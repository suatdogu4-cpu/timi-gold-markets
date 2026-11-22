import tempfile
import unittest
from pathlib import Path

from unified_decision import build_unified_decision


class UnifiedDecisionTests(unittest.TestCase):
    def test_insufficient_data_returns_wait(self):
        with tempfile.TemporaryDirectory() as tmp:
            result = build_unified_decision(
                Path(tmp), "XAUUSDT", "5m",
                bars=[{"t": i*300, "o": 2300+i, "h": 2302+i,
                       "l": 2298+i, "c": 2301+i, "v": 10}
                      for i in range(20)],
                indicators={"latest": {}},
                mtf=[],
                snapshot={"valid": {"ticker": True, "book": True, "trades": True},
                          "flow": {"trades60": 20, "spread_pct": 0.01},
                          "candles_valid": True},
                quant_stats={"status": "insufficient"},
            )
            self.assertEqual(result["direction"], "BEKLE")
            self.assertIn("En az 210 tamamlanmış mum gerekli", result["veto"])
            self.assertFalse(result["orders_enabled"])

    def test_fresh_valid_data_is_deterministic_wait_or_signal(self):
        bars=[]
        start=2000000000
        for i in range(260):
            c=2300+i*.05
            bars.append({"t":start+i*300,"o":c-.2,"h":c+.5,
                         "l":c-.5,"c":c,"v":100})
        indicators={
            "latest": {
                "close": 2312.95, "ema20": 2312.0, "ema50": 2310.0,
                "rsi14": 65.0, "macd_hist": 0.8, "adx14": 32.0,
                "atr14": 2.5, "atr_pct": 0.108, "zscore20": 1.2,
            }
        }
        mtf=[{"direction":"LONG"}]*5
        with tempfile.TemporaryDirectory() as tmp:
            result=build_unified_decision(
                Path(tmp),"XAUUSDT","5m",bars,indicators,mtf,
                {"valid":{"ticker":True,"book":True,"trades":True},
                 "flow":{"trades60":30,"spread_pct":0.01,
                         "imbalance":0.2,"aggressor_ratio":0.3},
                 "candles_valid":True},
                {"status":"ready","momentum20_pct":0.4},
            )
            self.assertIn(result["direction"], ("LONG","SHORT","BEKLE"))
            self.assertFalse(result["live_execution_enabled"])
            self.assertGreaterEqual(result["probability_up"], 0.0)
            self.assertLessEqual(result["probability_up"], 1.0)


if __name__=="__main__":
    unittest.main()
