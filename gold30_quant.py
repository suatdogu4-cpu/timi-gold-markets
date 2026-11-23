"""GOLD SCALP PRO 30G | read-only quantitative price/time research.

Developer: Suat DOGU. Uses ONLY same-source, CLOSED market candles.
No order placement. Historical frequencies are NOT calibrated trade probabilities.
Install: `from gold30_quant import register; register(app, M, closed_bars, quant_hub_daily_history)`
AFTER the quant_hub_daily_history definition at the bottom of main.py.
"""
from __future__ import annotations

import asyncio
import math
import statistics
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from fastapi import HTTPException
from fastapi.responses import FileResponse

VERSION = '1.0.0'
DAY = 86_400
WINDOW = 30 * DAY
INTERVAL = 15 * 60
ROOT = Path(__file__).resolve().parent
HORIZONS = [(5, '5m', 1, 300), (15, '15m', 1, 900),
            (30, '15m', 2, 900), (60, '15m', 4, 900), (120, '15m', 8, 900)]


def _r(x, n=2):
    try:
        y = float(x)
        return round(y, n) if math.isfinite(y) else None
    except (ValueError, TypeError):
        return None


def normalize_bars(rows):
    """Sort, de-duplicate and validate original OHLC rows, never interpolate."""
    out = {}
    for raw in rows or []:
        try:
            t = int(raw['t'])
            o, h, l, c = (float(raw[k]) for k in ('o', 'h', 'l', 'c'))
            v = float(raw.get('v') or 0)
            if (t < 1 or not all(math.isfinite(x) for x in (o, h, l, c, v))
                    or min(o, h, l, c) <= 0 or v < 0
                    or h < max(o, c, l) or l > min(o, c, h)):
                continue
            out[t] = dict(t=t, o=o, h=h, l=l, c=c, v=v)
        except (KeyError, TypeError, ValueError, OverflowError):
            continue
    return sorted(out.values(), key=lambda b: b['t'])


def atr_at(bars, idx, length=14):
    if idx < length:
        return None
    vals = []
    for j in range(idx - length + 1, idx + 1):
        b, prev = bars[j], bars[j-1]
        vals.append(max(b['h'] - b['l'], abs(b['h'] - prev['c']),
                        abs(b['l'] - prev['c'])))
    return statistics.mean(vals) if vals else None


def state_at(bars, i):
    if i < 22:
        return None
    close = bars[i]['c']
    ma = statistics.mean(b['c'] for b in bars[i-19:i+1])
    trend = 1 if close > ma * 1.0003 else -1 if close < ma * 0.9997 else 0
    old = bars[i-4]['c']
    momentum = 1 if close > old * 1.0002 else -1 if close < old * 0.9998 else 0
    return trend, momentum


def percentile(sorted_vals, p):
    if not sorted_vals:
        return None
    index = (len(sorted_vals)-1)*p
    lo, hi = math.floor(index), math.ceil(index)
    return sorted_vals[lo] + (sorted_vals[hi]-sorted_vals[lo])*(index-lo)


def wilson_bounds(success, total):
    if not total:
        return None
    z = 1.96
    p = success/total
    denom = 1 + z*z/total
    center = (p + z*z/(2*total))/denom
    spread = z*math.sqrt(p*(1-p)/total + z*z/(4*total*total))/denom
    return [_r(100*(center-spread), 1), _r(100*(center+spread), 1)]


