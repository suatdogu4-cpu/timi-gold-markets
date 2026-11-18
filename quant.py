"""GOLD SCALP PRO — deterministic closed-candle technical/quant research engine.

No external orders, no promised probability or investment recommendation.
Open-source strategies are independently implemented; third-party projects are referenced,
not copied or bundled.
"""
from __future__ import annotations
import math
import statistics
from collections import defaultdict
from typing import Any

TF_MIN = {"1m":1,"3m":3,"5m":5,"15m":15,"30m":30,"1H":60,"4H":240,"1D":1440}
STRATEGIES = {
    "ema_trend":"EMA 20/50 trend + RSI",
    "rsi_revert":"RSI aşırı bölge dönüşü",
    "donchian":"20 mum Donchian kırılımı",
    "vwap_revert":"VWAP ortalamaya dönüş",
    "smc_sweep":"Önceki 12 mum likidite süpürmesi",
    "bb_break":"Bollinger bant kırılımı",
    "momentum":"5 mum momentum + trend",
    "macd_cross":"MACD histogram sıfır kesişimi",
}

def num(x, default=0.0):
    try:
        n=float(x)
        return n if math.isfinite(n) else default
    except (TypeError, ValueError, OverflowError):
        return default

def safe(x, digits=5):
    return round(x, digits) if x is not None and math.isfinite(x) else None

def sma(xs,n):
    out=[None]*len(xs)
    if n<=0: return out
    total=0.0
    for i,x in enumerate(xs):
        total+=x
        if i>=n:total-=xs[i-n]
        if i>=n-1:out[i]=total/n
    return out

def ema(xs,n):
    out=[None]*len(xs)
    if n<1 or len(xs)<n:return out
    prev=sum(xs[:n])/n
    out[n-1]=prev
    k=2/(n+1)
    for i in range(n,len(xs)):
        prev=(xs[i]-prev)*k+prev
        out[i]=prev
    return out

def ema_optional(xs,n):
    out=[None]*len(xs)
    indices=[i for i,v in enumerate(xs) if v is not None]
    vals=[xs[i] for i in indices]
    e=ema(vals,n)
    for i,v in zip(indices,e):out[i]=v
    return out

def rsi(xs,n=14):
    out=[None]*len(xs)
    if len(xs)<n+1:return out
    dif=[xs[i]-xs[i-1] for i in range(1,len(xs))]
    gain=sum(max(d,0) for d in dif[:n])/n
    loss=sum(max(-d,0) for d in dif[:n])/n
    def value(g,l):return 100 if l==0 and g>0 else 50 if l==0 and g==0 else 100-100/(1+g/l)
    out[n]=value(gain,loss)
    for i in range(n+1,len(xs)):
        d=dif[i-1]
        gain=(gain*(n-1)+max(0,d))/n
        loss=(loss*(n-1)+max(0,-d))/n
        out[i]=value(gain,loss)
    return out

def true_ranges(high,low,close):
    return [max(high[i]-low[i], abs(high[i]-close[i-1]),abs(low[i]-close[i-1])) if i else high[i]-low[i] for i in range(len(close))]

def wilder(xs,n):
    out=[None]*len(xs)
    if len(xs)<n:return out
    prev=sum(xs[:n])/n
    out[n-1]=prev
    for i in range(n,len(xs)):
        prev=(prev*(n-1)+xs[i])/n
        out[i]=prev
    return out

