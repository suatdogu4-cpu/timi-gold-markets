"""Offline V6 anti-leakage / source integrity tests; never uses exchange network."""
import unittest, math, json, io, hashlib, zipfile
from datetime import datetime, timezone
import numpy as np
import pandas as pd
import gold_scalp_v6_data as data
import gold_scalp_v6_research as research
from gold_scalp_v6_view import read_research

class TestGoldV6(unittest.TestCase):
    @staticmethod
    def candles(n=1900,tf=1):
        start=1790000000//(60*tf*5)*(60*tf*5)
        rows=[]
        for i in range(n):
            value=4000+20*math.sin(i/40)+.02*i
            rows.append({'t':start+i*tf*60,'o':value,'h':value+2,
                         'l':value-2,'c':value+.4*math.sin(i/7),'v':100+i%35})
        return rows
    def test_partial_bar_rejected(self):
        t=1790000000//60*60
        b=dict(t=t,o=2,h=3,l=1,c=2,v=10)
        self.assertIsNone(data.checked(b,t+45))
        self.assertIsNotNone(data.checked(b,t+60))
        self.assertIsNone(data.checked(dict(b,t=t+8),t+60))
    def test_source_identity_fixed(self):
        self.assertNotEqual(data.SOURCES['bitget'],data.SOURCES['binance'])
        self.assertEqual(research.TIMES,(1,3,5,15))
    def test_resample_missing_minute_skipped(self):
        rows=self.candles(15)
        a=research.df_from_history({r['t']:r for r in rows})
        self.assertEqual(len(research.resample_closed_1m(a,5)),3)
        a=a.drop(7).reset_index(drop=True)
        self.assertEqual(len(research.resample_closed_1m(a,5)),2)
    def test_indicator_columns_on_past_only(self):
        df=research.df_from_history({x['t']:x for x in self.candles(700)})
        x=research.features(df)
        mutated=df.copy();mutated.loc[mutated.index[-1],'c']*=1.001
        y=research.features(mutated)
        for name in ('ema20','rsi','macdh','atr','volratio'):
            self.assertAlmostEqual(float(x[name].iloc[-2]),float(y[name].iloc[-2]),places=8)
    def test_next_bar_entry_cost_and_stop(self):
        raw=self.candles(260)
        df=research.features(research.df_from_history({x['t']:x for x in raw}))
        cfg={'family':'trend','vol_min':1,'session':'all','sensitivity':0,
             'hold_bars':4,'atr_stop':1.3,'atr_take':2,'tf_seconds':60}
        sig=np.zeros(len(df),dtype='int8');sig[240]=1
        out=research.backtest(df,sig,235,255,cfg)
        self.assertEqual(out['trades'],1)
        self.assertLess(out['expectancy_bps'],200)
    def test_no_trades_during_gap(self):
        raw=self.candles(280)
        del raw[241]
        df=research.features(research.df_from_history({x['t']:x for x in raw}))
        cfg={'family':'trend','vol_min':1,'session':'all','sensitivity':0,
             'hold_bars':4,'atr_stop':1.3,'atr_take':2,'tf_seconds':60}
        sig=np.zeros(len(df),dtype='int8');sig[240]=1
        result=research.backtest(df,sig,240,260,cfg)
        self.assertEqual(result['trades'],0)
    def test_final_test_after_validation(self):
        plan,k=research.validation_plan(2000)
        self.assertTrue(all(e<=k for _,e in plan))
        self.assertGreater(k,1600)
    def test_zip_sha256_guard(self):
        name='XAUUSDT-1m-2026-10.zip';buf=io.BytesIO()
        with zipfile.ZipFile(buf,'w') as z:
            z.writestr(name.replace('.zip','.csv'), 'open_time,open,high,low,close,volume\n1789999980000,4000,4010,3990,4001,100\n')
        self.assertEqual(len(research.TIMES),4)
        self.assertEqual(len(hashlib.sha256(buf.getvalue()).hexdigest()),64)
        self.assertEqual(len(data.parse_binance_zip(buf.getvalue(),name,1800000000)),1)
    def test_never_exposes_trade_signal(self):
        self.assertEqual(read_research('/nonesuch')['trade_decision'],'BEKLE')
        self.assertEqual(read_research('/nonesuch')['live_signal'],False)
        self.assertEqual(read_research('/nonesuch', 'XAUUSD')['status'],'SYMBOL_NOT_SUPPORTED')
    def test_strategy_on_synthetic(self):
        df=research.df_from_history({x['t']:x for x in self.candles(1800)})
        a=research.features(df)
        report=research.optimize_strategies(a,'bitget',1)
        self.assertEqual(report['tested_configurations'],len(research.configs()))
        self.assertFalse(report['live_signal'])

if __name__=='__main__':unittest.main()