def horizon_stats(bars, step_seconds, horizon_steps, live_price, min_count=40):
    """Non-overlapping, time-contiguous retrospective triple-barrier observations.

    Dynamic +/-0.75 ATR barriers are fixed at each historical start bar. Both
    barriers inside the same OHLC bar are AMBIGUOUS (not guessed from candle color).
    No features from future candles are used to select historical analogues.
    """
    b = normalize_bars(bars)
    duration = step_seconds*horizon_steps//60
    result = {'minutes': duration, 'interval':f'{step_seconds//60}m',
              'status':'INSUFFICIENT', 'condition':'none', 'sample_count':0,
              'observed_days':_r((b[-1]['t']-b[0]['t'])/DAY, 1) if len(b)>1 else 0,
              'estimated_live_win_probability':None}
    if len(b) < 110 or not live_price or live_price<=0:
        return result
    last_atr = atr_at(b, len(b)-1)
    last_state = state_at(b,len(b)-1)
    if last_atr is None or last_atr<=0 or not last_state:
        return result
    observations = []
    # Step h: avoids overlapping forecast intervals (not full statistical independence).
    for i in range(70, len(b)-horizon_steps, horizon_steps):
        if b[i+horizon_steps]['t']-b[i]['t'] != step_seconds*horizon_steps:
            continue
        if any(b[j]['t']-b[j-1]['t']!=step_seconds for j in range(i+1,i+horizon_steps+1)):
            continue
        a=atr_at(b,i)
        st=state_at(b,i)
        if not a or a<=0 or not st:
            continue
        upper=b[i]['c']+0.75*a
        lower=b[i]['c']-0.75*a
        outcome='TIMEOUT'; minutes=None
        for k in range(1,horizon_steps+1):
            n=b[i+k]
            hit_up=n['h']>=upper
            hit_down=n['l']<=lower
            if hit_up and hit_down:
                outcome='AMBIGUOUS';minutes=k*step_seconds/60;break
            if hit_up:
                outcome='UP';minutes=k*step_seconds/60;break
            if hit_down:
                outcome='DOWN';minutes=k*step_seconds/60;break
        observations.append({'state':st,'outcome':outcome, 'time':minutes,
                             'return':b[i+horizon_steps]['c']/b[i]['c']-1})
    matches=[x for x in observations if x['state']==last_state]
    condition='trend+momentum'
    if len(matches)<min_count:
        matches=[x for x in observations if x['state'][0]==last_state[0]]
        condition='trend'
    if len(matches)<min_count:
        matches=observations
        condition='unconditional'
    valid=[x for x in matches if x['outcome']!='AMBIGUOUS']
    ambiguous=len(matches)-len(valid)
    result.update({'sample_count':len(matches),'valid_count':len(valid),
                   'ambiguous_count':ambiguous,'condition':condition,
                   'atr':_r(last_atr), 'upper_barrier':_r(live_price+0.75*last_atr),
                   'lower_barrier':_r(live_price-0.75*last_atr),
                   'up_target2':_r(live_price+1.5*last_atr),
                   'down_target2':_r(live_price-1.5*last_atr),
                   'historical_count':len(observations)})
    if len(valid)<min_count or ambiguous>len(matches)*0.25:
        result['warning']='Etkin örnek sayısı az veya aynı mumda çift bariyer sık görülüyor.'
        return result
    up=sum(x['outcome']=='UP' for x in valid)
    down=sum(x['outcome']=='DOWN' for x in valid)
    wait=len(valid)-up-down
    endings=sorted(x['return'] for x in valid)
    reached=[x['time'] for x in valid if x['outcome'] in ('UP','DOWN')]
    result.update({
        'status':'RESEARCH', 'p_up_first':_r(100*up/len(valid),1),
        'p_down_first':_r(100*down/len(valid),1),
        'p_timeout':_r(100*wait/len(valid),1),
        'up_95_ci':wilson_bounds(up,len(valid)),
        'count_up':up, 'count_down':down, 'count_timeout':wait,
        'median_first_touch_minutes':_r(statistics.median(reached),1) if reached else None,
        'price_q10':_r(live_price*(1+percentile(endings,0.1))),
        'price_q50':_r(live_price*(1+percentile(endings,0.5))),
        'price_q90':_r(live_price*(1+percentile(endings,0.9))),
        'warning':'Geçmiş ilk-temas sıklığıdır; ileri test veya kalibrasyon yapılmış olasılık değildir.'
    })
    return result


