"""Local synthetic *tests only*; test candles are never used for a deployed model."""
import json
import math
from datetime import datetime,date,timedelta,timezone
from pathlib import Path
import random
import pytest
import tempfile
import unittest
from gold_ml_core import session_hours,session_dataset,live_status,clean_bars,train_xgb,predict_probability

UTC=timezone.utc

def fake_data(days=245, end_partial=False):
    start=date(2025,1,1);candles=[]
    rng=random.Random(99)
    for i in range(days):
        d=start+timedelta(days=i)
        ah,lh=session_hours(d)
        polarity=1 if i%3==0 or i%7==0 else -1
        base=2700+10*math.sin(i*.03)
        for j,t in enumerate(ah):
            op=base+j*.3*polarity;cl=op+.32*polarity+rng.uniform(-.08,.08)
            candles.append({'t':t,'o':op,'h':max(op,cl)+.2,'l':min(op,cl)-.2,'c':cl})
        if end_partial and i==days-1:continue
        # Highly learnable synthetic signal for portability testing only.
        for j,t in enumerate(lh):
            op=base+7+j*.25*polarity;cl=op+.42*polarity+rng.uniform(-.08,.08)
            candles.append({'t':t,'o':op,'h':max(op,cl)+.2,'l':min(op,cl)-.2,'c':cl})
    now=int(datetime.combine(start+timedelta(days=days+3),datetime.min.time(),tzinfo=UTC).timestamp())
    return candles,now

class GoldMLTest(unittest.TestCase):
    def test_closed_sessions_and_no_future_leakage(self):
        bars,now=fake_data(2,True)
        out=session_dataset(bars,now_s=now)
        self.assertEqual(len(out['rows']),1)
        self.assertEqual(out['audit']['partial_london'],1)
        f0=list(out['rows'][0]['features'])
        for b in bars:
            if b['t'] in session_hours(date(2025,1,1))[1]:
                b['c']=b['o']*.999
                b['l']=min(b['l'],b['c']*.999)
        self.assertEqual(f0,session_dataset(bars,now_s=now)['rows'][0]['features'])

    def test_reject_incomplete_future_invalid(self):
        bars,now=fake_data(1)
        bars[0]['h']=bars[0]['l']-.5
        bars.append({'t':now+3600,'o':1,'h':2,'l':.5,'c':1})
        _,n=clean_bars(bars,now)
        self.assertEqual(n,2)
        self.assertEqual(len(session_dataset(bars,now_s=now)['rows']),0)

    def test_train_and_export_verification(self):
        pytest.importorskip('xgboost',reason='XGBoost training dependencies are installed in the research workflow, not the web runtime')
        bars,now=fake_data(255)
        model,meta=train_xgb(bars,'XAUUSDT')
        self.assertIsNotNone(model)
        self.assertTrue(meta['trained'])
        self.assertFalse(meta['orders_enabled'])
        self.assertFalse(meta['consensus_vote'])
        self.assertLess(meta['portable_export_max_margin_diff'],1e-3)
        self.assertTrue(0<predict_probability(model,[0.2,1,0.2,.2,.1,.1,0,.5])<1)

    def test_missing_xgboost_is_reported_without_crashing(self):
        bars,now=fake_data(255)
        from unittest.mock import patch
        import builtins
        original_import=builtins.__import__
        def import_without_xgboost(name,*args,**kwargs):
            if name=='xgboost':raise ModuleNotFoundError("No module named 'xgboost'")
            return original_import(name,*args,**kwargs)
        with patch('builtins.__import__',side_effect=import_without_xgboost):
            model,meta=train_xgb(bars,'XAUUSDT')
        self.assertIsNone(model)
        self.assertEqual(meta['status'],'DEPENDENCY_UNAVAILABLE')
        self.assertIn('GitHub Actions',meta['reasons'][0])

    def test_no_upstream_model_or_bogus_prediction(self):
        bars,now=fake_data(70)
        model,meta=train_xgb(bars,'XAUUSDT')
        self.assertIsNone(model)
        self.assertFalse(meta['approved'])
        with tempfile.TemporaryDirectory() as d:
            s=live_status(bars,'XAUUSDT',model_root=d,now_s=now)
            self.assertIsNone(s['prediction'])
            self.assertFalse(s['orders_enabled'])

    def test_source_mismatch(self):
        with tempfile.TemporaryDirectory() as d:
            folder=Path(d)/'models';folder.mkdir()
            path=folder/'dukascopy_xauusd_session_xgb.json'
            path.write_text(json.dumps({'symbol':'XAUUSD','source':'dukascopy_xauusd_bid_h1',
                      'features':['asia_return','asia_range','asia_body','asia_volatility','asia_first_half','asia_last_half','asia_wick_balance','day_of_week'],
                      'approved':True,'trained_at_utc':datetime.now(UTC).isoformat(),'intercept':0,'trees':[]}))
            s=live_status([],'XAUUSD',model_root=d)
            self.assertEqual(s['status'],'SOURCE_MISMATCH')
            self.assertIsNone(s['prediction'])

if __name__=='__main__':unittest.main()
