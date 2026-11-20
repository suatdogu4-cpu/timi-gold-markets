"""GOLD SCALP PRO v1.0 | Developer: Suat DOĞU
Read-only market analytics. Only XAUUSDT (Bitget UTA v3 public) and
XAUUSD (OANDA practice, OPTIONAL private market-data credentials).
Public Bitget market endpoints never require an exchange trading key.
No order placement code exists in this service.
"""
from __future__ import annotations
import asyncio
import csv
import io
import json
import logging
import os
import time
from collections import deque
from contextlib import asynccontextmanager, suppress
from datetime import datetime, timezone
from zoneinfo import ZoneInfo
from pathlib import Path
from typing import Any

import httpx
import websockets
from fastapi import FastAPI, HTTPException, Query, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse
from quant import TF_MIN, STRATEGIES, indicators, smc, flow_metrics, score_signal, quant_stats, backtest, num

LOG=logging.getLogger('gold');logging.basicConfig(level=logging.INFO)
ROOT=Path(__file__).resolve().parent
REST='https://api.bitget.com'
WS='wss://ws.bitget.com/v3/ws/public'
OANDA_BASE='https://api-fxpractice.oanda.com'
OANDA_TOKEN=os.getenv('OANDA_TOKEN','').strip()
OANDA_ACCOUNT=os.getenv('OANDA_ACCOUNT_ID','').strip()
FRED_KEY=os.getenv('FRED_API_KEY','').strip()
TF_OANDA={'1m':'M1','3m':'M3','5m':'M5','15m':'M15','30m':'M30','1H':'H1','4H':'H4','1D':'D'}
MAX_CANDLES=700

def nowms():return int(time.time()*1000)

def age(ts):return max(0,(nowms()-ts)/1000) if ts else None

def fresh(ts,seconds):return ts>0 and age(ts)<=seconds

def err_text(ex):return f'{type(ex).__name__}: {str(ex)[:190]}'

