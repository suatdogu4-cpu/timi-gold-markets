"""Independent, no-lookahead shadow backtest for GOLD SCALP PRO.

Does not modify legacy /api/backtest or its eight definitions.
Keeps thresholds fixed (no tuning to the sample), assumes closed candles,
next-bar opens, conservative gaps and stop-first intrabar handling.
"""
from __future__ import annotations
import math
import statistics
from quant import indicators, _signal_for, STRATEGIES, safe, TF_MIN

VERSION = '2.1.0'


def _metrics(trades, initial=10000.0):
    wins=[t for t in trades if t['pnl_ref'] > 0]
    losses=[t for t in trades if t['pnl_ref'] < 0]
    profit=sum(t['pnl_ref'] for t in wins)
    loss=-sum(t['pnl_ref'] for t in losses)
    eq=initial;peak=initial;maxdd=0;curve=[{'t':trades[0]['t'] if trades else 0, 'equity':initial}]
    for t in trades:
        eq+=t['pnl_ref'];peak=max(peak,eq);maxdd=min(maxdd,100*(eq/peak-1))
        curve.append({'t':t['exit_t'],'equity':round(eq,2)})
    return {'trades_count':len(trades),'wins':len(wins),'win_rate_pct':safe(100*len(wins)/len(trades),2) if trades else None,
            'profit_factor':safe(profit/loss,3) if loss else None,
            'net_pnl_ref':safe(eq-initial,3),'avg_pnl_ref':safe((eq-initial)/len(trades),4) if trades else None,
            'max_drawdown_pct':safe(maxdd,3),'equity_curve':curve[-250:],
            'statistically_sufficient':len(trades)>=30}


def _regime_gate(strategy, side, i, bars, raw, atr_pct_rank):
    e20=raw['ema20'][i];e50=raw['ema50'][i];e200=raw['ema200'][i]
    adx=raw['adx14'][i];atr=raw['atr14'][i]
    if any(x is None for x in (e20,e50,e200,adx,atr)) or atr<=0:return False,'Gösterge ısınması'
    close=bars[i]['c']
    if atr_pct_rank>=95:return False,'Oynaklık şoku (%95+ ATR)'
    # Trend-following is not enabled in ranging or contradictory HTF proxies.
    trend_families={'ema_trend','donchian','bb_break','momentum','macd_cross'}
    revert_families={'rsi_revert','vwap_revert','smc_sweep'}
    if strategy in trend_families:
        if adx<19:return False,'Trend gücü yetersiz (ADX)'
        if side*(close-e200)<=0 or side*(e20-e50)<=0:return False,'EMA200 / EMA20-50 yön çatışması'
    if strategy in revert_families:
        if adx>24:return False,'Güçlü trendde dönüş işlemi engellendi'
        if strategy=='smc_sweep' and atr_pct_rank<15:return False,'Aşırı düşük volatilitede sweep teyitsiz'
    return True,'Koşullar uygun'


def _atr_rank(raw, bars, i):
    atrs=raw['atr14']
    if atrs[i] is None or bars[i]['c']<=0:return 100
    hist=[100*a/bars[j]['c'] for j,a in enumerate(atrs[max(0,i-80):i],start=max(0,i-80))
          if a is not None and bars[j]['c']>0]
    if len(hist)<30:return 100
    v=100*atrs[i]/bars[i]['c']
    return 100*sum(x<=v for x in hist)/len(hist)


