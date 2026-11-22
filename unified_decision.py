"""Unified, auditable decision engine for GOLD SCALP PRO.

Research-only by default. The engine combines technical, flow, risk and
chronological self-learning signals. It never places orders.
"""
from __future__ import annotations

import hashlib
import json
import math
import sqlite3
import statistics
import time
from contextlib import closing
from pathlib import Path
from typing import Any


VERSION = "1.0.0"
MIN_TRAIN_OUTCOMES = 100
MIN_FORWARD_ACCURACY = 0.55
LONG_THRESHOLD = 0.58
SHORT_THRESHOLD = 0.42


def _number(value: Any, default: float | None = None) -> float | None:
    try:
        result = float(value)
        return result if math.isfinite(result) else default
    except (TypeError, ValueError, OverflowError):
        return default


def sigmoid(value: float) -> float:
    value = max(-35.0, min(35.0, value))
    if value >= 0:
        return 1.0 / (1.0 + math.exp(-value))
    exp_value = math.exp(value)
    return exp_value / (1.0 + exp_value)


def _clamp(value: float, low: float, high: float) -> float:
    return max(low, min(high, value))


def features_from_market(bars: list[dict], indicators: dict, mtf: list[dict],
                         flow: dict, risk: dict, symbol: str) -> tuple[list[float], dict]:
    latest = indicators.get("latest", {}) if isinstance(indicators, dict) else {}
    close = _number(latest.get("close"))
    ema20 = _number(latest.get("ema20"))
    ema50 = _number(latest.get("ema50"))
    rsi = _number(latest.get("rsi14"))
    macd_hist = _number(latest.get("macd_hist"))
    adx = _number(latest.get("adx14"))
    atr_pct = _number(latest.get("atr_pct"))
    zscore = _number(latest.get("zscore20"))

    trend = (1.0 if close is not None and ema20 is not None and close > ema20 and ema20 > ema50
             else -1.0 if close is not None and ema20 is not None and close < ema20 and ema20 < ema50
             else 0.0)
    momentum = _clamp(((rsi or 50.0) - 50.0) / 30.0, -1.0, 1.0)
    macd = _clamp((macd_hist or 0.0) / max(abs(macd_hist or 0.0), close or 1.0) * 100.0, -1.0, 1.0)
    adx_strength = _clamp((adx or 0.0) / 50.0, 0.0, 1.0)
    zscore_feature = _clamp((zscore or 0.0) / 3.0, -1.0, 1.0)
    atr_feature = _clamp((atr_pct or 0.0) / 2.0, 0.0, 1.0)

    mtf_directions = [row.get("direction") for row in (mtf or [])]
    mtf_feature = ((mtf_directions.count("LONG") - mtf_directions.count("SHORT"))
                   / max(len(mtf_directions), 1))

    imbalance = _clamp(_number(flow.get("imbalance"), 0.0) or 0.0, -1.0, 1.0)
    aggressor = _clamp(_number(flow.get("aggressor_ratio"), 0.0) or 0.0, -1.0, 1.0)
    spread = _number(flow.get("spread_pct"))
    recent = _number(risk.get("momentum20_pct"))
    momentum20 = _clamp((recent or 0.0) / 2.0, -1.0, 1.0)
    if symbol != "XAUUSDT":
        imbalance = aggressor = 0.0

    feature_names = (
        "trend", "rsi_momentum", "macd", "adx", "zscore",
        "mtf", "book_imbalance", "aggressor", "momentum20", "atr_pct",
    )
    values = [trend, momentum, macd, adx_strength, zscore_feature,
              mtf_feature, imbalance, aggressor, momentum20, atr_feature]
    return values, dict(zip(feature_names, values))