class Market:
    def __init__(self):
        self.client: httpx.AsyncClient|None=None
        self.lock=asyncio.Lock()
        self.ws_online=False
        self.ws_error='Henüz bağlanmadı'
        self.last_ws=0
        self.last_pong=0
        self.ticker={};self.ticker_ts=0
        self.depth_bids={};self.depth_asks={};self.book_ts=0;self.book_seq=None
        self.trades=deque(maxlen=6000);self.trade_ids=set();self.trades_ts=0
        self.candles={};self.candle_updated={};self.candle_errors={}
        self.spot_quote={};self.spot_ts=0;self.spot_error='OANDA bağlantısı yapılandırılmadı'
        self.macro_cache={};self.macro_ts=0;self.macro_error=None
        self.last_bitget_rest=0;self.last_spot_rest=0
        self.channels={}
        self.bg=[]
        self.clients=set()

    async def get_json(self,url,params=None,headers=None):
        if not self.client:raise RuntimeError('HTTP istemcisi hazır değil')
        r=await self.client.get(url,params=params,headers=headers)
        r.raise_for_status();return r.json()

    async def bitget(self,path,params):
        j=await self.get_json(REST+path,params)
        if str(j.get('code'))!='00000':raise ValueError(f'Bitget: {j.get("code")} {j.get("msg","")[:120]}')
        return j['data']

    async def start(self):
        self.client=httpx.AsyncClient(timeout=httpx.Timeout(12.0,connect=8),follow_redirects=False,
                                      headers={'User-Agent':'GoldScalpPro/1.0 public-read-only'})
        self.bg=[asyncio.create_task(self.run_ws(),name='bitget_uta_ws'),
                 asyncio.create_task(self.run_rest(),name='periodic_rest'),
                 asyncio.create_task(self.run_spot(),name='oanda_optional')]
        LOG.info('Gold gateway started. Optional OANDA: %s',bool(OANDA_TOKEN and OANDA_ACCOUNT))

    async def stop(self):
        for task in self.bg:task.cancel()
        await asyncio.gather(*self.bg,return_exceptions=True)
        if self.client:await self.client.aclose()

    def feed_trade(self,t):
        try:
            trade={"t":int(t.get('T') or t.get('ts') or nowms()),"p":num(t.get('p') or t.get('price')),
                "v":num(t.get('v') or t.get('size')),"side":str(t.get('S') or t.get('side') or '').lower(),
                "id":str(t.get('i') or t.get('tradeId') or '')}
            if trade['p']<=0 or trade['v']<=0 or trade['side'] not in ('buy','sell'):return
            # No duplicated snapshot fills or replay reconnects.
            if trade['id'] and trade['id'] in self.trade_ids:return
            if trade['id']:self.trade_ids.add(trade['id'])
            self.trades.append(trade);self.trades_ts=nowms()
            if len(self.trade_ids)>8000:self.trade_ids={x['id'] for x in self.trades if x['id']}
        except (ValueError,TypeError):return

    def feed_depth(self,d,action):
        try:
            seq=int(d.get('seq',0));pseq=int(d.get('pseq',0))
            if action=='snapshot':
                self.depth_bids={num(p):num(q) for p,q in d.get('b',[]) if num(p)>0 and num(q)>0}
                self.depth_asks={num(p):num(q) for p,q in d.get('a',[]) if num(p)>0 and num(q)>0}
            elif action=='update':
                if self.book_seq is None:raise ValueError('Depth update before snapshot')
                if pseq!=self.book_seq:raise ValueError(f'Depth sequence gap {self.book_seq}!={pseq}')
                if seq<=self.book_seq:raise ValueError('Depth sequence did not increase')
                for key,book in [('b',self.depth_bids),('a',self.depth_asks)]:
                    for p,q in d.get(key,[]):
                        price=num(p);qty=num(q)
                        if qty>0:book[price]=qty
                        else:book.pop(price,None)
            else:return
            self.book_seq=seq
            self.book_ts=nowms()
        except (TypeError,ValueError) as ex:
            self.depth_bids={};self.depth_asks={};self.book_seq=None;self.book_ts=0
            raise RuntimeError(str(ex)) from ex

    def on_message(self,j):
        if j.get('event'):
            if j.get('event')=='error':
                arg=j.get('arg',{});self.channels[arg.get('topic','unknown')]=str(j.get('msg') or j.get('code'))
                self.ws_error=f'Abonelik hatası: {self.channels}'
                LOG.warning('Bitget subscription error: %s',self.ws_error)
            return
        arg=j.get('arg') or {}
        if arg.get('symbol')!='XAUUSDT':return
        topic=arg.get('topic');data=j.get('data') or []
        if not isinstance(data,list):data=[data]
        if topic=='ticker':
            if data:
                d=data[-1];price=num(d.get('lastPrice'))
                if price>0:
                    self.ticker={"last":price,"bid":num(d.get('bid1Price')),"ask":num(d.get('ask1Price')),
                        "high24":num(d.get('highPrice24h')),"low24":num(d.get('lowPrice24h')),
                        "change24_pct":num(d.get('price24hPcnt'))*100,"volume24":num(d.get('volume24h')),
                        "turnover24":num(d.get('turnover24h')),"mark":num(d.get('markPrice')),
                        "index":num(d.get('indexPrice')),"funding":num(d.get('fundingRate')),
                        "oi":num(d.get('openInterest')), "nextFunding":d.get('nextFundingTime')}
                    self.ticker_ts=nowms()
        if topic=='publicTrade':
            if j.get('action')=='snapshot':
                # Preserve fill history but do not count duplicate initial snapshot as new trades
                for d in data:self.feed_trade(d)
            else:
                for d in data:self.feed_trade(d)
        if topic=='books50':
            for d in data:self.feed_depth(d,j.get('action'))
        self.last_ws=nowms()

    async def run_ws(self):
        retry=2
        while True:
            try:
                self.depth_bids={};self.depth_asks={};self.book_seq=None;self.book_ts=0
                self.ws_online=False
                async with websockets.connect(WS,ping_interval=20,ping_timeout=20,open_timeout=18,
                                               close_timeout=5,max_size=2**22) as ws:
                    args=[{"instType":"usdt-futures","topic":topic,"symbol":"XAUUSDT"}
                          for topic in ('ticker','publicTrade','books50')]
                    await ws.send(json.dumps({"op":"subscribe","args":args}))
                    self.ws_online=True;self.ws_error='';retry=2;self.last_pong=nowms()
                    async def heartbeat():
                        while True:
                            await asyncio.sleep(25)
                            await ws.send('ping')  # Bitget requires application-level text ping
                            await asyncio.sleep(25)
                            if not fresh(self.last_pong,50):
                                await ws.close(code=1011,reason='Missing Bitget text pong')
                                return
                    ping_task=asyncio.create_task(heartbeat())
                    try:
                        async for raw in ws:
                            if raw=='pong':self.last_pong=nowms();continue
                            try:obj=json.loads(raw)
                            except (ValueError,TypeError):continue
                            self.on_message(obj)
                    finally:
                        ping_task.cancel()
                        with suppress(asyncio.CancelledError):await ping_task
            except asyncio.CancelledError:raise
            except Exception as ex:
                self.ws_error=err_text(ex)
                LOG.warning('Bitget WebSocket reconnect: %s',self.ws_error)
            finally:self.ws_online=False
            await asyncio.sleep(retry);retry=min(retry*1.7,45)

    async def fetch_bitget_candles(self,tf='1m',limit=500):
        tf=valid_tf(tf);limit=min(MAX_CANDLES,max(100,int(limit)))
        data=await self.bitget('/api/v3/market/candles',{'category':'USDT-FUTURES','symbol':'XAUUSDT',
                                                          'interval':tf,'type':'market','limit':limit})
        parsed=[]
        for d in data:
            try:
                t=int(d[0])//1000;bar={"t":t,"o":num(d[1]),"h":num(d[2]),"l":num(d[3]),"c":num(d[4]),"v":num(d[5])}
                if bar['c']>0 and bar['h']>=bar['l'] and bar['o']>0:parsed.append(bar)
            except (TypeError,ValueError,IndexError):continue
        parsed={x['t']:x for x in parsed}
        parsed=sorted(parsed.values(),key=lambda x:x['t'])
        if not parsed:raise ValueError('Bitget mum verisi boş / sembol mevcut değil')
        self.candles[('XAUUSDT',tf)]=parsed
        self.candle_updated[('XAUUSDT',tf)]=nowms()
        self.candle_errors.pop(('XAUUSDT',tf),None)
        return parsed

    async def fetch_spot_candles(self,tf='1m',limit=500):
        if not OANDA_TOKEN or not OANDA_ACCOUNT:raise ValueError('XAUUSD için OANDA_TOKEN ve OANDA_ACCOUNT_ID tanımlayın')
        if not self.client:raise ValueError('HTTP hazır değil')
        params={'granularity':TF_OANDA[tf],'count':min(limit,500),'price':'M'}
        url=f'{OANDA_BASE}/v3/accounts/{OANDA_ACCOUNT}/instruments/XAU_USD/candles'
        j=await self.get_json(url,params,{'Authorization':f'Bearer {OANDA_TOKEN}'})
        parsed=[]
        for d in j.get('candles',[]):
            try:
                mid=d['mid'];dt=datetime.fromisoformat(d['time'].replace('Z','+00:00'))
                parsed.append({"t":int(dt.timestamp()),"o":num(mid['o']),"h":num(mid['h']),
                               "l":num(mid['l']),"c":num(mid['c']),"v":num(d.get('volume')),
                               "complete":bool(d.get('complete'))})
            except (KeyError,ValueError,TypeError):continue
        parsed.sort(key=lambda x:x['t'])
        if not parsed:raise ValueError('OANDA XAU_USD mum erişimi bulunamadı')
        self.candles[('XAUUSD',tf)]=parsed;self.candle_updated[('XAUUSD',tf)]=nowms()
        self.candle_errors.pop(('XAUUSD',tf),None)
        return parsed

    async def get_candles(self,symbol,tf,limit=500,force=False):
        key=(symbol,tf)
        cached=self.candles.get(key)
        ttl=max(12,TF_MIN[tf]*25) if symbol=='XAUUSDT' else max(25,TF_MIN[tf]*45)
        if not force and cached and fresh(self.candle_updated.get(key,0),ttl) and len(cached)>=min(limit,100):return cached[-limit:]
        try:
            if symbol=='XAUUSD':return (await self.fetch_spot_candles(tf,limit))[-limit:]
            return (await self.fetch_bitget_candles(tf,limit))[-limit:]
        except Exception as ex:
            self.candle_errors[key]=err_text(ex)
            if cached and fresh(self.candle_updated.get(key,0),max(120,TF_MIN[tf]*180)):return cached[-limit:]
            raise

    async def fetch_initial_rest(self):
        # REST bootstrap only when WebSocket has not delivered a fresher ticker/book.
        data=await self.bitget('/api/v3/market/tickers',{'category':'USDT-FUTURES','symbol':'XAUUSDT'})
        entries=data if isinstance(data,list) else [data]
        if entries and not fresh(self.ticker_ts,15):
            self.on_message({'arg':{'symbol':'XAUUSDT','topic':'ticker'},'data':entries})
            # REST is a fallback, not a WS claim
            self.last_ws=0
        if not fresh(self.book_ts,15):
            d=await self.bitget('/api/v3/market/orderbook',{'category':'USDT-FUTURES','symbol':'XAUUSDT','limit':50})
            if d and not fresh(self.book_ts,15):
                self.depth_bids={num(p):num(q) for p,q in d.get('b',[]) if num(p)>0 and num(q)>0}
                self.depth_asks={num(p):num(q) for p,q in d.get('a',[]) if num(p)>0 and num(q)>0}
                # No sequence provided by REST; NEVER apply incremental books50 to REST book.
                self.book_seq=None;self.book_ts=nowms()
        self.last_bitget_rest=nowms()

    async def run_rest(self):
        await asyncio.sleep(1)
        while True:
            try:
                if not fresh(self.ticker_ts,30) or not fresh(self.book_ts,30):
                    await self.fetch_initial_rest()
                # Pre-cache 1m, 5m and 15m. Others fetched on demand.
                await self.get_candles('XAUUSDT','1m',500,force=True)
                await self.get_candles('XAUUSDT','5m',500,force=True)
                await self.get_candles('XAUUSDT','15m',500,force=True)
            except asyncio.CancelledError:raise
            except Exception as ex:LOG.warning('REST bootstrap/candles: %s',err_text(ex))
            await asyncio.sleep(45)

    async def run_spot(self):
        if not OANDA_TOKEN or not OANDA_ACCOUNT:return
        while True:
            try:
                j=await self.get_json(f'{OANDA_BASE}/v3/accounts/{OANDA_ACCOUNT}/pricing',
                                      {'instruments':'XAU_USD'},
                                      {'Authorization':f'Bearer {OANDA_TOKEN}'})
                q=next((x for x in j.get('prices',[]) if x.get('instrument')=='XAU_USD'),None)
                if not q:raise ValueError('OANDA XAU_USD fiyat erişimi yok')
                bid=num(q.get('bids',[{}])[0].get('price')) if q.get('bids') else 0
                ask=num(q.get('asks',[{}])[0].get('price')) if q.get('asks') else 0
                if bid<=0 or ask<=0:raise ValueError('OANDA çift yönlü fiyat boş')
                self.spot_quote={'last':(bid+ask)/2,'bid':bid,'ask':ask}
                self.spot_ts=nowms();self.spot_error=''
            except asyncio.CancelledError:raise
            except Exception as ex:self.spot_error=err_text(ex)
            await asyncio.sleep(15)

    async def macro(self):
        if self.macro_cache and fresh(self.macro_ts,6*3600):return self.macro_cache
        series={'DFII10':'ABD 10Y reel faiz','DGS10':'ABD 10Y nominal faiz','T10YIE':'10Y enflasyon beklentisi','DTWEXBGS':'Geniş dolar endeksi'}
        out={}
        async def fetch_one(key,label):
            try:
                if FRED_KEY:
                    j=await self.get_json('https://api.stlouisfed.org/fred/series/observations',
                        {'series_id':key,'api_key':FRED_KEY,'file_type':'json','sort_order':'desc','limit':12})
                    vals=[{'date':x['date'],'value':num(x['value'],None)} for x in j.get('observations',[]) if x.get('value') not in ('.',None)]
                else:
                    # FRED publicly publishes CSV chart downloads; not guaranteed SLA or API.
                    u='https://fred.stlouisfed.org/graph/fredgraph.csv'
                    resp=await self.client.get(u,params={'id':key,'cosd':'2026-01-01'});resp.raise_for_status()
                    if len(resp.content)>2_000_000:raise ValueError('FRED response too large')
                    parsed=list(csv.DictReader(io.StringIO(resp.text)))
                    vals=[{'date':x.get('observation_date') or x.get('DATE'), 'value':num(x.get(key),None)} for x in parsed if x.get(key) and x.get(key)!='.'][-12:][::-1]
                if not vals:raise ValueError('Seri boş')
                out[key]={'label':label,'last':vals[0]['value'],'date':vals[0]['date'],
                          'previous':vals[1]['value'] if len(vals)>1 else None,'source':'FRED'}
            except Exception as ex:out[key]={'label':label,'last':None,'error':err_text(ex),'source':'FRED'}
        await asyncio.gather(*(fetch_one(k,v) for k,v in series.items()))
        self.macro_cache=out;self.macro_ts=nowms()
        return out

    def snapshot(self):
        ts=nowms()
        bids=sorted(self.depth_bids.items(),reverse=True)[:50]
        asks=sorted(self.depth_asks.items())[:50]
        recent=[x for x in self.trades if 0<=ts-x['t']<=120000]
        flow=flow_metrics(bids,asks,recent,ts)
        validity={'ticker':fresh(self.ticker_ts,12),'book':fresh(self.book_ts,12),
                  'trades':fresh(self.trades_ts,25)}
        spot_valid=fresh(self.spot_ts,45)
        return {'server_time':ts,'symbol':'XAUUSDT','price':self.ticker if validity['ticker'] else None,
            'spot':self.spot_quote if spot_valid else None,'spot_age_s':age(self.spot_ts),
            'spot_status':('CANLI (15 sn REST)' if spot_valid else 'YAPILANDIRILMADI' if not OANDA_TOKEN else 'GECİKMELİ'),
            'source':'Bitget UTA v3 public + optional OANDA v20 practice',
            'age_s':{'ticker':age(self.ticker_ts),'book':age(self.book_ts),'trades':age(self.trades_ts)},
            'valid':validity,'ws_connected':self.ws_online,'ws_error':self.ws_error,
            'channels':self.channels,'bids':bids if validity['book'] else [],'asks':asks if validity['book'] else [],
            'trades':recent[-60:] if validity['trades'] else [],'flow':flow if validity['book'] and validity['trades'] else None,
            'errors':{f'{k[0]}/{k[1]}':v for k,v in self.candle_errors.items()},
            'notes':['Bitget derinlik küresel altın emir defteri değildir.','Spot ve futures fiyatları ayrı kaynaktır.',
                     'Geçmiş snapshot ve güncel WS verisi aynı örnekleme sayılmamalıdır.']}

