"""ALTIN QUANT's six explicit research strategy families.

Only checks prerequisites for candidate monitoring, never creates an executable
trading instruction. The eight legacy backtests remain untouched.
"""
from __future__ import annotations
from quant import indicators, smc

NAMES={
 'S1':'Trend pullback / EMA-VWAP',
 'S2':'Breakout + retest',
 'S3':'Sweep + reclaim',
 'S4':'VWAP / Bollinger mean reversion',
 'S5':'Squeeze expansion',
 'S6':'Order flow absorption',
}


def evaluate_strategies(bars, regime, mtf, flow):
    rows=[]
    if len(bars)<210:
        return [{'id':k,'name':v,'status':'VERİ YOK', 'reason':'210 kapanmış 5m mum eksik'} for k,v in NAMES.items()]
    i=indicators(bars)['latest'];ev=smc(bars).get('events',[])
    p=i['close']; atr=i.get('atr14') or 0
    context=mtf.get('context'); reg=regime.get('code')
    f60=(flow.get('windows') or {}).get('60',{}).get('aggressor')
    trend=context in ('LONG','SHORT') and reg in ('UP','DOWN')
    flow_same=(f60 is not None and ((context=='LONG' and f60>.10) or (context=='SHORT' and f60<-.10)))
    def add(code, ok, notes, requirements=True):
        rows.append({'id':code,'name':NAMES[code],
                     'status':('İZLE' if ok else 'VERİ YOK' if not requirements else 'KOŞUL YOK'),
                     'reason':notes,'orders_enabled':False})
    near_avg = atr>0 and i.get('ema20') and abs(p-i['ema20'])<=.75*atr
    add('S1',bool(trend and near_avg and flow_same),
        'Trend + EMA20 yakınlığı + aynı yön 60sn agresör gereklidir',
        f60 is not None)
    # S2 requires a break, THEN a retest and confirmation; a single historical
    # 5m bar cannot prove a pending retest. Only tag possible monitoring state.
    max20=max(x['h'] for x in bars[-21:-1]);min20=min(x['l'] for x in bars[-21:-1])
    range_break=(p>max20 or p<min20) and atr>0
    add('S2',False,'Kırılım '+('görüldü; geri test ve tekrar teyit gerekli' if range_break else 'yok')+'; henüz işlem adayı değil')
    sweeps=[x for x in ev if x.get('t',0)>=bars[-2]['t'] and x.get('type') in ('SWEEP_LOW','SWEEP_HIGH')]
    add('S3',False,'Yakın sweep '+('adayı var; yapı dönüşü henüz doğrulanmadı' if sweeps else 'yok')+'; geri alma teyidi gerekli')
    z=i.get('zscore20');range_ok=reg=='RANGE'
    add('S4',bool(range_ok and z is not None and abs(z)>=1.7),
        'Yatay rejim ve |Z20| >=1.7; ters fiyat kapanışı ayrıca gerekli',
        z is not None)
    squeezed=reg=='SQUEEZE'
    add('S5',False,'Sıkışma '+('var; hacimli yönlü kırılım bekleniyor' if squeezed else 'tespit edilmedi'))
    add('S6',False,'Emilim için ardışık emir defteri ve tick bazlı fiyat etkisi geçmişi gerekiyor',False)
    return rows