class UnifiedDecisionStore:
    def __init__(self, root: Path):
        self.path = root / "models" / "unified_decision.sqlite3"
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._init_db()

    def _connect(self):
        connection = sqlite3.connect(self.path, timeout=10)
        connection.row_factory = sqlite3.Row
        return connection

    def _init_db(self):
        with closing(self._connect()) as db:
            db.execute("""
                CREATE TABLE IF NOT EXISTS forecasts (
                    id TEXT PRIMARY KEY,
                    symbol TEXT NOT NULL,
                    tf TEXT NOT NULL,
                    forecast_ts INTEGER NOT NULL,
                    settle_ts INTEGER NOT NULL,
                    entry_price REAL NOT NULL,
                    probability REAL NOT NULL,
                    direction TEXT NOT NULL,
                    features TEXT NOT NULL,
                    outcome INTEGER,
                    return_pct REAL,
                    settled_ts INTEGER
                )
            """)
            db.execute("""
                CREATE TABLE IF NOT EXISTS model_state (
                    key TEXT PRIMARY KEY,
                    weights TEXT NOT NULL,
                    bias REAL NOT NULL,
                    samples INTEGER NOT NULL,
                    accuracy REAL,
                    brier REAL,
                    updated_ts INTEGER NOT NULL
                )
            """)
            db.commit()

    def weights(self, symbol: str, tf: str) -> tuple[list[float], float, dict]:
        key = f"{symbol}:{tf}"
        with closing(self._connect()) as db:
            row = db.execute("SELECT * FROM model_state WHERE key=?", (key,)).fetchone()
        if not row:
            return [0.0] * 10, 0.0, {
                "samples": 0, "accuracy": None, "brier": None,
                "updated_ts": None,
            }
        try:
            weights = json.loads(row["weights"])
            if len(weights) != 10:
                raise ValueError("bad weight count")
            return weights, float(row["bias"]), {
                "samples": int(row["samples"]),
                "accuracy": row["accuracy"],
                "brier": row["brier"],
                "updated_ts": row["updated_ts"],
            }
        except (json.JSONDecodeError, ValueError, TypeError):
            return [0.0] * 10, 0.0, {"samples": 0, "accuracy": None, "brier": None,
                                     "updated_ts": None}

    def save_model(self, symbol: str, tf: str, weights: list[float], bias: float,
                   samples: int, accuracy: float | None, brier: float | None):
        key = f"{symbol}:{tf}"
        with closing(self._connect()) as db:
            db.execute("""
                INSERT INTO model_state(key,weights,bias,samples,accuracy,brier,updated_ts)
                VALUES(?,?,?,?,?,?,?)
                ON CONFLICT(key) DO UPDATE SET
                    weights=excluded.weights,bias=excluded.bias,samples=excluded.samples,
                    accuracy=excluded.accuracy,brier=excluded.brier,
                    updated_ts=excluded.updated_ts
            """, (key, json.dumps(weights), bias, samples, accuracy, brier, int(time.time())))
            db.commit()

    def pending(self, symbol: str, tf: str):
        with closing(self._connect()) as db:
            rows = db.execute("""
                SELECT * FROM forecasts
                WHERE symbol=? AND tf=? AND outcome IS NULL
                ORDER BY forecast_ts
            """, (symbol, tf)).fetchall()
        return [dict(row) for row in rows]

    def outcomes(self, symbol: str, tf: str) -> list[dict]:
        with closing(self._connect()) as db:
            rows = db.execute("""
                SELECT probability,outcome,features FROM forecasts
                WHERE symbol=? AND tf=? AND outcome IS NOT NULL
                ORDER BY settled_ts
            """, (symbol, tf)).fetchall()
        return [dict(row) for row in rows]

    def record_forecast(self, symbol: str, tf: str, forecast_ts: int, settle_ts: int,
                        entry_price: float, probability: float, direction: str,
                        features: dict):
        forecast_id = hashlib.sha256(
            f"{symbol}|{tf}|{forecast_ts}|{entry_price}|{probability:.8f}".encode()
        ).hexdigest()
        with closing(self._connect()) as db:
            db.execute("""
                INSERT OR IGNORE INTO forecasts
                (id,symbol,tf,forecast_ts,settle_ts,entry_price,probability,direction,features)
                VALUES(?,?,?,?,?,?,?,?,?)
            """, (forecast_id, symbol, tf, forecast_ts, settle_ts, entry_price, probability,
                  direction, json.dumps(features, sort_keys=True)))
            db.commit()

    def settle(self, record: dict, exit_price: float):
        return_pct = 100.0 * (exit_price / record["entry_price"] - 1.0)
        if record["direction"] == "LONG":
            outcome = 1 if exit_price > record["entry_price"] else 0
        elif record["direction"] == "SHORT":
            outcome = 1 if exit_price < record["entry_price"] else 0
        else:
            outcome = None
        if outcome is None:
            return
        with closing(self._connect()) as db:
            db.execute("""
                UPDATE forecasts SET outcome=?,return_pct=?,settled_ts=?
                WHERE id=? AND outcome IS NULL
            """, (outcome, return_pct, int(time.time()), record["id"]))
            db.commit()


