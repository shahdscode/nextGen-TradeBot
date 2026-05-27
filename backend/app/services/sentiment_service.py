"""
Sentiment service.
- English: FinBERT (ProsusAI/finbert) — loaded lazily on first use.
- Arabic:  AraBERT (aubmindlab/bert-base-arabertv02) — loaded lazily on first use
           when Arabic text is detected.
- Fallback: keyword-based scorer when transformers is unavailable.
"""
import re
import requests
import numpy as np
from typing import List, Dict, Any, Optional
from datetime import datetime, timedelta

from app.config import settings

try:
    from transformers import pipeline as hf_pipeline
    TRANSFORMERS_AVAILABLE = True
except ImportError:
    TRANSFORMERS_AVAILABLE = False

_finbert_pipeline  = None   # English FinBERT
_arabert_pipeline  = None   # Arabic AraBERT
_arabert_attempted = False  # avoid re-trying a failed load


# ── Arabic language detection ─────────────────────────────────────────────────

_ARABIC_RE = re.compile(r"[؀-ۿݐ-ݿࢠ-ࣿ]+")


def _is_arabic(text: str, threshold: float = 0.30) -> bool:
    """Return True if ≥ threshold fraction of word-characters are Arabic script."""
    if not text:
        return False
    arabic_chars = sum(len(m.group()) for m in _ARABIC_RE.finditer(text))
    total_chars  = len(re.sub(r"\s", "", text)) or 1
    return arabic_chars / total_chars >= threshold


# ── Model loaders ─────────────────────────────────────────────────────────────

def _get_finbert():
    global _finbert_pipeline
    if _finbert_pipeline is None and TRANSFORMERS_AVAILABLE:
        try:
            _finbert_pipeline = hf_pipeline(
                "sentiment-analysis",
                model="ProsusAI/finbert",
                return_all_scores=True,
                device=-1,  # CPU
            )
        except Exception:
            _finbert_pipeline = None
    return _finbert_pipeline


def _get_arabert():
    """
    Lazily load AraBERT for Arabic-language sentiment.
    Model: aubmindlab/bert-base-arabertv02 (~500 MB, downloaded once from HuggingFace).
    Falls back to keyword scorer if the download fails or transformers is not installed.
    """
    global _arabert_pipeline, _arabert_attempted
    if _arabert_attempted:
        return _arabert_pipeline
    _arabert_attempted = True

    if not TRANSFORMERS_AVAILABLE:
        return None

    try:
        _arabert_pipeline = hf_pipeline(
            "sentiment-analysis",
            model="aubmindlab/bert-base-arabertv02",
            return_all_scores=True,
            device=-1,
        )
    except Exception:
        # Model not cached locally — fall back silently to keyword scorer
        _arabert_pipeline = None
    return _arabert_pipeline


# ── Core scoring ─────────────────────────────────────────────────────────────

def score_headline(headline: str) -> Dict[str, Any]:
    """Score a single headline. Returns label + score in [-1, 1]."""
    if not headline or not headline.strip():
        return {"label": "neutral", "score": 0.0}

    text = headline.strip()[:512]

    if _is_arabic(text):
        pipe = _get_arabert()
        if pipe is not None:
            try:
                result = pipe(text)[0]
                scores = {item["label"].lower(): item["score"] for item in result}
                net    = scores.get("positive", 0) - scores.get("negative", 0)
                label  = max(scores, key=scores.get)
                return {"label": label, "score": round(float(net), 4)}
            except Exception:
                pass
    else:
        pipe = _get_finbert()
        if pipe is not None:
            try:
                result = pipe(text)[0]
                scores = {item["label"].lower(): item["score"] for item in result}
                net    = scores.get("positive", 0) - scores.get("negative", 0)
                label  = max(scores, key=scores.get)
                return {"label": label, "score": round(float(net), 4)}
            except Exception:
                pass

    return _keyword_sentiment(text)