M=Market()

def valid_tf(tf):
    if tf not in TF_MIN:raise HTTPException(400,'Geçersiz zaman dilimi')
    return tf

def valid_symbol(symbol):
    if symbol not in ('XAUUSDT','XAUUSD'):raise HTTPException(400,'Yalnız XAUUSD ve XAUUSDT destekleniyor')
    return symbol

def closed_bars(bars,tf):
    step=TF_MIN[tf]*60
    # Bitget includes current forming bar, OANDA includes complete bool; never use it for inference.
    current=int(time.time())
    return [x for x in bars if x.get('complete') is not False and x['t']+step<=current]

@asynccontextmanager
async def lifespan(app):
    await M.start()
    try:yield
    finally:await M.stop()

app=FastAPI(title='GOLD SCALP PRO',version='1.0.0',lifespan=lifespan)

@app.get('/')
async def index():return FileResponse(ROOT/'index.html')

# V2.2.3: Serve the existing modular front-end assets directly.
# The legacy API, WebSocket and analysis paths are unchanged.
@app.get('/gold_style.css', include_in_schema=False)
async def gold_style_asset():
    return FileResponse(ROOT / 'gold_style.css', media_type='text/css')

@app.get('/gold_app.js', include_in_schema=False)
async def gold_app_asset():
    return FileResponse(ROOT / 'gold_app.js', media_type='application/javascript')


