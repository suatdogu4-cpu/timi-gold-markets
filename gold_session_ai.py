"""GOLD SCALP PRO / QUANT AI -- Phase 1: audited session feature preparation.

Research inspiration: https://github.com/soloshun/Quantitative-XAUUSD-Strategy
Upstream MIT license; this is an independent, read-only adaptation.

IMPORTANT: No XGBoost/LSTM inference or fitted model is included in Phase 1.
No API credentials, trade execution, signals, or fabricated probabilities.
Input must be true source-tagged hourly candles from ONE instrument.
"""
from __future__ import annotations

from collections import defaultdict
from datetime import date, datetime, timedelta, timezone
import math
import statistics
import time
from typing import Any

VERSION = "0.1.0"
MIN_TRAIN_ROWS = 120  # Prototype data gate, NOT a guarantee of model reliability.
VALID_SYMBOLS = {"XAUUSD", "XAUUSDT"}
HOUR = 3600


def _number(value: Any) -> float | None:
    try:
        v = float(value)
        return v if math.isfinite(v) else None
    except (ValueError, TypeError, OverflowError):
        return None


def _valid_hourly_candles(bars: list[dict], now_ts: int) -> tuple[list[dict], dict]:
    """Filter incomplete/invalid bars and retain one bar per UTC hour."""
    audit = {"received": len(bars), "invalid": 0, "unclosed": 0,
             "duplicates": 0, "valid_closed": 0}
    by_time: dict[int, dict] = {}
    for raw in bars:
        try:
            ts = int(raw["t"])
            o, h, l, c = (_number(raw.get(k)) for k in ("o", "h", "l", "c"))
            if (ts <= 0 or ts % HOUR != 0 or None in (o, h, l, c)
                    or min(o, h, l, c) <= 0 or l > h or not l <= o <= h
                    or not l <= c <= h):
                audit["invalid"] += 1
                continue
            if raw.get("complete") is False or ts + HOUR > now_ts:
                audit["unclosed"] += 1
                continue
            if ts in by_time:
                audit["duplicates"] += 1
                continue
            by_time[ts] = {"t": ts, "o": o, "h": h, "l": l, "c": c}
        except (TypeError, ValueError, KeyError, AttributeError):
            audit["invalid"] += 1
    valid = [by_time[t] for t in sorted(by_time)]
    audit["valid_closed"] = len(valid)
    return valid, audit


def _session_day(ts: int) -> date:
    dt = datetime.fromtimestamp(ts, timezone.utc)
    # The upstream study's Asia session starts at 22:00 UTC on the PREVIOUS day.
    return dt.date() + timedelta(days=1) if dt.hour >= 22 else dt.date()


def _expected_hours(day: date, name: str) -> list[int]:
    start = datetime(day.year, day.month, day.day, tzinfo=timezone.utc)
    if name == "asia":
        start -= timedelta(hours=2)  # previous day 22:00 -> today 07:00
        n = 10
    elif name == "london":
        start += timedelta(hours=8)  # today 08:00 -> 16:00
        n = 9
    else:
        raise ValueError("Unknown session")
    return [int(start.timestamp()) + i * HOUR for i in range(n)]


def _features(candles: list[dict]) -> dict:
    first, last = candles[0], candles[-1]
    log_returns = [math.log(candles[i]["c"] / candles[i - 1]["c"])
                   for i in range(1, len(candles))]
    return {
        "return_pct": 100 * (last["c"] / first["o"] - 1),
        "range_pct": 100 * (max(c["h"] for c in candles) / min(c["l"] for c in candles) - 1),
        "body_pct": 100 * (last["c"] - first["o"]) / first["o"],
        "hourly_log_return_stdev": statistics.pstdev(log_returns) if log_returns else 0.0,
        "close": last["c"],
    }