def indicators(bars):
    n=len(bars)
    if not n:return {"latest":{},"series":{},"count":0}
    c=[num(x['c']) for x in bars]; h=[num(x['h']) for x in bars]
    l=[num(x['l']) for x in bars]; o=[num(x['o']) for x in bars]
    v=[max(0,num(x.get('v'))) for x in bars]
    tr=true_ranges(h,l,c)
    atr14=wilder(tr,14)
    ema9=ema(c,9);e20=ema(c,20);e50=ema(c,50);e200=ema(c,200)
    r14=rsi(c);r7=rsi(c,7)
    e12=ema(c,12);e26=ema(c,26)
    mac=[(a-b if a is not None and b is not None else None) for a,b in zip(e12,e26)]
    sig=ema_optional(mac,9)
    hist=[(a-b if a is not None and b is not None else None) for a,b in zip(mac,sig)]
    mid=sma(c,20)
    upper=[None]*n;lower=[None]*n;bandwidth=[None]*n
    for i in range(19,n):
        sd=statistics.pstdev(c[i-19:i+1]);upper[i]=mid[i]+2*sd;lower[i]=mid[i]-2*sd
        bandwidth[i]=100*4*sd/mid[i] if mid[i] else None
    k=[None]*n;d=[None]*n
    for i in range(13,n):
        hi=max(h[i-13:i+1]);lo=min(l[i-13:i+1]);k[i]=100*(c[i]-lo)/(hi-lo) if hi!=lo else 50
    d=sma_optional(k,3)
    plus_dm=[0.0]*n;minus_dm=[0.0]*n
    for i in range(1,n):
        up=h[i]-h[i-1];dn=l[i-1]-l[i]
        plus_dm[i]=up if up>dn and up>0 else 0
        minus_dm[i]=dn if dn>up and dn>0 else 0
    atr_adx=wilder(tr,14);pdm=wilder(plus_dm,14);mdm=wilder(minus_dm,14)
    pdi=[100*x/a if a and x is not None else None for x,a in zip(pdm,atr_adx)]
    mdi=[100*x/a if a and x is not None else None for x,a in zip(mdm,atr_adx)]
    dx=[100*abs(p-m)/(p+m) if p is not None and m is not None and p+m else None for p,m in zip(pdi,mdi)]
    adx=ema_optional(dx,14)
    tp=[(x+y+z)/3 for x,y,z in zip(h,l,c)]
    cci=[None]*n
    tpma=sma(tp,20)
    for i in range(19,n):
        dev=sum(abs(x-tpma[i]) for x in tp[i-19:i+1])/20
        cci[i]=(tp[i]-tpma[i])/(.015*dev) if dev else 0
    roc=[100*(c[i]/c[i-12]-1) if i>=12 and c[i-12] else None for i in range(n)]
    will=[None]*n
    don_hi=[None]*n;don_lo=[None]*n
    for i in range(19,n):
        hi=max(h[i-13:i+1]);lo=min(l[i-13:i+1]);will[i]=-100*(hi-c[i])/(hi-lo) if hi!=lo else -50
        don_hi[i]=max(h[i-19:i+1]);don_lo[i]=min(l[i-19:i+1])
    obv=[0.0]*n
    for i in range(1,n):obv[i]=obv[i-1]+(v[i] if c[i]>c[i-1] else -v[i] if c[i]<c[i-1] else 0)
    cmf=[None]*n
    for i in range(19,n):
        weighted=sum(((2*c[j]-h[j]-l[j])/(h[j]-l[j]) if h[j]!=l[j] else 0)*v[j] for j in range(i-19,i+1))
        vol=sum(v[i-19:i+1]);cmf[i]=weighted/vol if vol else None
    mfi=[None]*n
    for i in range(14,n):
        pos=neg=0.0
        for j in range(i-13,i+1):
            if tp[j]>tp[j-1]:pos+=tp[j]*v[j]
            elif tp[j]<tp[j-1]:neg+=tp[j]*v[j]
        mfi[i]=100*pos/(pos+neg) if pos+neg else 50
    vwap=[None]*n
    # Rolling 50-bar VWAP approximation, not exchange session VWAP
    for i in range(n):
        st=max(0,i-49);tv=sum(v[st:i+1]);vwap[i]=sum(tp[j]*v[j] for j in range(st,i+1))/tv if tv else None
    st=[None]*n;st_dir=[0]*n
    # Standard ATR supertrend state machine; breakpoints only on closed bars
    for i in range(1,n):
        if atr14[i] is None:continue
        center=(h[i]+l[i])/2;up=center+3*atr14[i];dn=center-3*atr14[i]
        if st[i-1] is None:
            st_dir[i]=1 if c[i]>c[i-1] else -1;st[i]=dn if st_dir[i]==1 else up
        elif st_dir[i-1]==1:
            st_dir[i]=-1 if c[i]<st[i-1] else 1
            st[i]=up if st_dir[i]==-1 else max(dn,st[i-1])
        else:
            st_dir[i]=1 if c[i]>st[i-1] else -1
            st[i]=dn if st_dir[i]==1 else min(up,st[i-1])
    logret=[math.log(c[i]/c[i-1]) for i in range(1,n) if c[i]>0 and c[i-1]>0]
    rv=statistics.pstdev(logret[-30:])*math.sqrt(365*24*60) * 100 if len(logret)>=10 else None
    mean20=mid[-1]
    zscore=(c[-1]-mean20)/statistics.pstdev(c[-20:]) if len(c)>=20 and statistics.pstdev(c[-20:]) else None
    last=lambda arr: safe(arr[-1]) if arr else None
    rel={
        "close":last(c),"ema9":last(ema9),"ema20":last(e20),"ema50":last(e50),"ema200":last(e200),
        "rsi14":last(r14),"rsi7":last(r7),"atr14":last(atr14),"macd":last(mac),"macd_signal":last(sig),"macd_hist":last(hist),
        "bb_mid":last(mid),"bb_up":last(upper),"bb_low":last(lower),"bb_width_pct":last(bandwidth),
        "stoch_k":last(k),"stoch_d":last(d),"adx14":last(adx),"plus_di":last(pdi),"minus_di":last(mdi),
        "cci20":last(cci),"roc12":last(roc),"williams14":last(will),"obv":last(obv),"cmf20":last(cmf),"mfi14":last(mfi),
        "vwap50":last(vwap),"supertrend":last(st),"supertrend_dir":st_dir[-1],
        "donchian_high":last(don_hi),"donchian_low":last(don_lo),"realized_vol_ann_pct":safe(rv),"zscore20":safe(zscore),
        "atr_pct":safe(100*atr14[-1]/c[-1] if atr14[-1] and c[-1] else None),
        "volume_sma20":last(sma(v,20)),"last_volume":last(v),
    }
    ser={"ema20":e20,"ema50":e50,"ema200":e200,"rsi14":r14,"atr14":atr14,
         "macd":mac,"macd_signal":sig,"macd_hist":hist,"bb_up":upper,"bb_low":lower,
         "stoch_k":k,"stoch_d":d,"vwap50":vwap,"supertrend":st,"adx14":adx}
    return {"latest":rel,"series":{k:[{"t":bars[i]['t'],"v":safe(x)} for i,x in enumerate(a) if x is not None][-500:] for k,a in ser.items()},"count":n,
            "_raw":ser}