# QUANT HUB v3: public front-end resources (no auth data exposed).
@app.get('/gold_quant_hub.css',include_in_schema=False)
async def quant_hub_css():
    return FileResponse(ROOT / 'gold_quant_hub.css', media_type='text/css')

@app.get('/gold_quant_hub.js',include_in_schema=False)
async def quant_hub_js():
    return FileResponse(ROOT / 'gold_quant_hub.js', media_type='application/javascript')

@app.get('/api/health')
async def health():
    s=M.snapshot();return {'app':'GOLD SCALP PRO','version':'1.0.0','status':'online',
        'time_utc':datetime.now(timezone.utc).isoformat(),'bitget_ws':s['ws_connected'],
        'symbol':'XAUUSDT','feed_valid':s['valid'],'feed_age_seconds':s['age_s'],
        'spot_configured':bool(OANDA_TOKEN and OANDA_ACCOUNT),'spot_age_s':s['spot_age_s'],
        'last_errors':{'ws':s['ws_error'],'spot':M.spot_error,'candles':s['errors']},
        'live_external_verified':bool(s['ws_connected'] and s['valid']['ticker'] and s['valid']['book'] and s['valid']['trades'])}

@app.get('/api/snapshot')
async def snapshot():return M.snapshot()

@app.get('/api/candles')
async def candles(symbol:str='XAUUSDT',tf:str='1m',limit:int=Query(default=350,ge=100,le=700),refresh:bool=False):
    symbol=valid_symbol(symbol);tf=valid_tf(tf)
    try:
        bars=await M.get_candles(symbol,tf,limit,force=refresh)
        return {'symbol':symbol,'tf':tf,'bars':bars,'source':'Bitget UTA' if symbol=='XAUUSDT' else 'OANDA v20',
                'updated_ms':M.candle_updated.get((symbol,tf)),
                'closed_count':len(closed_bars(bars,tf)), 'warning':'Son mum halen oluşuyor olabilir.'}
    except Exception as ex:raise HTTPException(503,err_text(ex))

def session_info():
    now=datetime.now(timezone.utc)
    london=now.astimezone(ZoneInfo('Europe/London'))
    ny=now.astimezone(ZoneInfo('America/New_York'))
    london_open=london.weekday()<5 and 8<=london.hour<17
    ny_open=ny.weekday()<5 and 8<=ny.hour<17
    return {'london_local':london.strftime('%H:%M %Z'),'ny_local':ny.strftime('%H:%M %Z'),
        'london_open':london_open,'ny_open':ny_open,
        'session':'LONDRA + NEW YORK' if london_open and ny_open else 'LONDRA' if london_open else 'NEW YORK' if ny_open else 'ASYA/SEANS DIŞI',
        'note':'Saatler yaklaşık aktif spot piyasa seanslarıdır; tatil/özel işlem saati hesabı içermez.'}

@app.get('/api/analysis')
async def analysis(symbol:str='XAUUSDT',tf:str='1m',refresh:bool=False):
    symbol=valid_symbol(symbol);tf=valid_tf(tf)
    try:all_bars=await M.get_candles(symbol,tf,550,force=refresh)
    except Exception as ex:raise HTTPException(503,err_text(ex))
    bars=closed_bars(all_bars,tf)
    ix=indicators(bars)
    public={'latest':ix['latest'],'series':ix['series'],'count':ix['count']}
    structure=smc(bars)
    snap=M.snapshot();flow=snap['flow'] or {}
    candle_age=age(M.candle_updated.get((symbol,tf),0))
    candle_ok=bool(bars and len(bars)>210 and int(time.time())-bars[-1]['t']<=TF_MIN[tf]*60*3+90)
    valid=dict(snap['valid']);valid['candles']=candle_ok
    score=score_signal(bars,public,structure,flow,valid,symbol)
    # MTF guard uses same source, independent closed bars. Never interpolate a missing TF.
    mtf_readings=[]
    if symbol=='XAUUSDT' and tf in ('1m','3m','5m','15m'):
        async def tf_read(t):
            try:
                b=closed_bars(await M.get_candles(symbol,t,300),t)
                x=indicators(b)['latest']
                direction='LONG' if x.get('ema50') and x['close']>x['ema20']>x['ema50'] and x['rsi14']>=50 else 'SHORT' if x.get('ema50') and x['close']<x['ema20']<x['ema50'] and x['rsi14']<=50 else 'KARIŞIK'
                return {'tf':t,'direction':direction}
            except Exception as ex:return {'tf':t,'direction':'VERİ YOK','error':err_text(ex)}
        mtf_readings=await asyncio.gather(*(tf_read(t) for t in ('1m','3m','5m')))
        opposing=sum(x['direction'] in ('LONG','SHORT') and x['direction']!=score['decision'] for x in mtf_readings)
        # A strong one-timeframe signal cannot bypass multiple opposing lower timeframes.
        if score['decision'] in ('LONG','SHORT') and opposing>=2:
            score['veto'].append('1m/3m/5m MTF: en az iki zaman dilimi ters yönde')
            score['decision']='BEKLE';score['stop']=None;score['take_profit']=None
    return {'symbol':symbol,'tf':tf,'indicators':public,'smc':structure,
            'mtf':mtf_readings,'session':session_info(),
            'quant':quant_stats(bars,tf),'decision':score,'data':{'last_closed_time':bars[-1]['t'] if bars else None,
                'closed_bars':len(bars),'source':'Bitget UTA' if symbol=='XAUUSDT' else 'OANDA v20',
                'candles_age_s':candle_age,'candles_valid':candle_ok,'flow_valid':bool(snap['flow']),
                'market_valid':valid,'spot_requires_oanda':symbol=='XAUUSD'}}