def _online_train(store: UnifiedDecisionStore, symbol: str, tf: str):
    outcomes = store.outcomes(symbol, tf)
    weights, bias, meta = store.weights(symbol, tf)
    if not outcomes:
        return weights, bias, meta

    # Replays are chronological and capped to the most recent 5000 settled
    # observations. A small L2-regularized logistic update is a genuinely
    # improving online calibration layer, not a guaranteed profit model.
    learning_rate = 0.035
    latest = outcomes[-5000:]
    for row in latest:
        try:
            named = json.loads(row["features"])
            values = [float(named.get(name, 0.0)) for name in (
                "trend", "rsi_momentum", "macd", "adx", "zscore",
                "mtf", "book_imbalance", "aggressor", "momentum20", "atr_pct",
            )]
        except (json.JSONDecodeError, TypeError, ValueError):
            continue
        probability = sigmoid(bias + sum(w*x for w, x in zip(weights, values)))
        error = int(row["outcome"]) - probability
        for index, value in enumerate(values):
            weights[index] = (1.0-learning_rate*0.002)*weights[index] + learning_rate*error*value
        bias += learning_rate * error

    predictions = [float(row["probability"]) for row in outcomes]
    labels = [int(row["outcome"]) for row in outcomes]
    accuracy = sum((1 if p >= 0.5 else 0) == y for p, y in zip(predictions, labels)) / len(labels)
    brier = sum((p - y) ** 2 for p, y in zip(predictions, labels)) / len(labels)
    meta.update({"samples": len(labels), "accuracy": accuracy, "brier": brier})
    store.save_model(symbol, tf, weights, bias, len(labels), accuracy, brier)
    return weights, bias, meta


def settle_pending(store: UnifiedDecisionStore, symbol: str, tf: str, bars: list[dict]):
    now = int(time.time())
    for record in store.pending(symbol, tf):
        if record["settle_ts"] > now:
            continue
        candidates = [bar for bar in bars if int(bar["t"]) >= int(record["settle_ts"])]
        if candidates:
            store.settle(record, float(candidates[0]["c"]))