def improved_backtest(bars, strategy, fee_bps=4.,slippage_bps=1.,spread_bps=0., max_hold=12):
    if strategy not in STRATEGIES:raise ValueError('Bilinmeyen strateji')
    if any(not math.isfinite(x) or x<0 or x>100 for x in (fee_bps,slippage_bps,spread_bps)):
        raise ValueError('Maliyetler 0..100 bps olmalı')
    if len(bars)<300:return {'error':'En az 300 kapanmış mum gerekli (EMA200 + test örneklemi).','ready':False}
    ix=indicators(bars);raw=ix['_raw'];trades=[];rejected={}
    split=int(len(bars)*.70)
    total_cost_bps=2*(fee_bps+slippage_bps)+spread_bps
    last_side=0;i=205
    while i<len(bars)-2:
        # The indicator can be a persistent *state*. Trade only a fresh direction change,
        # never open again on every bar while state is unchanged.
        side=_signal_for(strategy,i,bars,raw)
        fresh_edge=bool(side and side!=last_side)
        last_side=side
        if not fresh_edge:i+=1;continue
        atr=raw['atr14'][i]
        if atr is None or atr<=0:i+=1;continue
        atr_rank=_atr_rank(raw,bars,i)
        allowed,why=_regime_gate(strategy,side,i,bars,raw,atr_rank)
        entry_ref=bars[i+1]['o'];cost_move=entry_ref*total_cost_bps/10000
        # Avoid signals whose 2.25 ATR target is largely consumed by costs.
        if cost_move>=1.5*atr:allowed=False;why='İşlem maliyeti hedef hareketine göre yüksek'
        if not allowed:
            rejected[why]=rejected.get(why,0)+1;i+=1;continue
        # Next-bar open is the first known fill. Slippage and spread half on each leg.
        slip=(slippage_bps+spread_bps/2)/10000
        entry=entry_ref*(1+side*slip)
        stop=entry-side*1.5*atr;take=entry+side*2.25*atr
        end=min(i+1+max_hold,len(bars)-1)
        exit_price=bars[end]['c'];exit_i=end;exit_reason='TIME'
        for j in range(i+1,end+1):
            bar=bars[j];o=bar['o'];lo=bar['l'];hi=bar['h']
            if side==1:
                if o<=stop:exit_price=o;exit_reason='GAP_STOP'
                elif lo<=stop:exit_price=stop;exit_reason='STOP'
                elif o>=take:exit_price=take;exit_reason='TP_GAP_CAPPED'
                elif hi>=take:exit_price=take;exit_reason='TP'
                else:continue
            else:
                if o>=stop:exit_price=o;exit_reason='GAP_STOP'
                elif hi>=stop:exit_price=stop;exit_reason='STOP'
                elif o<=take:exit_price=take;exit_reason='TP_GAP_CAPPED'
                elif lo<=take:exit_price=take;exit_reason='TP'
                else:continue
            exit_i=j;break
        exit_fill=exit_price*(1-side*slip)
        pnl=side*(exit_fill-entry)-(abs(entry)+abs(exit_fill))*fee_bps/10000
        trades.append({'t':bars[i+1]['t'],'exit_t':bars[exit_i]['t'],'side':'LONG' if side==1 else 'SHORT',
                       'entry':safe(entry),'exit':safe(exit_fill),'pnl_ref':safe(pnl,5),
                       'reason':exit_reason,'signal_index':i,'phase':'forward' if i>=split else 'development'})
        i=exit_i+1
    development=[x for x in trades if x['phase']=='development']
    forward=[x for x in trades if x['phase']=='forward']
    return {'ready':True,'version':VERSION,'strategy':strategy,'label':STRATEGIES[strategy],
            'sample_candles':len(bars),'split_bar_index':split,'split_time':bars[split]['t'],
            'params':{'fee_bps_per_side':fee_bps,'slippage_bps_per_side':slippage_bps,'spread_bps_roundtrip':spread_bps,
                      'atr_stop':1.5,'atr_take':2.25,'max_hold_bars':max_hold,'cooldown':'one signal edge + until exit'},
            'development':_metrics(development),'forward':_metrics(forward),
            'all':_metrics(trades),'rejected':rejected,'trades':trades[-80:],
            'forward_status':('NO_TRADES' if not forward else 'INSUFFICIENT' if len(forward)<30 else 'MEASURABLE'),
            'note':'%70 erken dönem, %30 ileri dönem; veri üzerinde parametre optimizasyonu yapılmadı. '
                   'İleri örnek sonuçları çok az işlemde güvenilir değildir. Emir defteri geçmişi, funding, gerçek dolum ve sözleşme çarpanı bu testte yoktur. '
                   'Hiçbir sonuç gelecek kârlılığını garanti etmez.'}