@app.get('/api/mtf')
async def mtf(symbol:str='XAUUSDT'):
    symbol=valid_symbol(symbol)
    rows=[]
    async def one(tf):
        try:
            bars=closed_bars(await M.get_candles(symbol,tf,350),tf)
            ix=indicators(bars)['latest']
            if not ix.get('ema50') or ix.get('rsi14') is None:return {'tf':tf,'direction':'VERİ YOK'}
            direction='LONG' if ix['close']>ix['ema20']>ix['ema50'] and ix['rsi14']>=50 else 'SHORT' if ix['close']<ix['ema20']<ix['ema50'] and ix['rsi14']<=50 else 'KARIŞIK'
            return {'tf':tf,'direction':direction,'rsi':ix['rsi14'],'ema20':ix['ema20'],'ema50':ix['ema50']}
        except Exception as ex:return {'tf':tf,'direction':'VERİ YOK','error':err_text(ex)}
    rows=await asyncio.gather(*(one(x) for x in ('1m','3m','5m','15m','1H','4H')))
    return {'symbol':symbol,'rows':rows,'timestamp_ms':nowms()}

@app.get('/api/strategies')
async def strategies():return {'strategies':STRATEGIES}

@app.get('/api/backtest')
async def testing(symbol:str='XAUUSDT',tf:str='5m',strategy:str='ema_trend',
                  fee_bps:float=Query(default=4,ge=0,le=30),slippage_bps:float=Query(default=1,ge=0,le=30)):
    symbol=valid_symbol(symbol);tf=valid_tf(tf)
    if strategy not in STRATEGIES:raise HTTPException(400,'Bilinmeyen strateji')
    try:
        candles=await M.get_candles(symbol,tf,700)
        result=await asyncio.to_thread(backtest,closed_bars(candles,tf),strategy,fee_bps,slippage_bps)
        return {'symbol':symbol,'tf':tf,**result}
    except Exception as ex:raise HTTPException(503,err_text(ex))

@app.get('/api/macro')
async def macro():return {'data':await M.macro(),'cached_at':M.macro_ts,
                           'note':'FRED makro serileri anlık tick verisi değildir; yayın tarihi her seri için ayrıdır.'}

@app.get('/api/config')
async def config():return {'app':'GOLD SCALP PRO','developer':'Suat DOĞU',
    'spot_configured':bool(OANDA_TOKEN and OANDA_ACCOUNT),'spot_instrument':'XAU_USD',
    'symbols':['XAUUSDT','XAUUSD'],'timeframes':list(TF_MIN),
    'read_only':True,'orders_enabled':False,'public_keys_required':False,'strategy_count':len(STRATEGIES),
    'chart_credit':'TradingView Lightweight Charts™ (Apache 2.0; attribution required)'}

@app.websocket('/ws/stream')
async def ws_stream(websocket:WebSocket):
    if len(M.clients)>=30:
        await websocket.close(code=1013,reason='Too many clients');return
    await websocket.accept();M.clients.add(websocket)
    try:
        while True:
            await websocket.send_json({'type':'snapshot','payload':M.snapshot()})
            await asyncio.sleep(1)
    except (WebSocketDisconnect,RuntimeError,OSError):pass
    finally:M.clients.discard(websocket)

@app.get('/api/correlation')
async def correlation(tf:str='15m'):
    tf=valid_tf(tf)
    if not (OANDA_TOKEN and OANDA_ACCOUNT):
        return {'correlation':None,'reason':'XAUUSD spot OANDA hesabı bağlı değil','sample':0}
    try:
        future=closed_bars(await M.get_candles('XAUUSDT',tf,450),tf)
        spot=closed_bars(await M.get_candles('XAUUSD',tf,450),tf)
        f={x['t']:x['c'] for x in future};s={x['t']:x['c'] for x in spot}
        # Return correlation of synchronous log returns only; do not correlate price levels.
        times=sorted(set(f)&set(s))
        x=[];y=[]
        for p,q in zip(times,times[1:]):
            if q-p==TF_MIN[tf]*60 and min(f[p],f[q],s[p],s[q])>0:
                import math
                x.append(math.log(f[q]/f[p]));y.append(math.log(s[q]/s[p]))
        x=x[-120:];y=y[-120:]
        import statistics,math
        if len(x)<30:return {'correlation':None,'sample':len(x),'reason':'30 eşzamanlı getiri örneği bulunamadı'}
        sx=statistics.pstdev(x);sy=statistics.pstdev(y)
        if sx==0 or sy==0:return {'correlation':None,'sample':len(x),'reason':'Sabit seri'}
        mx=statistics.mean(x);my=statistics.mean(y)
        rho=sum((a-mx)*(b-my) for a,b in zip(x,y))/len(x)/sx/sy
        return {'correlation':round(rho,4),'sample':len(x),'tf':tf,'source':'Bitget / OANDA',
                'note':'Aynı zamanlı log getiriler Pearson korelasyonu, fiyat seviyesi korelasyonu değildir.'}
    except Exception as ex:return {'correlation':None,'reason':err_text(ex),'sample':0}

@app.get('/api/news')
async def news():
    # Public GDELT may throttle or return empty; never fabricate news.
    try:
        d=await M.get_json('https://api.gdeltproject.org/api/v2/doc/doc',
            {'query':'("gold price" OR "gold futures" OR XAUUSD) sourcelang:english',
             'mode':'artlist','maxrecords':12,'timespan':'24h','format':'json','sort':'datedesc'})
        items=[]
        for x in d.get('articles',[]):
            u=x.get('url','')
            if not u.startswith(('https://','http://')):continue
            items.append({'title':str(x.get('title',''))[:180], 'url':u,'domain':x.get('domain'),
                          'time':x.get('seendate'),'source':'GDELT'})
        return {'items':items,'source':'GDELT DOC 2.0','note':'Haber akışı gecikebilir; duygu puanı veya fiyat tahmini içermez.'}
    except Exception as ex:return {'items':[],'error':err_text(ex),'source':'GDELT DOC 2.0'}

# ============================================================
# ALTIN QUANT v2 SHADOW INTEGRATION
# Read-only sidecar. Legacy endpoints and their responses are unchanged.
# Set ALTIN_QUANT_ENABLED=0 in Render Environment for immediate rollback.
# ============================================================
from altin_quant import build_quant_report, WEIGHTS
from altin_risk import calculate_risk, POLICY