def build_session_rows(bars: list[dict], *, symbol: str = "XAUUSDT",
                       now_ts: int | None = None) -> dict:
    """Prepare feature rows for Hypothesis A (Asia -> London), WITHOUT training.

    Each labeled row uses ONLY its completed Asia candles for features. Its London
    label is attached only after all 9 London candles are closed. The live
    candidate contains *no* London data or prediction.
    """
    if symbol not in VALID_SYMBOLS:
        raise ValueError("Only XAUUSD and XAUUSDT supported")
    if not isinstance(bars, list):
        raise ValueError("bars must be a list")
    now_ts = int(now_ts if now_ts is not None else time.time())
    candles, audit = _valid_hourly_candles(bars, now_ts)
    grouped = defaultdict(dict)
    for b in candles:
        grouped[_session_day(b["t"])][b["t"]] = b

    rows = []
    candidate = None
    partial_asia = 0
    partial_london = 0
    now_day = datetime.fromtimestamp(now_ts, timezone.utc).date()
    for day in sorted(grouped):
        day_bars = grouped[day]
        asia_times = _expected_hours(day, "asia")
        lon_times = _expected_hours(day, "london")
        if not all(ts in day_bars for ts in asia_times):
            partial_asia += 1
            continue
        asia = _features([day_bars[ts] for ts in asia_times])
        feature = {"session_date_utc": day.isoformat(),
                   "feature_cutoff_utc": datetime.fromtimestamp(asia_times[-1] + HOUR, timezone.utc).isoformat(),
                   "asia_return_pct": round(asia["return_pct"], 6),
                   "asia_range_pct": round(asia["range_pct"], 6),
                   "asia_body_pct": round(asia["body_pct"], 6),
                   "asia_hourly_log_return_stdev": round(asia["hourly_log_return_stdev"], 9)}
        if all(ts in day_bars for ts in lon_times):
            london = _features([day_bars[ts] for ts in lon_times])
            rows.append({**feature,
                         "london_direction": int(london["return_pct"] > 0),
                         "london_return_pct": round(london["return_pct"], 6)})
        else:
            partial_london += 1
            # One live candidate at most; no London candles go into its features.
            london_start, london_end = lon_times[0], lon_times[-1] + HOUR
            if day == now_day and london_start <= now_ts < london_end:
                candidate = feature

    return {"symbol": symbol, "timeframe": "1H", "session_timezone": "UTC_FIXED",
            "source_warning": ("XAUUSDT Bitget futures is a proxy; do not merge its bars with XAUUSD spot"
                               if symbol == "XAUUSDT" else
                               "XAUUSD spot; requires an independently configured licensed data feed"),
            "audit": {**audit, "partial_asia_days": partial_asia,
                      "partial_london_days": partial_london},
            "rows": rows, "live_candidate": candidate}


def session_ai_status(bars: list[dict], *, symbol: str = "XAUUSDT",
                      now_ts: int | None = None) -> dict:
    data = build_session_rows(bars, symbol=symbol, now_ts=now_ts)
    count = len(data["rows"])
    return {
        "engine": "QUANT AI Session Research", "version": VERSION,
        "mode": "DATA_PREPARATION_ONLY", "orders_enabled": False,
        "model_loaded": False, "model_type": None, "prediction": None,
        "probability": None, "signals_enabled": False,
        "hypothesis": "A: completed Asia (22:00-07:59 UTC) -> London (08:00-16:59 UTC)",
        "symbol": symbol, "timeframe": "1H", "session_timezone": "UTC_FIXED",
        "labelled_samples": count, "min_prototype_samples": MIN_TRAIN_ROWS,
        "prototype_data_gate": count >= MIN_TRAIN_ROWS,
        "training_ready": False,  # leakage/walk-forward audit not yet implemented
        "live_candidate": data["live_candidate"],
        "last_completed_session": data["rows"][-1] if count else None,
        "audit": data["audit"], "source_warning": data["source_warning"],
        "warnings": [
            "No XGBoost/LSTM trained or executed in Phase 1; there is no LONG/SHORT recommendation.",
            "UTC windows follow upstream research, not DST-adjusted London exchange hours.",
            "A 500-700 H1 candle snapshot is not enough to validate a multi-year ML model.",
            "Use chronological walk-forward testing with spreads, fees, and slippage before activation."
        ]
    }