def fetch_and_score(ticker: str, api_key: Optional[str] = None) -> Dict[str, Any]:
    """Fetch recent news headlines for ticker and return aggregated sentiment."""
    headlines = _fetch_headlines(ticker, api_key or settings.newsapi_key)

    demo = False
    if not headlines:
        if not settings.market_allow_demo_fallback:
            return {
                "label":             "neutral",
                "score":             0.0,
                "headline_count":    0,
                "individual_scores": [],
                "headlines":         [],
                "source":            "unavailable",
            }
        headlines = _demo_headlines(ticker)
        demo = True

    scores     = [score_headline(h) for h in headlines[:10]]
    net_scores = [s["score"] for s in scores]
    mean_score = float(np.mean(net_scores))

    if mean_score > 0.15:
        label = "positive"
    elif mean_score < -0.15:
        label = "negative"
    else:
        label = "neutral"

    return {
        "label":             label,
        "score":             round(mean_score, 4),
        "headline_count":    len(headlines),
        "individual_scores": scores[:5],
        "headlines":         headlines[:5],
        "source":            "demo" if demo else "live",
    }


# ── Internal helpers ──────────────────────────────────────────────────────────

def _extract_title_from_news_item(item: dict) -> str:
    """Handle both old yfinance format (title at root) and new format (≥0.2.50, nested)."""
    content = item.get("content") or {}
    if isinstance(content, dict):
        title = content.get("title") or content.get("summary") or ""
        desc  = content.get("description") or content.get("summary") or ""
        text  = (title + " " + desc).strip()
        if text:
            return text
    title = item.get("title") or ""
    desc  = item.get("description") or item.get("summary") or ""
    return (title + " " + desc).strip()


def _fetch_headlines(ticker: str, api_key: str) -> List[str]:
    headlines = []

    # Try NewsAPI first (requires api_key in .env)
    if api_key:
        try:
            clean  = ticker.replace(".CA", "").replace("-", " ")
            url    = "https://newsapi.org/v2/everything"
            params = {
                "q":        clean,
                "language": "en",
                "sortBy":   "publishedAt",
                "pageSize": 10,
                "from":     (datetime.utcnow() - timedelta(days=7)).strftime("%Y-%m-%d"),
                "apiKey":   api_key,
            }
            resp = requests.get(url, params=params, timeout=10)
            if resp.ok:
                articles  = resp.json().get("articles", [])
                headlines = [
                    (a.get("title", "") + " " + (a.get("description") or "")).strip()
                    for a in articles
                ]
                headlines = [h for h in headlines if h]
        except Exception:
            pass

    # Fallback: yfinance news (handles both old and new API formats)
    if not headlines:
        try:
            import yfinance as yf
            raw_news = yf.Ticker(ticker).news or []
            for item in raw_news[:10]:
                text = _extract_title_from_news_item(item)
                if text:
                    headlines.append(text)
        except Exception:
            pass

    return headlines


def _demo_headlines(ticker: str) -> List[str]:
    """Plausible demo headlines when no live source is available."""
    clean = ticker.replace(".CA", "").replace("-", "").upper()
    return [
        f"{clean} shares trade in focus as investors assess quarterly outlook",
        f"Analysts maintain coverage on {clean} ahead of earnings season",
        f"{clean} volume picks up amid broader market moves",
        f"Market watchers eye {clean} support levels after recent session",
        f"{clean} among active names as sector rotation continues",
    ]


def _keyword_sentiment(text: str) -> Dict[str, Any]:
    text_lower = text.lower()
    positive_words = [
        "rise", "rally", "surge", "gain", "profit", "beat", "strong", "bull",
        "growth", "upgrade", "buy", "positive", "record", "high", "increase",
        # Arabic transliterations / common positive finance words
        "ارتفع", "نمو", "ربح", "إيجابي", "قوي",
    ]
    negative_words = [
        "fall", "drop", "plunge", "loss", "miss", "weak", "bear", "decline",
        "downgrade", "sell", "negative", "low", "decrease", "crash", "concern",
        # Arabic transliterations / common negative finance words
        "انخفض", "خسارة", "هبوط", "سلبي", "ضعيف",
    ]
    pos   = sum(1 for w in positive_words if w in text_lower)
    neg   = sum(1 for w in negative_words if w in text_lower)
    total = pos + neg or 1
    score = round((pos - neg) / total, 4)
    label = "positive" if score > 0.1 else ("negative" if score < -0.1 else "neutral")
    return {"label": label, "score": score}