ALTIN_QUANT_ENABLED=os.getenv('ALTIN_QUANT_ENABLED','1').strip().lower() not in ('0','false','off')

@app.get('/api/altin-quant/health')
async def altin_quant_health():
    return {'version':'2.0.0','enabled':ALTIN_QUANT_ENABLED,'mode':'SHADOW_ONLY',
            'orders_enabled':False,'existing_v1_endpoints_unchanged':True,
            'weighted_families':WEIGHTS,'data_source':'Existing GOLD SCALP PRO Market cache'}

@app.get('/api/altin-quant/analysis')
async def altin_quant_analysis(symbol:str='XAUUSDT',tf:str='5m'):
    if not ALTIN_QUANT_ENABLED:
        raise HTTPException(503,'ALTIN QUANT kapalı. v1 API çalışmaya devam eder.')
    symbol=valid_symbol(symbol)
    tf=valid_tf(tf)
    # Legacy endpoint is used as-is; shadow extension never overwrites its decision.
    try:
        old=await analysis(symbol=symbol,tf=tf,refresh=False)
        old_decision=old.get('decision',{})
    except HTTPException:
        old_decision={'decision':'BEKLE','veto':['Mevcut analiz verisi alınamadı']}
    except Exception as ex:
        old_decision={'decision':'BEKLE','veto':[err_text(ex)]}

    errors={}
    async def one(f):
        try:
            b=await M.get_candles(symbol,f,450)
            return f,closed_bars(b,f)
        except Exception as ex:
            errors[f]=err_text(ex)
            return f,[]
    collected=dict(await asyncio.gather(*(one(f) for f in ('4H','1H','15m','5m','1m'))))
    s=M.snapshot()
    # Raw trades are internal only; never expose user credentials or gateway state.
    s['raw_trades']=[dict(t) for t in M.trades]
    result=await asyncio.to_thread(build_quant_report,symbol,collected,s,old_decision,nowms())
    result['data_errors']=errors
    result['data']={'bars_by_tf':{k:len(v) for k,v in collected.items()},
                    'feed_valid':s['valid'],'last_candle_source':old.get('data',{}).get('source') if 'old' in locals() else None}
    return result

@app.get('/api/altin-quant/risk-plan')
async def altin_quant_risk_plan(equity:float=Query(...,gt=0,le=10_000_000),
        daily_loss:float=Query(default=0,ge=0,le=10_000_000),
        weekly_loss:float=Query(default=0,ge=0,le=10_000_000),
        consecutive_losses:int=Query(default=0,ge=0,le=100),
        drawdown_pct:float=Query(default=0,ge=0,le=100),
        entry:float|None=Query(default=None,gt=0),
        stop:float|None=Query(default=None,gt=0),
        multiplier:float|None=Query(default=None,gt=0)):
    if not ALTIN_QUANT_ENABLED:raise HTTPException(503,'ALTIN QUANT kapalı')
    try:
        return calculate_risk(equity,daily_loss,weekly_loss,consecutive_losses,
                              drawdown_pct,entry,stop,multiplier)
    except ValueError as ex:raise HTTPException(400,str(ex))


# ============================================================
# GOLD v2.1 — OPTIONAL PUBLIC DATA AND STRATEGY RESEARCH
# New endpoints ONLY. Existing v1/v2 endpoints and UI remain intact.
# ============================================================
from gold_data_v21 import GoldData
from gold_strategy_v21 import improved_backtest

GOLD_V21_DATA = GoldData()

@app.get('/api/gold-v21/health')
async def gold_v21_health():
    return {'version':'2.1.0','mode':'SHADOW_ONLY','orders_enabled':False,
            'legacy_endpoints_unchanged':True,
            'modules':['contract_public','oi_history','funding_history','economic_calendar','risk_veto','journal','conservative_backtest'],
            'note':'Canlı veri uç noktaları ancak /report çağrısı ve gerçek kaynaktan yanıt sonrası doğrulanır.'}

@app.get('/api/gold-v21/report')
async def gold_v21_report(symbol:str='XAUUSDT',tf:str='5m'):
    if not ALTIN_QUANT_ENABLED:raise HTTPException(503,'ALTIN QUANT devre dışı')
    symbol=valid_symbol(symbol);tf=valid_tf(tf)
    if symbol!='XAUUSDT':
        return {'mode':'SHADOW_ONLY','symbol':symbol,'status':'unavailable',
                'reason':'Bitget sözleşme/OI/funding yalnız XAUUSDT içindir; XAUUSD spot verisinin yerine kullanılmaz'}
    base=await altin_quant_analysis(symbol=symbol,tf=tf)
    contract,deriv,calendar=await asyncio.gather(
        GOLD_V21_DATA.contracts(M),GOLD_V21_DATA.derivatives(M),GOLD_V21_DATA.calendar(M))
    veto=GOLD_V21_DATA.event_veto(calendar,nowms())
    market=M.snapshot()
    risk=GOLD_V21_DATA.risk_plan(base,contract,market,veto)
    try:
        closed5=closed_bars(await M.get_candles('XAUUSDT','5m',350),'5m')
        from gold_data_v21 import _good_number
        fees=contract.get('taker_fee_bps') if contract.get('status')=='ready' else None
        book_spread=(base.get('orderflow') or {}).get('spread_bps')
        scenarios=GOLD_V21_DATA.stop_take_scenarios(closed5,fees,book_spread)
    except Exception as ex:
        scenarios={'status':'unavailable','reason':err_text(ex)}
    score=base.get('score') or {}
    data_quality=base.get('timeframe_quality') or {}
    problems=[]
    if any(not market['valid'].get(k) for k in ('ticker','book','trades')):problems.append('Canlı fiyat/kitap/işlem eski')
    for k in ('1m','5m','15m','1H'):
        row=data_quality.get(k) or {}
        if not row.get('fresh') or row.get('gap_count_last_50'):problems.append(k+' mum eski veya boşluk var')
    if contract.get('status')!='ready':problems.append('Bitget sözleşme kuralları erişilemiyor')
    if deriv.get('status')!='ready':problems.append('OI/funding verisi eksik veya erişilemiyor')
    if not veto.get('allowed'):problems.append(veto['reason'])
    if score.get('veto'):problems.extend(score['veto'])
    # State is intentionally never a trading permission. No private account reads.
    journal=await asyncio.to_thread(GOLD_V21_DATA.save_sample,base)
    return {'version':'2.1.0','mode':'SHADOW_ONLY','orders_enabled':False,'symbol':symbol,
            'status':'VALIDATED_RESEARCH' if not problems else 'RESEARCH_WITH_VETO',
            'timestamp_ms':nowms(), 'baseline':{'legacy':base.get('legacy'),
                 'shadow_decision':score.get('final'),'long':score.get('long_points'),
                 'short':score.get('short_points'),'score_veto':score.get('veto')},
            'regime':base.get('regime'),'mtf':base.get('mtf'),
            'mtf_explanation':'Rejim 5m fiyat/volatilite sınıfıdır; ana MTF 4H/1H/15m yön onayıdır. Farklı sonuçlar çelişki değil farklı ufuktur.',
            'feed_valid':market['valid'],'candle_quality':data_quality,
            'instrument':contract,'derivatives':deriv,'calendar':calendar,
            'calendar_veto':veto,'risk_plan':risk,'stop_take_scenarios':scenarios,'all_veto':list(dict.fromkeys(problems)),
            'journal':journal,'data_note':'Eksik veri puana/sinyale dönüştürülmez; bu uç nokta eski kararı değiştirmez.'}