def sma_optional(xs,n):
    out=[None]*len(xs)
    for i in range(n-1,len(xs)):
        vals=xs[i-n+1:i+1]
        if all(v is not None for v in vals):out[i]=sum(vals)/n
    return out

def smc(bars):
    if len(bars)<24:return {"status":"insufficient","events":[],"swing_high":None,"swing_low":None}
    h=[num(x['h']) for x in bars];l=[num(x['l']) for x in bars];c=[num(x['c']) for x in bars]
    highs=[];lows=[]
    for i in range(2,len(bars)-2):
        if h[i]>max(h[i-2:i]+h[i+1:i+3]):highs.append((i,h[i]))
        if l[i]<min(l[i-2:i]+l[i+1:i+3]):lows.append((i,l[i]))
    hi=highs[-1][1] if highs else None;lo=lows[-1][1] if lows else None
    ev=[]
    if hi and c[-1]>hi and c[-2]<=hi:ev.append({"type":"BOS_UP","price":safe(hi),"t":bars[-1]['t']})
    if lo and c[-1]<lo and c[-2]>=lo:ev.append({"type":"BOS_DOWN","price":safe(lo),"t":bars[-1]['t']})
    # Strict confirmed 3-candle price imbalance. Not all gaps imply actionable FVGs.
    for i in range(max(2,len(bars)-15),len(bars)):
        if l[i]>h[i-2]:ev.append({"type":"FVG_BULL","low":safe(h[i-2]),"high":safe(l[i]),"t":bars[i]['t']})
        if h[i]<l[i-2]:ev.append({"type":"FVG_BEAR","low":safe(h[i]),"high":safe(l[i-2]),"t":bars[i]['t']})
    if len(bars)>15:
        priorhi=max(h[-13:-1]);priorlo=min(l[-13:-1])
        if h[-1]>priorhi and c[-1]<priorhi:ev.append({"type":"SWEEP_HIGH","price":safe(priorhi),"t":bars[-1]['t']})
        if l[-1]<priorlo and c[-1]>priorlo:ev.append({"type":"SWEEP_LOW","price":safe(priorlo),"t":bars[-1]['t']})
    return {"status":"ready","events":ev[-18:],"swing_high":safe(hi),"swing_low":safe(lo),
            "range_mid":safe((hi+lo)/2) if hi is not None and lo is not None else None,
            "note":"BOS/FVG/sweep adayları: iki sağ mumla teyit edilen swing; emir block/CHoCH garantisi değildir."}

