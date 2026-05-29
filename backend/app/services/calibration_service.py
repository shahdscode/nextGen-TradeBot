"""
Confidence Calibration using Platt Scaling.

Problem: ML models are often overconfident — a model that says 90% confidence
might only be correct 70% of the time historically.

Fix: Fit a logistic regression mapping raw model scores → real probabilities.
After calibration, 75% confidence means the model was correct ~75% of the
time on held-out data.

Academic reference
------------------
Platt (1999) — Probabilistic Outputs for Support Vector Machines and
Comparisons to Regularized Likelihood Methods
"""
import logging
import os
import pickle
from typing import Any, Dict, List

import numpy as np

logger = logging.getLogger(__name__)


def fit_calibrator(
    raw_scores: np.ndarray,
    actual_outcomes: np.ndarray,
    save_path: str,
) -> Dict[str, Any]:
    """
    Fit Platt scaling (logistic regression) from raw model scores to real probabilities.

    Parameters
    ----------
    raw_scores      : 1-D array of model outputs in [0, 1]
    actual_outcomes : 1-D array of ground-truth labels (1 = correct prediction, 0 = wrong)
    save_path       : where to write the fitted calibrator (.pkl)

    Returns
    -------
    {
      "brier_score_before": float,
      "brier_score_after":  float,
      "reliability_data":   [{"bin_center": float, "fraction_positive": float, "count": int}]
    }
    """
    from sklearn.linear_model import LogisticRegression
    from sklearn.metrics import brier_score_loss
    from sklearn.calibration import calibration_curve

    raw_scores      = np.asarray(raw_scores,      dtype=np.float32).reshape(-1, 1)
    actual_outcomes = np.asarray(actual_outcomes, dtype=int)

    if len(raw_scores) < 20:
        raise ValueError(f"Too few samples to fit calibrator: {len(raw_scores)}")

    brier_before = float(brier_score_loss(actual_outcomes, raw_scores.flatten()))

    # Platt scaling: logistic regression on the scalar raw score
    calibrator = LogisticRegression(C=1.0, max_iter=1000, random_state=42, solver="lbfgs")
    calibrator.fit(raw_scores, actual_outcomes)
    cal_scores = calibrator.predict_proba(raw_scores)[:, 1]

    brier_after = float(brier_score_loss(actual_outcomes, cal_scores))

    # Reliability diagram data (10 bins)
    try:
        frac_pos, mean_pred = calibration_curve(actual_outcomes, cal_scores, n_bins=10)
        # Build bin counts
        bins = np.linspace(0, 1, 11)
        counts, _ = np.histogram(cal_scores, bins=bins)
        reliability_data = [
            {
                "bin_center":       round(float(mean_pred[i]), 3),
                "fraction_positive": round(float(frac_pos[i]),  3),
                "count":            int(counts[i]) if i < len(counts) else 0,
            }
            for i in range(len(mean_pred))
        ]
    except Exception:
        reliability_data = []

    # Save
    os.makedirs(os.path.dirname(save_path) or ".", exist_ok=True)
    with open(save_path, "wb") as f:
        pickle.dump(calibrator, f)

    result = {
        "brier_score_before": round(brier_before, 4),
        "brier_score_after":  round(brier_after,  4),
        "reliability_data":   reliability_data,
    }
    logger.info(
        "Calibrator fitted: Brier %.4f → %.4f (improvement %.4f), saved → %s",
        brier_before, brier_after, brier_before - brier_after, save_path,
    )
    return result


def calibrate_score(raw_score: float, calibrator_path: str) -> float:
    """
    Apply Platt-scaling calibration to a single raw model score.

    Returns the raw score unchanged if the calibrator file does not exist.
    """
    if not os.path.exists(calibrator_path):
        return float(raw_score)

    try:
        with open(calibrator_path, "rb") as f:
            calibrator = pickle.load(f)
        x = np.array([[raw_score]], dtype=np.float32)
        return float(calibrator.predict_proba(x)[0, 1])
    except Exception as exc:
        logger.warning("calibrate_score failed (%s) — returning raw score", exc)
        return float(raw_score)


def plot_reliability_diagram(
    reliability_data: List[Dict],
    save_path: str,
) -> str:
    """
    Save a reliability (calibration) diagram as PNG.

    X-axis: mean predicted probability per bin
    Y-axis: observed fraction of positives per bin
    The diagonal (y=x) represents perfect calibration.

    Parameters
    ----------
    reliability_data : output of fit_calibrator()["reliability_data"]
    save_path        : output PNG path

    Returns the save_path on success.
    """
    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt

        if not reliability_data:
            logger.warning("plot_reliability_diagram: no data — skipping")
            return save_path

        bin_centers = [d["bin_center"]       for d in reliability_data]
        frac_pos    = [d["fraction_positive"] for d in reliability_data]

        fig, ax = plt.subplots(figsize=(6, 5))
        ax.plot([0, 1], [0, 1], "k--", label="Perfect calibration", linewidth=1)
        ax.plot(bin_centers, frac_pos, "s-", color="#0d6efd", label="Model", linewidth=2)
        ax.set_xlabel("Mean predicted probability")
        ax.set_ylabel("Fraction of positives")
        ax.set_title("Reliability Diagram (Platt Scaling)")
        ax.legend(loc="upper left")
        ax.set_xlim(0, 1)
        ax.set_ylim(0, 1)
        ax.grid(True, alpha=0.3)
        fig.tight_layout()

        os.makedirs(os.path.dirname(save_path) or ".", exist_ok=True)
        fig.savefig(save_path, dpi=150)
        plt.close(fig)
        logger.info("Reliability diagram saved → %s", save_path)

    except Exception as exc:
        logger.warning("plot_reliability_diagram failed: %s", exc)

    return save_path