def report(daily, fifteen, five, price, price_fresh, source,
           now=None, history=None):
    now=int(now if now is not None else time.time())
    d=normalize_bars(daily)
    b15=normalize_bars(fifteen)
    b5=normalize_bars(five)
    cutoff=now-WINDOW
    window=[x for x in d if x['t']+DAY>cutoff and x['t']+DAY<=now]
    coverage_days=_r((d[-1]['t']+DAY-d[0]['t'])/DAY,1) if d else 0
    full_30d=bool(window and min(x['t'] for x in window)<=cutoff+2*DAY
                  and len(window)>=18)
    high=max(window,key=lambda x:x['h']) if window else None
    low=min(window,key=lambda x:x['l']) if window else None
    atr_d=atr_at(d,len(d)-1) if len(d)>14 else None
    swings=[]
    for i in range(2,len(window)-2):
        x=window[i]
        if all(x['h']>window[j]['h'] for j in range(i-2,i+3) if j!=i):
            swings.append({'type':'TEPE','price':_r(x['h']),'time':x['t']})
        if all(x['l']<window[j]['l'] for j in range(i-2,i+3) if j!=i):
            swings.append({'type':'DIP','price':_r(x['l']),'time':x['t']})
    span=high['h']-low['l'] if high and low else None
    h_fresh=bool(b15 and 0<=now-(b15[-1]['t']+900)<=2700)
    f_fresh=bool(b5 and 0<=now-(b5[-1]['t']+300)<=900)
    prices_usable=bool(price_fresh and price and price>0)
    periods=[]
    for minutes, tf, steps, step in HORIZONS:
        bars=b5 if tf=='5m' else b15
        item=horizon_stats(bars,step,steps,price if prices_usable else None)
        item['horizon_minutes']=minutes
        # 30-day memory is the goal. If incomplete, show analytical context,
        # but do not label it validated for short-term trading.
        item['data_current']=f_fresh if tf=='5m' else h_fresh
        item['data_30d_complete']=bool(full_30d and (bars and bars[0]['t']<=cutoff+DAY))
        if item['status']=='RESEARCH' and (not item['data_current'] or not prices_usable):
            item['status']='STALE'
        periods.append(item)
    main=next((x for x in periods if x['horizon_minutes']==30),None)
    ready=bool(main and main['status']=='RESEARCH' and main['data_30d_complete']
               and main['valid_count']>=60 and price_fresh)
    skew=((main.get('p_up_first') or 0)-(main.get('p_down_first') or 0)) if ready else 0
    side='YUKARI EĞİLİM' if ready and skew>=20 else 'AŞAĞI EĞİLİM' if ready and skew<=-20 else 'BEKLE'
    return {
        'version':VERSION,'mode':'RESEARCH_ONLY','orders_enabled':False,
        'symbol':source.split(' ')[0], 'source':source,
        'computed_at_utc':datetime.fromtimestamp(now,timezone.utc).isoformat(),
        'price':_r(price) if prices_usable else None,
        'price_fresh':bool(price_fresh), 'decision':side,
        'decision_note':'Yön eğilimi geçmiş bariyer örneklerinin sıklığına dayanır; canlı işlem sinyali değildir.',
        'window':{'days':30,'from_utc':datetime.fromtimestamp(cutoff,timezone.utc).isoformat(),
                  'to_utc':datetime.fromtimestamp(now,timezone.utc).isoformat(),
                  'observed_daily_candles':len(window),'observed_daily_span':coverage_days,
                  'full_30d':full_30d,'high':_r(high['h']) if high else None,
                  'high_at':high['t'] if high else None,'low':_r(low['l']) if low else None,
                  'low_at':low['t'] if low else None,'range_dollars':_r(span),
                  'position_pct':_r(100*(price-low['l'])/span,1) if prices_usable and span and span>0 else None,
                  'mid':_r((high['h']+low['l'])/2) if span is not None else None,
                  'atr14_daily':_r(atr_d),
                  'retracements':{str(v):_r(high['h']-span*v) for v in (0.236,0.382,0.5,0.618,0.786)} if span else {},
                  'confirmed_pivots':swings[-10:],
                  'daily_series':[{'t':x['t'],'c':_r(x['c']),'h':_r(x['h']),'l':_r(x['l'])} for x in window]},
        'data_quality':{'recent_15m_bars':len(b15),'recent_5m_bars':len(b5),
                        'fifteen_last_closed_utc':datetime.fromtimestamp(b15[-1]['t']+900,timezone.utc).isoformat() if b15 else None,
                        'five_last_closed_utc':datetime.fromtimestamp(b5[-1]['t']+300,timezone.utc).isoformat() if b5 else None,
                        'fifteen_current':h_fresh,'five_current':f_fresh,
                        'history':history or {}},
        'horizons':periods,
        'limitations':['OHLC aynı mumda iki bariyere dokunursa sonuç belirsizdir.',
                       'Çakışmayan örnek aralıkları bağımsızlığı garanti etmez.',
                       'Geçmiş sıklıklar kalibre edilmiş ileri tahmin değildir.',
                       'XAUUSD ve Bitget XAUUSDT fiyat serileri birbirine karıştırılmaz.',
                       'Gerçek para emirleri veya garantili kâr hesaplanmaz.']}