def flow_metrics(bids,asks,trades,now_ms):
    b=sum(p*q for p,q in bids[:20]);a=sum(p*q for p,q in asks[:20]);total=b+a
    recent=[x for x in trades if now_ms-x['t']<=60000 and x['t']<=now_ms+5000]
    buy=sum(x['p']*x['v'] for x in recent if x['side']=='buy')
    sell=sum(x['p']*x['v'] for x in recent if x['side']=='sell')
    by_price=defaultdict(lambda: [0.0,0.0])
    for x in recent:
        # Each row only represents observed exchange trades in the last 60s.
        key=round(x['p']/.5)*.5
        by_price[key][0 if x['side']=='buy' else 1]+=x['v']
    footprint=sorted([{"price":price,"buy":safe(q[0],4),"sell":safe(q[1],4),"delta":safe(q[0]-q[1],4)} for price,q in by_price.items()],key=lambda x:x['price'], reverse=True)[:65]
    top=bids[0][0] if bids else None;ask=asks[0][0] if asks else None
    return {"bid_notional20":safe(b,2),"ask_notional20":safe(a,2),"imbalance":safe((b-a)/total if total else None,4),
            "buy_notional60":safe(buy,2),"sell_notional60":safe(sell,2),"delta60":safe(buy-sell,2),
            "aggressor_ratio":safe((buy-sell)/(buy+sell) if buy+sell else None,4),"trades60":len(recent),
            "spread_pct":safe(100*(ask-top)/ask if ask and top else None,5),
            "footprint":footprint,"cvd_note":"60 saniyelik gözlenen taker işlemlerinden delta; tam tarihsel CVD değildir."}

def score_signal(bars, ind, structure, flow, valid, instrument):
    x=ind.get('latest',{}); c=x.get('close')
    if len(bars)<210:return {"decision":"BEKLE","score":None,"long":None,"short":None,"confidence":None,"reasons":["210 adet kapanmış mum gerekli"],"veto":["Yetersiz geçmiş veri"],"stop":None,"take_profit":None}
    buy=sell=0.0;reasons=[];veto=[]
    def vote(pos,neg,amount,reason):
        nonlocal buy,sell
        if pos:buy+=amount;reasons.append("+ "+reason)
        elif neg:sell+=amount;reasons.append("− "+reason)
    vote(c>x['ema20']>x['ema50'],c<x['ema20']<x['ema50'],23,"EMA20/EMA50 trend")
    vote(x['rsi14']>55,x['rsi14']<45,12,"RSI momentum")
    vote(x['macd_hist']>0,x['macd_hist']<0,14,"MACD histogram")
    vote((x.get('adx14') or 0)>=20 and (x.get('plus_di') or 0)>(x.get('minus_di') or 0),(x.get('adx14') or 0)>=20 and (x.get('plus_di') or 0)<(x.get('minus_di') or 0),8,"ADX trend gücü")
    vote(x['supertrend_dir']>0,x['supertrend_dir']<0,9,"Supertrend")
    recent=structure.get('events',[])[-8:]
    vote(any(y['type'] in ('BOS_UP','SWEEP_LOW') for y in recent),any(y['type'] in ('BOS_DOWN','SWEEP_HIGH') for y in recent),12,"SMC yapı olayı")
    if instrument=='XAUUSDT':
        vote(flow.get('imbalance') is not None and flow['imbalance']>.12,flow.get('imbalance') is not None and flow['imbalance']<-.12,10,"Emir defteri dengesi")
        vote(flow.get('aggressor_ratio') is not None and flow['aggressor_ratio']>.1,flow.get('aggressor_ratio') is not None and flow['aggressor_ratio']<-.1,12,"60 sn agresif işlem yönü")
        if not valid.get('ticker'):veto.append("Canlı fiyat gecikmeli")
        if not valid.get('book'):veto.append("Emir defteri eksik/gecikmeli")
        if not valid.get('trades'):veto.append("İşlem akışı eksik/gecikmeli")
        if flow.get('spread_pct') is None or flow['spread_pct']>.2:veto.append("Spread ölçülemedi / geniş")
        if (flow.get('trades60') or 0)<5:veto.append("60 saniyede yeterli işlem yok")
    else:veto.append("Spot için doğrulanmış canlı akış / order flow yok; birleşik karar kapalı")
    if x['atr14'] is None or x['atr14']<=0:veto.append("ATR eksik")
    if valid.get('candles') is False:veto.append("Kapanmış mum verisi güncel değil")
    decided="LONG" if buy>=55 and buy-sell>=25 else "SHORT" if sell>=55 and sell-buy>=25 else "BEKLE"
    if veto:decided="BEKLE"
    atr=x['atr14'] or 0
    stop=c-1.5*atr if decided=='LONG' else c+1.5*atr if decided=='SHORT' else None
    tp=c+2.25*atr if decided=='LONG' else c-2.25*atr if decided=='SHORT' else None
    return {"decision":decided,"score":safe(buy-sell,1),"long":safe(buy,1),"short":safe(sell,1),
            "confidence":None,"reasons":reasons,"veto":veto,"stop":safe(stop),"take_profit":safe(tp),
            "info":"Skor yön gücüdür; doğrulanmış kazanma ihtimali değildir. SL/TP yalnız analitik örnektir."}

