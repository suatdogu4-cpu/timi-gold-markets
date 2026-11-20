"""Offline unit tests for v3 research. No broker access, no synthetic performance claims."""
import csv
from datetime import datetime,timezone,timedelta
import gzip
import tempfile
from pathlib import Path
from unittest import TestCase,main
from unittest.mock import patch
import gold_ml_v3 as ml
from tools import gold_ml_v3_pipeline as pipe


def fixture_hours(days=135):
    # Synthetic data is ONLY for software tests, never deployed as market training data.
    start=int(datetime(2026,1,1,tzinfo=timezone.utc).timestamp())
    rows=[]
    for i in range(days*24):
        t=start+i*3600
        p=2600+i*.07+(i%17-8)*.12
        rows.append({'t':t,'o':p,'h':p+1.3,'l':p-1.2,'c':p+.17,'v':100+i%9})
    return rows

class GoldMLV3Tests(TestCase):
    def test_source_isolation_schema(self):
        self.assertEqual(ml.SOURCES['binance_xauusdt']['symbol'],'XAUUSDT')
        self.assertNotEqual(ml.SOURCES['binance_xauusdt']['source_id'],ml.SOURCES['bitget_xauusdt']['source_id'])
        self.assertEqual(len(ml.COLUMNS),26)

    def test_no_future_or_unclosed_in_features(self):
        bars=fixture_hours();now=bars[-1]['t']+3600
        a=ml.sessions(bars,now_s=now)
        self.assertGreater(len(a['samples']),60)
        target=a['samples'][-10]
        # Change all London candles of this target session. Its 08 UTC features cannot change.
        contaminated=[dict(x) for x in bars]
        for x in contaminated:
            if target['cutoff']<=x['t']<target['cutoff']+9*3600:
                x['o']+=60;x['c']+=60;x['h']+=60;x['l']+=60
        b=ml.sessions(contaminated,now_s=now)
        aa=next(z for z in a['samples'] if z['day']==target['day'])
        bb=next(z for z in b['samples'] if z['day']==target['day'])
        self.assertEqual(aa['x'],bb['x'])
        self.assertTrue(all(isinstance(x,(float,int)) for x in aa['x']))
        self.assertEqual(len(aa['x']),26)

    def test_archive_restores_source_separated_history(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);dataset=root/'datasets/gold_ml';dataset.mkdir(parents=True)
            data=root/'data';data.mkdir()
            orig_data,orig_archive=pipe.DATA,pipe.ARCHIVE
            try:
                pipe.DATA={k:data/(k+'_h1.csv') for k in pipe.DATA}
                pipe.ARCHIVE=dataset
                pipe.save_csv(pipe.DATA['bitget_xauusdt'],fixture_hours(10))
                pipe.archive_data()
                self.assertTrue((dataset/'bitget_xauusdt_h1.csv.gz').is_file())
                (data/'bitget_xauusdt_h1.csv').unlink()
                pipe.restore_archives()
                self.assertEqual(len(pipe.csv_rows(pipe.DATA['bitget_xauusdt'])),240)
                self.assertFalse(pipe.DATA['binance_xauusdt'].exists())
            finally:
                pipe.DATA,pipe.ARCHIVE=orig_data,orig_archive

    def test_binance_history_mock_rejects_unclosed_and_leaks(self):
        with tempfile.TemporaryDirectory() as d:
            p=Path(d)/'binance.csv'
            orig=pipe.DATA
            try:
                pipe.DATA={**orig,'binance_xauusdt':p}
                t=int(datetime(2026,2,1,tzinfo=timezone.utc).timestamp())
                # One closed candle, one open candle. Never include the open candle.
                data=[[str((t+i*3600)*1000),'2900','2910','2890','2901','22',str((t+(i+1)*3600-1)*1000)] for i in range(2)]
                now=t+3600+100
                with patch.object(pipe,'_get_json',side_effect=[data,[]]),patch.object(pipe.time,'time',return_value=now),patch.object(pipe.time,'sleep'):
                    res=pipe.collect_binance(3)
                self.assertEqual(res['h1_saved'],1)
            finally:pipe.DATA=orig

    def test_indicators_constant_and_rising_series(self):
        closes=[100+i*.2 for i in range(160)]
        self.assertTrue(99.9<ml.rsi(closes)<=100)
        self.assertGreater(ml.ema(closes,20),ml.ema(closes,50))
        self.assertTrue(abs(ml.macd_histogram(closes))<.1)
        rows=[{'t':3600*(i+1),'o':100+i*.2,'h':101+i*.2,
               'l':99+i*.2,'c':100.2+i*.2,'v':10} for i in range(160)]
        self.assertGreater(ml.atr(rows),0)

    def test_render_status_is_read_only_and_no_report(self):
        with tempfile.TemporaryDirectory() as d:
            state=ml.report_for_symbol('XAUUSDT',d)
            self.assertFalse(state['orders_enabled'])
            self.assertFalse(state['consensus_vote'])
            self.assertIsNone(state['prediction'])

if __name__=='__main__':main()