def register(app, market, closed_bars, daily_history):
    """Register isolated routes after main.py's quant_hub_daily_history exists."""
    history_cache={}
    lock=asyncio.Lock()

    async def get_15m(symbol):
        # OANDA has separate authenticated history and cannot use Bitget paging.
        if symbol!='XAUUSDT':
            rows=closed_bars(await market.get_candles(symbol,'15m',500),'15m')
            return rows, {'provider':'OANDA','pages':0,'complete_30d':False}
        last=history_cache.get(symbol)
        if last and time.monotonic()-last['at']<600:
            return last['bars'],dict(last['meta'])
        async with lock:
            last=history_cache.get(symbol)
            if last and time.monotonic()-last['at']<600:
                return last['bars'],dict(last['meta'])
            rows=closed_bars(await market.get_candles(symbol,'15m',700),'15m')
            all_bars={int(x['t']):x for x in rows}
            cutoff=int(time.time())-WINDOW
            pages=0; warning=None
            previous_earliest=min(all_bars) if all_bars else None
            # 100 candle maximum per history page; at most 32 pages.
            while previous_earliest is not None and previous_earliest>cutoff and pages<32:
                end_ms=previous_earliest*1000-1
                start_ms=max(0,end_ms-89*DAY*1000)
                params={'category':'USDT-FUTURES','symbol':'XAUUSDT',
                        'interval':'15m','type':'market','startTime':str(start_ms),
                        'endTime':str(end_ms),'limit':100}
                try:
                    raw=await market.bitget('/api/v3/market/history-candles',params)
                except Exception as e:
                    warning=f'Geçmiş seri alınamadı: {type(e).__name__}'
                    break
                pages+=1
                added=0
                for item in raw if isinstance(raw,list) else []:
                    try:
                        b={'t':int(item[0])//1000, 'o':float(item[1]),
                           'h':float(item[2]), 'l':float(item[3]),
                           'c':float(item[4]), 'v':float(item[5])}
                        if b['t']<previous_earliest and b['t']>=cutoff-INTERVAL and b['t'] not in all_bars:
                            for clean in normalize_bars([b]):
                                all_bars[clean['t']]=clean
                                added+=1
                    except (TypeError, ValueError, IndexError, OverflowError):
                        continue
                new_earliest=min(all_bars) if all_bars else None
                if not added or new_earliest>=previous_earliest:
                    warning=warning or 'Sağlayıcı geçmiş sayfalamasında ilerleme yok.'
                    break
                previous_earliest=new_earliest
                await asyncio.sleep(0.08)
            selected=[x for x in normalize_bars(all_bars.values()) if x['t']>=cutoff-INTERVAL]
            meta={'provider':'Bitget UTA v3','pages':pages,
                  'first_utc':datetime.fromtimestamp(selected[0]['t'],timezone.utc).isoformat() if selected else None,
                  'bars':len(selected), 'complete_30d':bool(selected and selected[0]['t']<=cutoff+DAY),
                  'warning':warning}
            # Do not cache a failed incomplete fetch for long; offer retry.
            history_cache[symbol]={'at':time.monotonic()-(540 if warning else 0),
                                   'bars':selected,'meta':meta}
            return selected,meta

    @app.get('/gold30',include_in_schema=False)
    async def gold30_page():
        return FileResponse(ROOT/'gold30.html',media_type='text/html')

    @app.get('/api/gold30')
    async def gold30_api(symbol:str='XAUUSDT'):
        if symbol not in ('XAUUSDT','XAUUSD'):
            raise HTTPException(400,'Yalnız XAUUSDT/XAUUSD desteklenir')
        errors={}
        async def grab(label,coro):
            try:return await coro
            except Exception as exc:
                errors[label]=f'{type(exc).__name__}: {str(exc)[:120]}'
                return None
        daily_res, m15_res, m5_res=await asyncio.gather(
            grab('daily',daily_history(symbol)),grab('15m',get_15m(symbol)),
            grab('5m',market.get_candles(symbol,'5m',700)))
        daybars= daily_res[0] if daily_res else []
        b15,meta= m15_res if m15_res else ([],{})
        b5=closed_bars(m5_res,'5m') if m5_res else []
        snap=market.snapshot()
        if symbol=='XAUUSDT':
            quote=snap.get('price') or {}
            current=_r(quote.get('last'))
            valid=bool((snap.get('valid') or {}).get('ticker'))
        else:
            quote=snap.get('spot') or {}
            current=_r(quote.get('last'))
            valid=bool(quote and (snap.get('spot_age_s') is not None)
                       and snap['spot_age_s']<20)
        res=await asyncio.to_thread(report,daybars,b15,b5,current,valid,
                            symbol+' '+('Bitget UTA v3' if symbol=='XAUUSDT' else 'OANDA spot'),
                            None,meta)
        res['data_quality']['errors']=errors
        res['data_quality']['daily_info']=(daily_res[1] if daily_res else {})
        return res
