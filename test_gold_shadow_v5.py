"""Offline regression/safety tests for GOLD SHADOW V5. No network, no trading."""
import csv
import math
import tempfile
import unittest
from datetime import datetime, timezone, timedelta
from pathlib import Path

import gold_shadow_v5 as v5
UTC=timezone.utc

class StubModel:
    def fit(self, features, targets):
        if len(features)<v5.MIN_SESSIONS or len(set(targets))<2:
            raise ValueError('Unusable training data')
        return self
    def predict_proba(self, features):return [[0.38,0.62]]

class ShadowSafety(unittest.TestCase):
    def make_csv(self,folder):
        p=Path(folder)/'history.csv'
        # Deterministic synthetic hourly bars. Never used as market measurements.
        start=datetime(2026,3,1,0,tzinfo=UTC)
        end=datetime(2026,11,21,0,tzinfo=UTC)
        with p.open('w',encoding='utf-8',newline='') as f:
            writer=csv.DictWriter(f,fieldnames=['t','o','h','l','c','v']);writer.writeheader()
            k=0
            while start+timedelta(hours=k)<end:
                dt=start+timedelta(hours=k)
                price=2600+0.075*k+8*math.sin(k*.075)+3*math.sin(k*.015)
                close=price+4*math.sin(k*.18)
                writer.writerow({'t':int(dt.timestamp()),'o':price,'h':max(price,close)+1.4,
                  'l':min(price,close)-1.4,'c':close,'v':50+abs(10*math.cos(k*.03))})
                k+=1
        return p

    def test_safe_windows_and_delayed_run(self):
        self.assertTrue(v5.can_forecast(datetime(2026,11,20,8,11,tzinfo=UTC)))
        self.assertFalse(v5.can_forecast(datetime(2026,11,20,9,7,tzinfo=UTC)))
        self.assertFalse(v5.can_forecast(datetime(2026,11,21,8,11,tzinfo=UTC)))
        self.assertFalse(v5.can_settle(datetime(2026,11,20,16,59,tzinfo=UTC)))
        self.assertTrue(v5.can_settle(datetime(2026,11,20,17,19,tzinfo=UTC)))
        with tempfile.TemporaryDirectory() as d:
            p=self.make_csv(d)
            f=v5.forecast(datetime(2026,11,20,9,12,tzinfo=UTC),csvpath=p,journal=Path(d)/'j.jsonl',model_factory=StubModel)
            self.assertEqual(f['status'],'OUTSIDE_PROSPECTIVE_WINDOW')
            self.assertFalse((Path(d)/'j.jsonl').exists())

    def test_cloud_forecast_idempotent_settlement_and_chained_audit(self):
        with tempfile.TemporaryDirectory() as d:
            p=self.make_csv(d);journal=Path(d)/'j.jsonl';status=Path(d)/'status.json'
            when=datetime(2026,11,20,8,16,tzinfo=UTC)
            first=v5.forecast(when,csvpath=p,journal=journal,model_factory=StubModel)
            self.assertEqual(first['status'],'PROSPECTIVE_FORECAST_LOGGED')
            self.assertEqual(first['direction'],'LONG')
            self.assertEqual(len(v5.read_events(journal)),1)
            self.assertEqual(v5.forecast(when,csvpath=p,journal=journal,model_factory=StubModel)['status'],'ALREADY_RECORDED')
            early=v5.settle(datetime(2026,11,20,16,59,tzinfo=UTC),csvpath=p,journal=journal)
            self.assertEqual(early['status'],'OUTSIDE_SETTLEMENT_WINDOW')
            late=v5.settle(datetime(2026,11,20,17,19,tzinfo=UTC),csvpath=p,journal=journal)
            self.assertEqual(late['status'],'SETTLED_PROSPECTIVE_FORECAST')
            self.assertEqual(v5.settle(datetime(2026,11,20,17,30,tzinfo=UTC),csvpath=p,journal=journal)['status'],'ALREADY_SETTLED_OR_MISSED')
            self.assertEqual(len(v5.read_events(journal)),2)
            s=v5.summary(journal,status)
            self.assertEqual(s['forecasts_recorded'],1)
            self.assertEqual(s['sessions_settled'],1)
            self.assertEqual(s['directional_settled'],1)
            self.assertFalse(s['future_validation_ready'])
            self.assertFalse(s['live_trade_signal'])
            self.assertEqual(v5.public_status('XAUUSDT',Path(d))['status'],'NO_SHADOW_RECORD')
            contents=journal.read_text(encoding='utf-8')
            journal.write_text(contents.replace('"direction":"LONG"','"direction":"SHORT"',1),encoding='utf-8')
            with self.assertRaisesRegex(ValueError,'TAMPERED_JOURNAL'):v5.read_events(journal)

    def test_missing_forecast_not_backfilled(self):
        with tempfile.TemporaryDirectory() as d:
            p=self.make_csv(d);j=Path(d)/'j.jsonl';day=datetime(2026,11,20,17,20,tzinfo=UTC)
            r=v5.settle(day,csvpath=p,journal=j)
            self.assertEqual(r['status'],'MISSED_DAY_MARKED')
            self.assertEqual(v5.read_events(j)[0]['event'],'MISSED')
            self.assertEqual(v5.forecast(datetime(2026,11,20,8,24,tzinfo=UTC),csvpath=p,journal=j,model_factory=StubModel)['status'],'DAY_ALREADY_MISSED')

    def test_missing_last_hour_rejects_signal(self):
        with tempfile.TemporaryDirectory() as d:
            p=self.make_csv(d);journal=Path(d)/'j.jsonl';raw=p.read_text(encoding='utf-8').splitlines()
            forbidden=str(int(datetime(2026,11,20,7,tzinfo=UTC).timestamp()))
            p.write_text('\n'.join(x for x in raw if not x.startswith(forbidden+','))+'\n',encoding='utf-8')
            r=v5.forecast(datetime(2026,11,20,8,20,tzinfo=UTC),csvpath=p,journal=journal,model_factory=StubModel)
            self.assertEqual(r['status'],'MISSING_CLOSED_ASIA_BARS')
            self.assertFalse(journal.exists())


    def test_late_outcome_recovery_only_for_pre_recorded_forecast(self):
        with tempfile.TemporaryDirectory() as d:
            p=self.make_csv(d);j=Path(d)/'j.jsonl'
            day=datetime(2026,11,20,8,20,tzinfo=UTC)
            self.assertEqual(v5.forecast(day,csvpath=p,journal=j,model_factory=StubModel)['status'],'PROSPECTIVE_FORECAST_LOGGED')
            # On next business day, valid to settle the existing prediction;
            # not valid to manufacture a past prediction.
            monday=datetime(2026,11,23,8,25,tzinfo=UTC)
            r=v5.settle(monday,csvpath=p,journal=j,day='2026-11-20')
            self.assertEqual(r['status'],'SETTLED_PROSPECTIVE_FORECAST')
            self.assertEqual(v5.read_events(j)[0]['event'],'FORECAST')
            self.assertEqual(v5.read_events(j)[1]['forecast_hash'],v5.read_events(j)[0]['hash'])

    def test_render_reader_recomputes_expired_today_flag(self):
        with tempfile.TemporaryDirectory() as d:
            p=Path(d)/'models'/'gold_shadow_v5_status.json';p.parent.mkdir(parents=True)
            import json
            old={'version':v5.VERSION,'source':v5.SOURCE_ID,'status':'SHADOW_RESEARCH_ONLY',
               'latest_forecast':{'day':'2026-11-19','direction':'LONG'},
               'latest_forecast_is_today':True,'orders_enabled':True}
            p.write_text(json.dumps(old),encoding='utf-8')
            loaded=v5.public_status('XAUUSDT',Path(d))
            self.assertFalse(loaded['latest_forecast_is_today'])
            self.assertFalse(loaded['orders_enabled'])
            self.assertFalse(loaded['live_trade_signal'])

if __name__=='__main__':unittest.main()