def quant_stats(bars,tf):
    c=[num(x['c']) for x in bars if num(x['c'])>0]
    if len(c)<30:return {"status":"insufficient"}
    r=[math.log(c[i]/c[i-1]) for i in range(1,len(c))]
    recent=r[-60:];mu=statistics.mean(recent);sd=statistics.pstdev(recent)
    ann=math.sqrt(365*24*60/TF_MIN[tf]);vol=sd*ann*100
    # Gaussian 95% VaR is a model estimate for one candle, not a bound.
    var95=-(mu-1.645*sd)*100
    dd=[];high=c[0]
    for x in c:
        high=max(high,x);dd.append((x/high-1)*100)
    score=abs(c[-1]/c[-20]-1)*100
    return {"status":"ready","mean_return_pct":safe(100*mu,5),"vol_annualized_pct":safe(vol,3),
            "var95_1bar_pct":safe(var95,3),"max_price_drawdown_pct":safe(min(dd),3),
            "momentum20_pct":safe(100*(c[-1]/c[-20]-1),3),
            "regime":"YÜKSEK VOLATİLİTE" if vol>65 else "DÜŞÜK VOLATİLİTE" if vol<15 else "ORTA VOLATİLİTE",
            "note":"Kripto gibi 7/24 yıllıklandırma varsayımı; spot için seans farkları olabilir. VaR normal dağılım yaklaşımıdır."}

def _signal_for(strategy,i,bars,raw):
    if i<55:return 0
    c=bars[i]['c'];prev=bars[i-1]['c']
    e20=raw['ema20'][i];e50=raw['ema50'][i];r=raw['rsi14'][i];vwap=raw['vwap50'][i]
    if e20 is None or e50 is None or r is None:return 0
    if strategy=='ema_trend':return 1 if c>e20>e50 and r>55 else -1 if c<e20<e50 and r<45 else 0
    if strategy=='rsi_revert':return 1 if raw['rsi14'][i-1]<30<=r else -1 if raw['rsi14'][i-1]>70>=r else 0
    if strategy=='donchian':
        hi=max(x['h'] for x in bars[i-20:i]);lo=min(x['l'] for x in bars[i-20:i])
        return 1 if c>hi else -1 if c<lo else 0
    if strategy=='vwap_revert' and vwap:
        return 1 if prev<raw['vwap50'][i-1] and c>vwap and r<60 else -1 if prev>raw['vwap50'][i-1] and c<vwap and r>40 else 0
    if strategy=='smc_sweep':
        hi=max(x['h'] for x in bars[i-12:i]);lo=min(x['l'] for x in bars[i-12:i])
        return 1 if bars[i]['l']<lo and c>lo else -1 if bars[i]['h']>hi and c<hi else 0
    if strategy=='bb_break':
        up=raw['bb_up'][i];lo=raw['bb_low'][i]
        return 1 if up and c>up else -1 if lo and c<lo else 0
    if strategy=='momentum':return 1 if c>bars[i-5]['c'] and e20>e50 else -1 if c<bars[i-5]['c'] and e20<e50 else 0
    if strategy=='macd_cross':
        hist=raw['macd_hist']
        return 1 if hist[i] is not None and hist[i-1] is not None and hist[i-1]<=0<hist[i] else -1 if hist[i] is not None and hist[i-1] is not None and hist[i-1]>=0>hist[i] else 0
    return 0