def build_unified_decision(root: Path, symbol: str, tf: str, bars: list[dict],
                           indicators: dict, mtf: list[dict], snapshot: dict,
                           quant_stats: dict, quant_hub: dict | None = None) -> dict:
    store = UnifiedDecisionStore(root)
    settle_pending(store, symbol, tf, bars)
    weights, bias, learning = _online_train(store, symbol, tf)

    latest = indicators.get("latest", {}) if isinstance(indicators, dict) else {}
    c = _number(latest.get("close"))
    atr = _number(latest.get("atr14"))
    valid = snapshot.get("valid", {}) if isinstance(snapshot, dict) else {}
    flow = snapshot.get("flow", {}) if isinstance(snapshot, dict) else {}

    values, named_features = features_from_market(
        bars, indicators, mtf, flow, quant_stats, symbol
    )
    raw_model_probability = sigmoid(bias + sum(w*x for w, x in zip(weights, values)))

    # The deterministic score remains visible and auditable. It is deliberately
    # not substituted by the ML calibration before validation gates are met.
    deterministic = 0.50
    if values:
        deterministic = sigmoid(sum(v*w for v, w in zip(values, (1.1, 0.8, 0.7, 0.25, -0.4,
                                                               0.9, 0.7, 0.6, 0.8, -0.3))))

    model_approved = (learning["samples"] >= MIN_TRAIN_OUTCOMES
                      and learning["accuracy"] is not None
                      and learning["accuracy"] >= MIN_FORWARD_ACCURACY)
    probability = (0.65*deterministic + 0.35*raw_model_probability
                   if model_approved else deterministic)

    veto = []
    if len(bars) < 210:
        veto.append("En az 210 tamamlanmış mum gerekli")
    if snapshot.get("candles_valid") is False:
        veto.append("Mum verisi güncel değil")
    if symbol == "XAUUSDT":
        if not valid.get("ticker"):
            veto.append("Canlı fiyat gecikmeli")
        if not valid.get("book"):
            veto.append("Emir defteri eksik/gecikmeli")
        if not valid.get("trades"):
            veto.append("İşlem akışı eksik/gecikmeli")
        if (flow.get("trades60") or 0) < 5:
            veto.append("60 saniyede yeterli işlem yok")
        spread_pct = _number(flow.get("spread_pct"))
        if spread_pct is None or spread_pct > 0.2:
            veto.append("Spread ölçülemedi veya çok geniş")
    else:
        if not snapshot.get("spot"):
            veto.append("OANDA XAUUSD spot verisi doğrulanamadı")
    if c is None or atr is None or atr <= 0:
        veto.append("Fiyat veya ATR hesaplanamadı")

    if veto:
        direction = "BEKLE"
    elif probability >= LONG_THRESHOLD:
        direction = "LONG"
    elif probability <= SHORT_THRESHOLD:
        direction = "SHORT"
    else:
        direction = "BEKLE"

    tf_minutes = {"1m": 1, "3m": 3, "5m": 5, "15m": 15,
                  "30m": 30, "1H": 60, "4H": 240, "1D": 1440}.get(tf, 5)
    forecast_ts = int(bars[-1]["t"]) if bars else int(time.time())
    settle_ts = forecast_ts + tf_minutes * 12 * 60
    if direction != "BEKLE" and bars:
        store.record_forecast(
            symbol, tf, forecast_ts, settle_ts, c, probability, direction, named_features
        )

    stop = c - 1.5*atr if direction == "LONG" and c is not None and atr is not None else (
        c + 1.5*atr if direction == "SHORT" and c is not None and atr is not None else None
    )
    target = c + 2.25*atr if direction == "LONG" and c is not None and atr is not None else (
        c - 2.25*atr if direction == "SHORT" and c is not None and atr is not None else None
    )

    return {
        "engine": "GOLD UNIFIED DECISION ENGINE",
        "version": VERSION,
        "symbol": symbol,
        "tf": tf,
        "mode": "SHADOW_RESEARCH_ONLY",
        "orders_enabled": False,
        "live_execution_enabled": False,
        "direction": direction,
        "probability_up": round(probability, 6),
        "confidence": round(abs(probability-0.5)*2.0, 6),
        "model_approved": model_approved,
        "learning": learning,
        "features": named_features,
        "deterministic_probability_up": round(deterministic, 6),
        "ml_probability_up": round(raw_model_probability, 6),
        "thresholds": {"long": LONG_THRESHOLD, "short": SHORT_THRESHOLD},
        "stop": round(stop, 5) if stop is not None else None,
        "target": round(target, 5) if target is not None else None,
        "veto": veto,
        "reasons": [
            "Kapanmış mum ve zamanlama kontrollü tek otorite",
            "İleri zaman sonucu otomatik olarak SQLite gölge günlüğüne kaydedilir",
            "LIVE emir yetkisi varsayılan olarak kapalı",
        ],
        "quant_stats": quant_stats,
        "quant_hub_included": isinstance(quant_hub, dict),
        "forecast_horizon_minutes": tf_minutes*12,
        "timestamp_ms": int(time.time()*1000),
    }