@app.get('/api/gold-v21/journal')
async def gold_v21_journal(limit:int=Query(default=100,ge=1,le=500)):
    return await asyncio.to_thread(GOLD_V21_DATA.journal,limit)

@app.get('/api/gold-v21/backtest')
async def gold_v21_backtest(symbol:str='XAUUSDT',tf:str='5m',strategy:str='ema_trend',
                     fee_bps:float=Query(default=4,ge=0,le=30),
                     slippage_bps:float=Query(default=1,ge=0,le=30),
                     spread_bps:float=Query(default=1,ge=0,le=30)):
    symbol=valid_symbol(symbol);tf=valid_tf(tf)
    if strategy not in STRATEGIES:raise HTTPException(400,'Bilinmeyen strateji')
    try:
        candles=closed_bars(await M.get_candles(symbol,tf,700),tf)
        # Both models run on exactly the same closed-candle sample, no historical
        # microstructure feed inferred from today's order book.
        old,new=await asyncio.gather(
            asyncio.to_thread(backtest,candles,strategy,fee_bps,slippage_bps),
            asyncio.to_thread(improved_backtest,candles,strategy,fee_bps,slippage_bps,spread_bps))
        return {'version':'2.1.0','symbol':symbol,'tf':tf,'legacy':old,'filtered':new,
                'comparability_note':'Eski test ve filtreli test aynı mumları kullanır. Yeni filtrede ek spread varsayımı vardır; ayrıca maliyetler eşitlenmeden doğrudan PnL farkını getiri artışı sayma.'}
    except Exception as ex:raise HTTPException(503,err_text(ex))


# QUANT HUB v3: seven independently isolated, read-only analysis adaptations.
# NO trade endpoints, NO original ML/library imports, NO mutation of v1/v2 decisions.
from fastapi import Body

@app.get('/api/quant-hub/catalog')
async def quant_hub_catalog():
    from gold_quant_hub import catalog
    return catalog()

@app.get('/api/quant-hub/health')
async def quant_hub_health():
    from gold_quant_hub import VERSION
    return {'version':VERSION,'mode':'SHADOW_ONLY','orders_enabled':False,
            'modules':7,'consensus':True,'legacy_unchanged':True}

# Quant Hub only: small, cached Bitget DAILY OHLC history audit. Never merges
# XAUUSD spot/OANDA candles into XAUUSDT Bitget futures history.
_QUANT_DAILY_CACHE = {}
_QUANT_DAILY_CACHE_SECONDS = 900
_QUANT_DAILY_MS = 86400000

async def quant_hub_daily_history(symbol):
    cached=_QUANT_DAILY_CACHE.get(symbol)
    if cached and time.time()-cached['at']<_QUANT_DAILY_CACHE_SECONDS:
        return cached['bars'],dict(cached['info'])
    recent=closed_bars(await M.get_candles(symbol,'1D',350),'1D')
    recent=sorted({int(x['t']):x for x in recent}.values(),key=lambda x:x['t'])
    info={'source':('Bitget USDT-FUTURES XAUUSDT 1D market OHLC' if symbol=='XAUUSDT'
                    else 'OANDA XAUUSD 1D spot-mid OHLC'),
          'recent_closed_days':len(recent),'history_attempted':False,
          'history_pages':0,'history_added':0,'history_error':None}
    if symbol=='XAUUSDT' and recent and len(recent)<105:
        # Bitget /api/v3/market/history-candles: <=100 per page; <=90d range.
        # At most two reads for modest free-tier impact; no synthetic backfill.
        all_bars={int(b['t']):b for b in recent}
        earliest=min(all_bars)
        info['history_attempted']=True
        for _ in range(2):
            end_ms=int(earliest*1000)-1
            start_ms=max(0,end_ms-89*_QUANT_DAILY_MS)
            params={'category':'USDT-FUTURES','symbol':'XAUUSDT',
                    'interval':'1D','type':'market','startTime':str(start_ms),
                    'endTime':str(end_ms),'limit':100}
            try:
                rows=await M.bitget('/api/v3/market/history-candles',params)
                info['history_pages']+=1
                added=0
                for d in rows if isinstance(rows,list) else []:
                    try:
                        t=int(d[0])//1000
                        bar={'t':t,'o':num(d[1]),'h':num(d[2]),'l':num(d[3]),'c':num(d[4]),'v':num(d[5])}
                        if (t>=earliest or t<start_ms//1000 or t>=(end_ms//1000)
                            or bar['o']<=0 or bar['c']<=0 or bar['l']>bar['h']
                            or not bar['l']<=bar['o']<=bar['h'] or not bar['l']<=bar['c']<=bar['h']):
                            continue
                        if t not in all_bars:all_bars[t]=bar;added+=1
                    except (ValueError,TypeError,IndexError):continue
                info['history_added']+=added
                if added==0:break
                earliest=min(all_bars)
                if len(all_bars)>=105:break
            except Exception as exc:
                info['history_error']=err_text(exc)
                break
        recent=sorted(all_bars.values(),key=lambda x:x['t'])
    if recent:
        info['first_utc']=datetime.fromtimestamp(recent[0]['t'],timezone.utc).date().isoformat()
        info['last_utc']=datetime.fromtimestamp(recent[-1]['t'],timezone.utc).date().isoformat()
        info['last_candle_age_days']=round((time.time()-(recent[-1]['t']+86400))/86400,2)
    info['available_closed_days']=len(recent)
    # The UI must distinguish genuine missing exchange history from a bad query.
    if symbol=='XAUUSDT' and len(recent)<100 and not info['history_error']:
        info['notice']='Aynı Bitget sembolünden 100 tam günlük mum bulunamadı; uzun-vade motorları bu veriyle çalışmaz.'
    if symbol=='XAUUSD' and len(recent)<100:
        info['notice']='OANDA XAUUSD spot günlük geçmişi yeterli değil; Bitget XAUUSDT verisiyle karıştırılmadı.'
    _QUANT_DAILY_CACHE[symbol]={'at':time.time(),'bars':recent,'info':dict(info)}
    return recent,info

