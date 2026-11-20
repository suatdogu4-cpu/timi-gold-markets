"""Self-contained Phase 1 tests: python -m unittest -v test_gold_session_ai.py"""
import unittest
from datetime import date, datetime, timedelta, timezone
from gold_session_ai import build_session_rows, session_ai_status


def t(y, m, d, hour):
    return int(datetime(y, m, d, hour, tzinfo=timezone.utc).timestamp())


def candle(ts, open_price, close_price=None):
    close_price = float(close_price if close_price is not None else open_price)
    open_price = float(open_price)
    return {"t": ts, "o": open_price, "c": close_price,
            "h": max(open_price, close_price) + 0.1,
            "l": min(open_price, close_price) - 0.1, "v": 1}


def session(day=date(2026, 11, 19), finish_london=True):
    start = datetime(day.year, day.month, day.day, tzinfo=timezone.utc) - timedelta(hours=2)
    bars = [candle(int((start + timedelta(hours=i)).timestamp()), 4000+i, 4000+i+0.2)
            for i in range(10)]
    if finish_london:
        bars += [candle(int((start + timedelta(hours=i)).timestamp()), 4010+i, 4010+i+0.3)
                 for i in range(10, 19)]
    return bars


class SessionFeatureTests(unittest.TestCase):
    def test_cross_midnight_labels_only_after_london_complete(self):
        bars = session()
        result = build_session_rows(bars, now_ts=t(2026, 11, 19, 18))
        self.assertEqual(len(result["rows"]), 1)
        row = result["rows"][0]
        self.assertEqual(row["session_date_utc"], "2026-11-19")
        self.assertEqual(row["feature_cutoff_utc"], "2026-11-19T08:00:00+00:00")
        self.assertEqual(row["london_direction"], 1)

    def test_live_candidate_uses_asia_only(self):
        bars = session(finish_london=False)
        result = build_session_rows(bars, now_ts=t(2026, 11, 19, 12))
        self.assertEqual(len(result["rows"]), 0)
        self.assertIsNotNone(result["live_candidate"])
        self.assertNotIn("london_direction", result["live_candidate"])
        self.assertNotIn("prediction", result["live_candidate"])

    def test_invalid_future_bars_and_gaps_are_rejected(self):
        bars = session()
        bars[0]["c"] = -10
        result = build_session_rows(bars, now_ts=t(2026, 11, 19, 10))
        self.assertEqual(len(result["rows"]), 0)
        self.assertEqual(result["audit"]["invalid"], 1)
        self.assertGreater(result["audit"]["unclosed"], 0)

    def test_no_model_claims_and_symbol_separation(self):
        s = session_ai_status(session(), symbol="XAUUSDT", now_ts=t(2026, 11, 19, 18))
        self.assertFalse(s["model_loaded"])
        self.assertFalse(s["orders_enabled"])
        self.assertIsNone(s["prediction"])
        self.assertEqual(s["labelled_samples"], 1)
        with self.assertRaises(ValueError):
            session_ai_status(session(), symbol="BTCUSDT", now_ts=t(2026, 11, 19, 18))


if __name__ == "__main__":
    unittest.main()
