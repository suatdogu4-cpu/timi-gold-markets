"""Deterministic offline regression checks. No live exchange or real orders."""
import math
import unittest
from gold30_quant import normalize_bars, atr_at, horizon_stats, report

BASE = 1700000000 - (1700000000 % 86400)

def series(start, n, step, magnitude=1.5):
    data=[]
    for i in range(n):
        price=3600+8*math.sin(i/22)+0.022*i
        close=price+magnitude*math.sin(i/4.5)
        data.append({'t':start+i*step,'o':price,'h':max(price,close)+2.5,
                     'l':min(price,close)-2.5,'c':close,'v':i+1})
    return data

class QuantTests(unittest.TestCase):
    def test_validation(self):
        x=series(BASE,3,900)
        x.append({'t':x[-1]['t']+900,'o':2,'h':1,'l':3,'c':2,'v':1})
        x.append(x[0])
        self.assertEqual(len(normalize_bars(x)),3)
        self.assertEqual(atr_at(x[:2],1),None)

    def test_coverage_and_sources(self):
        now=BASE+31*86400+3600
        daily=series(BASE,31,86400)
        fifteen=series(now-3000*900,3000,900)
        five=series(now-700*300,700,300)
        d=report(daily,fifteen,five,3700,True,'XAUUSDT Bitget UTA v3',now)
        self.assertTrue(d['window']['full_30d'])
        self.assertEqual(d['symbol'],'XAUUSDT')
        self.assertFalse(d['orders_enabled'])
        self.assertEqual(len(d['horizons']),5)
        self.assertTrue(any(x['status']=='RESEARCH' for x in d['horizons']))
        self.assertTrue(all(x['p_up_first'] is None or 0<=x['p_up_first']<=100 for x in d['horizons']))
        self.assertTrue(all(x['p_down_first'] is None or 0<=x['p_down_first']<=100 for x in d['horizons']))
        self.assertTrue(all(x['p_timeout'] is None or 0<=x['p_timeout']<=100 for x in d['horizons']))

    def test_fail_closed_when_no_live_price(self):
        now=BASE+31*86400+3600
        d=report(series(BASE,31,86400),series(now-3000*900,3000,900),
                 series(now-700*300,700,300),3700,False,'XAUUSDT Bitget',now)
        self.assertEqual(d['decision'],'BEKLE')
        self.assertIsNone(d['price'])
        self.assertTrue(all(x.get('p_up_first') is None for x in d['horizons']))

    def test_gaps_excluded(self):
        bars=series(BASE,150,900)
        for x in bars[80:]:x['t']+=3600
        r=horizon_stats(bars,900,8,3500)
        self.assertLessEqual(r['sample_count'],r['historical_count'] if 'historical_count' in r else 150)

    def test_dual_touch_is_ambiguous(self):
        bars=series(BASE,160,900)
        bars[71]['h']=bars[70]['c']+100
        bars[71]['l']=bars[70]['c']-100
        r=horizon_stats(bars,900,1,3700,min_count=999)
        self.assertGreaterEqual(r['ambiguous_count'],1)

    def test_no_orders_in_source(self):
        from pathlib import Path
        source=Path(__import__('gold30_quant').__file__).read_text(encoding='utf-8')
        for term in ('place_order(', 'create_order(', 'send_order('):
            self.assertNotIn(term,source)

if __name__=='__main__':unittest.main()
