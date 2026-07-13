"""kite_live.py — OPTIONAL live NSE data via the user's Kite Connect app (India only).

A freshness layer, never a dependency: every caller must tolerate None. The token
expires daily (the user logs in each trading morning for the gold-options study, which
shares the same Kite app), and the subscription itself may lapse — in EVERY failure
case (no config file, stale token, dead API, missing library) the app silently keeps
using its normal free-data route, byte-identical to today. Render has no config file,
so production always runs the fallback.

Config: env KITE_CONFIG points at the gold-study config.json (api_key + access_token,
refreshed daily by its login flow). Defaults to that project's local path.
"""

from __future__ import annotations

import datetime as _dt
import json
import os
import time

_CONFIG_PATH = os.environ.get(
    "KITE_CONFIG", r"C:\Users\dell\Downloads\Sonia\SM\gold-options-study\config.json")

# availability probe result, re-checked every 10 minutes so a later morning login
# gets picked up (and a mid-day API death gets noticed).
_STATE = {"ok": None, "checked": 0.0, "kite": None}
_PROBE_EVERY = 600


def _connect():
    from kiteconnect import KiteConnect  # import inside the guard — lib may be absent
    with open(_CONFIG_PATH, encoding="utf-8") as fh:
        cfg = json.load(fh)
    k = KiteConnect(api_key=cfg["api_key"])
    k.set_access_token(cfg["access_token"])
    k.profile()          # the truthful probe: raises if the token/subscription is dead
    return k


def available() -> bool:
    now = time.time()
    if _STATE["ok"] is not None and now - _STATE["checked"] < _PROBE_EVERY:
        return _STATE["ok"]
    try:
        _STATE["kite"] = _connect()
        _STATE["ok"] = True
    except Exception:  # noqa: BLE001  any failure at all -> fall back silently
        _STATE["kite"] = None
        _STATE["ok"] = False
    _STATE["checked"] = now
    return _STATE["ok"]


def _kite():
    return _STATE["kite"] if available() else None


def session_fraction() -> float:
    """How much of the NSE session (09:15–15:30 IST) has elapsed — for judging
    'is today's volume heavy FOR THIS TIME OF DAY'. 1.0 outside market hours."""
    ist = _dt.datetime.utcnow() + _dt.timedelta(hours=5, minutes=30)
    start = ist.replace(hour=9, minute=15, second=0, microsecond=0)
    end = ist.replace(hour=15, minute=30, second=0, microsecond=0)
    if ist <= start or ist.weekday() >= 5:
        return 1.0                       # pre-open / weekend: yesterday's full bar
    if ist >= end:
        return 1.0
    return max((ist - start).total_seconds() / (375 * 60), 0.05)


def quotes(nse_symbols: list[str]) -> dict:
    """{symbol: {price, pct_1d, volume}} for bare NSE tradingsymbols. {} on any failure."""
    k = _kite()
    if not k or not nse_symbols:
        return {}
    out = {}
    try:
        keys = [f"NSE:{s}" for s in nse_symbols]
        for i in range(0, len(keys), 400):           # quote() cap is 500 instruments
            for key, q in k.quote(keys[i:i + 400]).items():
                sym = key.split(":", 1)[1]
                ltp = q.get("last_price")
                prev = (q.get("ohlc") or {}).get("close")
                if not ltp or not prev:
                    continue
                out[sym] = {"price": float(ltp),
                            "pct_1d": round((ltp / prev - 1) * 100, 2),
                            "volume": q.get("volume") or q.get("volume_traded")}
    except Exception:  # noqa: BLE001
        return {}
    return out


def nifty_pct() -> float | None:
    """Nifty 50's live move today, % — for the market strip. None on any failure."""
    k = _kite()
    if not k:
        return None
    try:
        q = k.quote(["NSE:NIFTY 50"])["NSE:NIFTY 50"]
        return round((q["last_price"] / q["ohlc"]["close"] - 1) * 100, 2)
    except Exception:  # noqa: BLE001
        return None