@app.post('/api/quant-hub/analyze')
async def quant_hub_analyze(payload:dict=Body(default={})):
    from gold_quant_hub import analyze, config_for
    symbol=valid_symbol(str(payload.get('symbol','XAUUSDT')))
    tf=valid_tf(str(payload.get('tf','5m')))
    if tf not in ('1m','3m','5m','15m'):
        raise HTTPException(400,'Quant Hub: 1m, 3m, 5m veya 15m seçiniz')
    config=config_for(payload.get('config'))
    req={'5m':tf,'1H':'1H','1D':'1D'}
    result={};errors={};daily_info={}
    async def pull(slot,tf_name):
        try:
            if tf_name=='1D':
                bars,meta=await quant_hub_daily_history(symbol)
                daily_info.update(meta)
                result[slot]=bars
            else:
                bars=await M.get_candles(symbol,tf_name,600)
                result[slot]=closed_bars(bars,tf_name)
        except Exception as exc:
            errors[slot]=err_text(exc)
            result[slot]=[]
    await asyncio.gather(*(pull(k,v) for k,v in req.items()))
    snap=M.snapshot()
    valid=snap.get('valid') or {}
    if symbol=='XAUUSDT':
        price_fresh=bool(valid.get('ticker'))
    else:
        price_fresh=bool(snap.get('spot')) and (snap.get('spot_age_s') is not None and snap['spot_age_s']<25)
    key=('XAUUSDT' if symbol=='XAUUSDT' else 'XAUUSD',tf)
    timestamp=M.candle_updated.get(key)
    quality={'symbol':symbol,'ticker_fresh':price_fresh,'spot_configured':bool(OANDA_TOKEN and OANDA_ACCOUNT),
             'source':'Bitget public market OHLC' if symbol=='XAUUSDT' else 'OANDA authenticated spot OHLC',
             'candle_cache_age_seconds':age(timestamp),'base_tf_seconds':TF_MIN[tf]*60,'errors':errors,
             'daily':daily_info,'no_real_orders':True}
    # The expensive numerical calculations run off-event-loop.
    out=await asyncio.to_thread(analyze,result,symbol,config,quality)
    out['analysis_tf']=tf
    # QUANT AI (Asya–Londra): yalnız mevcut Soloshun paneline araştırma verisi.
    # Orijinal konsensüs, diğer altı motor ve gerçek emir yasağı değişmez.
    soloshun_mod = (out.get('modules') or {}).get('soloshun')
    if isinstance(soloshun_mod, dict):
        try:
            from gold_session_ai import session_ai_status
            soloshun_mod['quant_ai'] = await asyncio.to_thread(
                session_ai_status, result.get('1H') or [], symbol=symbol)
        except Exception as exc:
            soloshun_mod['quant_ai'] = {
                'mode':'ERROR', 'error':err_text(exc), 'orders_enabled':False,
                'model_loaded':False, 'prediction':None, 'probability':None}
    # GOLD ML v1: read-only inference on same-source H1; never changes 7-engine consensus.
    if isinstance(soloshun_mod, dict):
        try:
            from gold_ml_core import live_status
            ml_data = await asyncio.to_thread(live_status, result.get('1H') or [], symbol, ROOT)
            if not isinstance(soloshun_mod.get('quant_ai'), dict):
                soloshun_mod['quant_ai'] = {'mode': 'ERROR', 'orders_enabled': False}
            soloshun_mod['quant_ai']['ml'] = ml_data
        except Exception as ml_exc:
            if isinstance(soloshun_mod.get('quant_ai'), dict):
                soloshun_mod['quant_ai']['ml'] = {
                    'status':'ERROR', 'prediction':None, 'orders_enabled':False,
                    'reason':err_text(ml_exc)}
    # GOLD ML V3: standard-library comparison report, research only, no new signal.
    if isinstance(soloshun_mod, dict):
        try:
            from gold_ml_v3 import report_for_symbol
            if not isinstance(soloshun_mod.get('quant_ai'), dict):
                soloshun_mod['quant_ai']={'mode':'ERROR','orders_enabled':False}
            soloshun_mod['quant_ai']['compare']=await asyncio.to_thread(report_for_symbol,symbol,ROOT)
        except Exception as compare_exc:
            if isinstance(soloshun_mod.get('quant_ai'), dict):
                soloshun_mod['quant_ai']['compare']={'status':'ERROR','error':err_text(compare_exc),
                    'orders_enabled':False,'consensus_vote':False,'prediction':None}
    # GOLD SHADOW V5: read-only, cloud-generated independent prospective journal.
    # Never modifies existing Soloshun/Quant Hub voting or orders.
    if isinstance(soloshun_mod,dict):
        try:
            from gold_shadow_v5 import public_status
            if not isinstance(soloshun_mod.get('quant_ai'),dict):
                soloshun_mod['quant_ai']={'mode':'ERROR','orders_enabled':False}
            soloshun_mod['quant_ai']['shadow_v5']=await asyncio.to_thread(public_status,symbol,ROOT)
        except Exception as shadow_exc:
            if isinstance(soloshun_mod.get('quant_ai'),dict):
                soloshun_mod['quant_ai']['shadow_v5']={
                   'status':'ERROR','error':err_text(shadow_exc),'orders_enabled':False,
                   'consensus_vote':False,'live_trade_signal':False}
    # GOLD SCALP V6: read-only minute-scale research report. Zero trade actions.
    if isinstance(soloshun_mod,dict):
        try:
            from gold_scalp_v6_view import read_research
            if not isinstance(soloshun_mod.get('quant_ai'),dict):
                soloshun_mod['quant_ai']={'mode':'RESEARCH','orders_enabled':False}
            soloshun_mod['quant_ai']['scalp_v6']=await asyncio.to_thread(read_research,ROOT,symbol)
        except Exception as v6_exc:
            if isinstance(soloshun_mod.get('quant_ai'),dict):
                soloshun_mod['quant_ai']['scalp_v6']={'status':'ERROR','reason':err_text(v6_exc),
                    'live_signal':False,'trade_decision':'BEKLE','no_orders':True}
    out['requested_at_ms']=nowms()
    return out