def backtest(bars,strategy,fee_bps=4.0,slippage_bps=1.0):
    if strategy not in STRATEGIES:raise ValueError('Bilinmeyen strateji')
    if len(bars)<100:return {"error":"En az 100 kapanmış mum gereklidir."}
    ind=indicators(bars);raw=ind['_raw'];i=55;trades=[];equity=10000.0;curve=[{"t":bars[0]['t'],"equity":equity}]
    # Single position, 1 notional reference unit, no reinvestment/leverage.
    while i<len(bars)-2:
        side=_signal_for(strategy,i,bars,raw)
        atr=raw['atr14'][i]
        if not side or not atr or atr<=0:i+=1;continue
        entry_i=i+1;entry=bars[entry_i]['o']*(1+side*slippage_bps/10000)
        stop=entry-side*1.5*atr;take=entry+side*2.25*atr
        end=min(entry_i+12,len(bars)-1)
        j=entry_i;exit_price=bars[j]['c'];why='TIME'
        while j<=end:
            bar=bars[j];hit_stop=bar['l']<=stop if side==1 else bar['h']>=stop
            hit_take=bar['h']>=take if side==1 else bar['l']<=take
            if hit_stop:exit_price=stop;why='STOP';break  # adverse first if both hit
            if hit_take:exit_price=take;why='TP';break
            exit_price=bar['c'];j+=1
        j=min(j,end)
        exit_price=exit_price*(1-side*slippage_bps/10000)
        costs=(entry+exit_price)*fee_bps/10000
        pnl=side*(exit_price-entry)-costs
        equity+=pnl
        trades.append({"t":bars[entry_i]['t'],"exit_t":bars[j]['t'],"side":"LONG" if side>0 else "SHORT","entry":safe(entry),"exit":safe(exit_price),"pnl_usd_ref":safe(pnl,3),"reason":why})
        curve.append({"t":bars[j]['t'],"equity":safe(equity,2)})
        i=j+1
    wins=[t for t in trades if t['pnl_usd_ref']>0];losses=[t for t in trades if t['pnl_usd_ref']<0]
    peak=10000.0;dd=0.0
    for x in curve:peak=max(peak,x['equity']);dd=min(dd,(x['equity']/peak-1)*100)
    prof=sum(t['pnl_usd_ref'] for t in wins);loss=abs(sum(t['pnl_usd_ref'] for t in losses))
    return {"strategy":strategy,"label":STRATEGIES[strategy],"trades":trades[-100:],"trades_count":len(trades),
        "win_rate_pct":safe(100*len(wins)/len(trades),2) if trades else None,
        "profit_factor":safe(prof/loss,3) if loss else None,"net_pnl_usd_ref":safe(equity-10000,2),
        "max_drawdown_pct":safe(dd,3),"equity_curve":curve[-250:],
        "sample_candles":len(bars),"fee_bps_per_side":fee_bps,"slippage_bps_per_side":slippage_bps,
        "note":"Geçerli sinyal kapanmış mumda, sonraki mum açılışından giriş; aynı mumda TP+SL olursa SL kabul edilir. Referans 1 fiyat birimi, borsa kontratı/PnL çarpanı değildir. Futures funding, değişken ücret, piyasa etkisi dahil değildir."}
