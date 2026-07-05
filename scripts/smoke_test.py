#!/usr/bin/env python3
"""
End-to-end smoke test for the NextGen TradeBot API.

Verifies the critical path in one command: health, auth (register/login/me),
authorization gates (401 without a token), public signals, meta-learner status,
paper-trading endpoints, and backtest scoping. Prints a pass/fail table and
exits non-zero if anything critical fails — so you can gate a demo/deploy on it.

Usage:
    python scripts/smoke_test.py                         # localhost:8002
    python scripts/smoke_test.py --base-url https://api.example.com
    python scripts/smoke_test.py --base-url http://194.163.179.126:8002
"""
from __future__ import annotations

import argparse
import sys
import time
import uuid

import requests

TIMEOUT = 15


class Runner:
    def __init__(self, base_url: str):
        self.base = base_url.rstrip("/")
        self.results: list[tuple[str, bool, str]] = []
        self.token: str | None = None
        # Ignore ambient HTTP(S)_PROXY env vars — a machine-level proxy must not
        # intercept our direct API calls (this silently breaks localhost tests).
        self.session = requests.Session()
        self.session.trust_env = False

    def _url(self, path: str) -> str:
        return f"{self.base}{path}"

    def check(self, name: str, ok: bool, detail: str = "") -> bool:
        self.results.append((name, ok, detail))
        mark = "\033[92m✓\033[0m" if ok else "\033[91m✗\033[0m"
        print(f"  {mark} {name}" + (f"  — {detail}" if detail else ""))
        return ok

    def _req(self, method: str, path: str, auth: bool = False, **kw):
        headers = kw.pop("headers", {})
        if auth and self.token:
            headers["Authorization"] = f"Bearer {self.token}"
        try:
            return self.session.request(method, self._url(path), headers=headers,
                                        timeout=TIMEOUT, **kw)
        except Exception as exc:
            return exc

    # ── individual checks ──────────────────────────────────────────────────
    def run(self) -> bool:
        print(f"\nSmoke test against: {self.base}\n")

        r = self._req("GET", "/health")
        self.check("health returns ok",
                   not isinstance(r, Exception) and r.status_code == 200
                   and r.json().get("status") == "ok",
                   detail=(str(r) if isinstance(r, Exception) else f"http {r.status_code}"))

        r = self._req("GET", "/api/info")
        self.check("api/info reachable",
                   not isinstance(r, Exception) and r.status_code == 200,
                   detail=(str(r) if isinstance(r, Exception) else f"http {r.status_code}"))

        # Authorization gate: /me without a token must be 401
        r = self._req("GET", "/api/auth/me")
        self.check("auth gate: /me is 401 without token",
                   not isinstance(r, Exception) and r.status_code == 401,
                   detail=("no response" if isinstance(r, Exception) else f"http {r.status_code}"))

        # Register a throwaway user
        uname = f"smoke_{uuid.uuid4().hex[:8]}"
        pw = "smoketest123"
        r = self._req("POST", "/api/auth/register",
                      json={"username": uname, "password": pw, "email": f"{uname}@example.com"})
        registered = not isinstance(r, Exception) and r.status_code in (200, 201)
        self.check("register new user", registered,
                   detail=("no response" if isinstance(r, Exception) else f"http {r.status_code}"))

        # Login
        r = self._req("POST", "/api/auth/login", json={"username": uname, "password": pw})
        logged_in = not isinstance(r, Exception) and r.status_code == 200 and r.json().get("access_token")
        if logged_in:
            self.token = r.json()["access_token"]
        self.check("login returns token", bool(logged_in),
                   detail=("no response" if isinstance(r, Exception) else f"http {r.status_code}"))

        # /me with token
        r = self._req("GET", "/api/auth/me", auth=True)
        self.check("authenticated /me works",
                   not isinstance(r, Exception) and r.status_code == 200
                   and r.json().get("username") == uname)

        # Public signals feed
        r = self._req("GET", "/api/signals/top?market=us&limit=5")
        self.check("public signals feed",
                   not isinstance(r, Exception) and r.status_code == 200
                   and isinstance(r.json(), list),
                   detail=("" if isinstance(r, Exception) else
                           f"{len(r.json())} signals" if r.status_code == 200 else f"http {r.status_code}"))

        # Meta-learner status (report loaded state)
        r = self._req("GET", "/api/ml/meta/status")
        loaded = (not isinstance(r, Exception) and r.status_code == 200
                  and bool(r.json().get("loaded")))
        self.check("meta-learner status reachable",
                   not isinstance(r, Exception) and r.status_code == 200,
                   detail=f"loaded={loaded}")

        # Paper-trading auth gate
        r = self._req("GET", "/api/paper-trading/status")
        self.check("paper status is 401 without token",
                   not isinstance(r, Exception) and r.status_code == 401)

        r = self._req("GET", "/api/paper-trading/status", auth=True)
        self.check("authenticated paper status works",
                   not isinstance(r, Exception) and r.status_code == 200,
                   detail=("" if isinstance(r, Exception) else f"http {r.status_code}"))

        r = self._req("GET", "/api/paper-trading/command-center", auth=True)
        self.check("command center reachable",
                   not isinstance(r, Exception) and r.status_code == 200,
                   detail=("" if isinstance(r, Exception) else f"http {r.status_code}"))

        r = self._req("GET", "/api/paper-trading/analytics", auth=True)
        self.check("portfolio analytics reachable",
                   not isinstance(r, Exception) and r.status_code == 200,
                   detail=("" if isinstance(r, Exception) else f"http {r.status_code}"))

        r = self._req("GET", "/api/paper-trading/trade-log", auth=True)
        self.check("trade log reachable",
                   not isinstance(r, Exception) and r.status_code == 200
                   and isinstance(r.json(), list))

        # Backtest list auth gate
        r = self._req("GET", "/api/backtest")
        self.check("backtest list is 401 without token",
                   not isinstance(r, Exception) and r.status_code == 401)

        # forgot-password returns generic 200 (no account leak). A 429 here means
        # the rate limiter engaged (also a healthy signal on repeated runs).
        r = self._req("POST", "/api/auth/forgot-password", json={"identifier": uname})
        self.check("forgot-password works (or rate-limited)",
                   not isinstance(r, Exception) and r.status_code in (200, 429),
                   detail=(str(r) if isinstance(r, Exception) else
                           f"http {r.status_code}"
                           + (" — rate-limited" if r.status_code == 429 else "")))

        return self.summary()

    def summary(self) -> bool:
        passed = sum(1 for _, ok, _ in self.results if ok)
        total = len(self.results)
        all_ok = passed == total
        color = "\033[92m" if all_ok else "\033[91m"
        print(f"\n{color}{passed}/{total} checks passed\033[0m")
        if not all_ok:
            print("\nFailed:")
            for name, ok, detail in self.results:
                if not ok:
                    print(f"  - {name} ({detail})")
        return all_ok


def main():
    ap = argparse.ArgumentParser(description="NextGen TradeBot API smoke test")
    ap.add_argument("--base-url", default="http://localhost:8002",
                    help="API base URL (default: http://localhost:8002)")
    args = ap.parse_args()
    ok = Runner(args.base_url).run()
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
