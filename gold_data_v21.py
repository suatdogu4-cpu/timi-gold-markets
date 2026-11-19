"""Optional, fail-closed public-data enrichment for GOLD SCALP PRO.
Public Bitget UTA v3 + publicly documented XOOMAR calendar. No trading.
All states marked as observed, stale, or unavailable; never fabricated.
"""
from __future__ import annotations
import asyncio
import math
import os
import sqlite3
import json
import time
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Any

from quant import num, safe

BITGET_CATEGORY='USDT-FUTURES'
CALENDAR_URL='https://xoomar.com/api/markets/calendar'
SOURCE_CALENDAR='https://xoomar.com/markets/api/calendar'
JOURNAL_PATH=os.getenv('GOLD_JOURNAL_PATH','/tmp/gold_shadow_journal_v21.sqlite3')


def ms():return int(time.time()*1000)


def _good_number(v):
    if v in ('',None):return None
    try:
        f=float(v)
        return f if math.isfinite(f) else None
    except (ValueError,TypeError):return None


def _one(data):
    if isinstance(data,list):return next((d for d in data if isinstance(d,dict) and d.get('symbol')=='XAUUSDT'),None)
    return data if isinstance(data,dict) else None


def _event_at(s):
    try:
        x=datetime.fromisoformat(str(s).replace('Z','+00:00'))
        if x.tzinfo is None:return None
        return int(x.timestamp()*1000)
    except (ValueError,TypeError):return None


class GoldData:
    def __init__(self):
        self.cache={};self.locks={}

    async def _cached(self,key,ttl,load):
        old=self.cache.get(key)
        if old and ms()-old['ts']<ttl*1000:return dict(old['data'])
        async with self.locks.setdefault(key,asyncio.Lock()):
            old=self.cache.get(key)
            if old and ms()-old['ts']<ttl*1000:return dict(old['data'])
            try:
                result=await load()
                result.setdefault('status','ready')
                result['retrieved_at_ms']=ms()
                self.cache[key]={'ts':ms(),'data':result}
                return dict(result)
            except Exception as e:
                return {'status':'unavailable','source':key,'error':f'{type(e).__name__}: {str(e)[:145]}',
                        'retrieved_at_ms':None,'stale_data_not_used':True}

    async def contracts(self,market):
        async def fetch():
            data=await market.bitget('/api/v3/market/instruments',{'category':BITGET_CATEGORY,'symbol':'XAUUSDT'})
            d=_one(data)
            if not d or d.get('symbol')!='XAUUSDT':raise ValueError('XAUUSDT enstrüman listesinde bulunamadı')
            maker=_good_number(d.get('makerFeeRate'));taker=_good_number(d.get('takerFeeRate'))
            return {'source':'Bitget UTA v3 /market/instruments','symbol':'XAUUSDT',
                    'market_status':d.get('status'), 'asset_type':d.get('symbolType'),
                    'base_coin':d.get('baseCoin'),'quote_coin':d.get('quoteCoin'),
                    'min_order_qty':_good_number(d.get('minOrderQty')),
                    'quantity_multiplier':_good_number(d.get('quantityMultiplier')),
                    'price_multiplier':_good_number(d.get('priceMultiplier')),
                    'min_order_amount':_good_number(d.get('minOrderAmount')),
                    'quantity_precision':int(d['quantityPrecision']) if str(d.get('quantityPrecision','')).isdigit() else None,
                    'price_precision':int(d['pricePrecision']) if str(d.get('pricePrecision','')).isdigit() else None,
                    'maker_fee_bps':safe(maker*10000,3) if maker is not None else None,
                    'taker_fee_bps':safe(taker*10000,3) if taker is not None else None,
                    'note':'UTA miktar birimi resmi belgeye göre base coin; genel bir ons/kontrat çarpanı varsayılmadı. Hesaba özel komisyon farklı olabilir.'}
        return await self._cached('contract',12*3600,fetch)

    async def derivatives(self,market):
        async def fetch():
            opts={'category':BITGET_CATEGORY,'symbol':'XAUUSDT'}
            oi,history,funding,f_history=await asyncio.gather(
                market.bitget('/api/v3/market/open-interest',opts),
                market.bitget('/api/v3/market/open-interest-history',{'symbol':'XAUUSDT','period':'5m'}),
                market.bitget('/api/v3/market/current-fund-rate',opts),
                market.bitget('/api/v3/market/history-fund-rate',{**opts,'limit':20}),
                return_exceptions=True)
            errors={}
            for name,val in [('oi',oi),('oi_history',history),('funding',funding),('funding_history',f_history)]:
                if isinstance(val,Exception):errors[name]=f'{type(val).__name__}: {str(val)[:120]}'
            out={'source':'Bitget UTA v3 public derivatives','errors':errors}
            if not isinstance(oi,Exception):
                obj=_one((oi or {}).get('list',[]) if isinstance(oi,dict) else oi)
                out['oi_now_base']=_good_number((obj or {}).get('openInterest'))
                out['oi_exchange_time_ms']=int(oi.get('ts')) if isinstance(oi,dict) and str(oi.get('ts','')).isdigit() else None
            if not isinstance(history,Exception):
                rows=(history or {}).get('list',[]) if isinstance(history,dict) else []
                pairs=[(int(x['timestamp']),float(x['openInterest'])) for x in rows if x.get('symbol')=='XAUUSDT'
                       and str(x.get('timestamp','')).isdigit() and _good_number(x.get('openInterest')) is not None]
                pairs.sort()
                out['oi_history_5m']=[{'ts':t,'oi_base':safe(v,6)} for t,v in pairs[-30:]]
                if len(pairs)>=2 and pairs[-2][1]>0 and pairs[-1][0]>pairs[-2][0]:
                    out['oi_change_5m_pct']=safe(100*(pairs[-1][1]/pairs[-2][1]-1),4)
                    out['oi_history_last_ms']=pairs[-1][0]
            if not isinstance(funding,Exception):
                obj=_one(funding)
                if obj:
                    out['funding_rate_pct']=safe(_good_number(obj.get('fundingRate'))*100,6) if _good_number(obj.get('fundingRate')) is not None else None
                    out['funding_interval_h']=_good_number(obj.get('fundingRateInterval'))
                    out['next_funding_at_ms']=int(obj['nextUpdate']) if str(obj.get('nextUpdate','')).isdigit() else None
            if not isinstance(f_history,Exception):
                rows=(f_history or {}).get('resultList',[]) if isinstance(f_history,dict) else []
                pairs=[(int(x['fundingRateTimestamp']),float(x['fundingRate'])) for x in rows
                       if x.get('symbol')=='XAUUSDT' and str(x.get('fundingRateTimestamp','')).isdigit()
                       and _good_number(x.get('fundingRate')) is not None]
                pairs.sort()
                out['funding_history']=[{'ts':t,'rate_pct':safe(v*100,6)} for t,v in pairs[-20:]]
            out['status']='ready' if out.get('oi_now_base') is not None and out.get('funding_rate_pct') is not None and len(out.get('oi_history_5m', []))>=2 and len(out.get('funding_history', []))>=1 and not errors else 'partial'
            out['note']='OI artışı long/satıcı yönünü ispatlamaz; funding bileşeni tek başına yön sinyali değildir.'
            return out
        return await self._cached('derivatives',120,fetch)

    async def calendar(self,market):
        async def fetch():
            now=datetime.now(timezone.utc)
            q={'from':(now-timedelta(days=1)).date().isoformat(),'to':(now+timedelta(days=8)).date().isoformat(),
               'importance':'high'}
            d=await market.get_json(CALENDAR_URL,q)
            if not isinstance(d,dict) or not isinstance(d.get('data'),list):raise ValueError('Takvim veri şeması beklenmedik')
            rows=[]
            for e in d['data']:
                when=_event_at(e.get('scheduledAt'))
                if when is None or e.get('importance')!='high':continue
                rows.append({'name':str(e.get('eventName',''))[:110],'scheduled_at_ms':when,'importance':'high',
                             'agency':e.get('source'),'actual':e.get('actual'),'forecast':None,
                             'source_url':SOURCE_CALENDAR})
            rows.sort(key=lambda x:x['scheduled_at_ms'])
            return {'source':'XOOMAR (BLS/BEA/Fed kaynak takvimi)','source_url':SOURCE_CALENDAR,
                    'updated_at':d.get('updatedAt'), 'events':rows[:80],
                    'note':'Ücretsiz üçüncü taraf takvim; tarih/saatler orijinal resmi ajanslardan toplanır, konsensüs beklenti verisi yok.'}
        return await self._cached('calendar',1800,fetch)

    @staticmethod
    def event_veto(calendar,now_ms):
        if calendar.get('status')!='ready':return {'allowed':False,'reason':'Ekonomik takvim doğrulanamadı; haber veto açıktır','event':None}
        # High impact: 20 minutes before, 10 minutes after. Fixed preventive policy, not optimized.
        for e in calendar.get('events',[]):
            delta=now_ms-e['scheduled_at_ms']
            if -20*60_000 <= delta <= 10*60_000:
                return {'allowed':False,'reason':'Yüksek etkili ABD verisi yakın/henüz açıklandı', 'event':e}
        return {'allowed':True,'reason':'Yakın yüksek etkili etkinlik yok (kaynak kapsamıyla sınırlı)','event':None}

    @staticmethod
    def risk_plan(shadow,contract,market_snapshot,event_veto,equity=1000.,risk_percent=.25):
        # Research-only hypothetical sizing. No real account state, leverage or liquidation protection.
        setup=shadow.get('setup') or {}
        price=_good_number(setup.get('entry_ref'));stop=_good_number(setup.get('stop'))
        take=_good_number(setup.get('take_profit'))
        spread= _good_number(setup.get('spread_bps'))
        candidate=(shadow.get('score') or {}).get('theoretical','')
        feed=market_snapshot.get('valid') or {}
        veto=[]
        if contract.get('status')!='ready':veto.append('Bitget sözleşme bilgisi yok')
        if contract.get('market_status')!='online':veto.append('Bitget sözleşmesi online doğrulanmadı')
        if not event_veto.get('allowed'):veto.append(event_veto.get('reason'))
        if not all(feed.get(k) for k in ('ticker','book','trades')):veto.append('Canlı piyasa akışı eksik')
        if candidate not in ('LONG ADAYI','SHORT ADAYI') or (shadow.get('score') or {}).get('final') not in ('LONG ADAYI','SHORT ADAYI'):
            veto.append('ALTIN QUANT güvenlik vetosu / yönsel aday oluşmadı')
        if not all(x is not None and x>0 for x in (price,stop,take)):veto.append('Stop/hedef doğrulanamadı')
        if spread is None or spread>10:veto.append('Spread ölçülemedi veya geniş')
        fee=contract.get('taker_fee_bps');assumed_slippage_bps=2.0
        if fee is None:veto.append('Taker komisyonu borsadan alınamadı')
        if veto:return {'status':'BLOCKED','veto':veto,'hypothetical':True,'orders_enabled':False}
        direction=1 if candidate=='LONG ADAYI' else -1
        if direction*(price-stop)<=0 or direction*(take-price)<=0:
            return {'status':'BLOCKED','veto':['Stop/hedef yönü ters'],'hypothetical':True,'orders_enabled':False}
        risk_per_base=abs(price-stop)+(price*(2*fee+2*assumed_slippage_bps+spread)/1e4)
        reward_per_base=abs(take-price)-(price*(2*fee+2*assumed_slippage_bps+spread)/1e4)
        if reward_per_base <= 0:return {'status':'BLOCKED','veto':['Maliyet sonrası hedef negatif'],'hypothetical':True,'orders_enabled':False}
        max_risk=equity*risk_percent/100
        size=max_risk/risk_per_base
        minq=contract.get('min_order_qty')
        if not minq or size<minq:return {'status':'BLOCKED','veto':['Minimum borsa miktarı risk bütçesini aşıyor'],'hypothetical':True,'orders_enabled':False}
        # Do NOT round into fake precision/step: minimum steps/contract semantics must be verified live.
        return {'status':'RESEARCH_ONLY','hypothetical':True,'orders_enabled':False,'equity_ref':equity,
                'risk_budget_ref':safe(max_risk,3),'raw_base_qty_unrounded':safe(size,8),
                'reward_to_risk_net':safe(reward_per_base/risk_per_base,3),
                'taker_fee_bps':fee,'assumed_slippage_bps_per_side':assumed_slippage_bps,
                'note':'Örnek varsayım: özsermaye 1000 USDT, risk %0.25, kayma 2 bps/yön. Emir gönderilemez; hesap/likidasyon/marjin bilgisi yok.'}

    @staticmethod
    def stop_take_scenarios(closed_bars, fee_bps=None, spread_bps=None, slippage_bps=2.):
        """Two-sided, entirely hypothetical *closed 5-minute bar* study.
        Does not infer liquidity or an executable price from broker-unavailable data.
        """
        from quant import indicators
        if len(closed_bars)<40:return {'status':'unavailable','reason':'40 kapalı 5m mum gerekli'}
        ix=indicators(closed_bars)['latest']
        entry=_good_number(closed_bars[-1]['c']);atr=_good_number(ix.get('atr14'))
        if not entry or not atr or atr<=0:return {'status':'unavailable','reason':'ATR/fiyat ölçülemedi'}
        lows=[float(x['l']) for x in closed_bars[-13:-1]]
        highs=[float(x['h']) for x in closed_bars[-13:-1]]
        if not lows or not highs:return {'status':'unavailable','reason':'Önceki yapı seviyeleri yok'}
        scenarios=[]
        for side in (1,-1):
            stop=min(min(lows),entry-1.5*atr) if side==1 else max(max(highs),entry+1.5*atr)
            take=entry+side*2.25*atr
            stopdist=abs(entry-stop)
            gross_reward=abs(take-entry)
            total_cost_bps=(2*(fee_bps+slippage_bps)+spread_bps) if fee_bps is not None and spread_bps is not None else None
            cost=entry*total_cost_bps/10000 if total_cost_bps is not None else None
            net_rr=(gross_reward-cost)/(stopdist+cost) if cost is not None else None
            scenarios.append({'direction':'LONG' if side>0 else 'SHORT','entry_ref':safe(entry),
                              'stop_ref':safe(stop),'target_ref':safe(take),
                              'gross_risk_ref':safe(stopdist,4),'gross_reward_ref':safe(gross_reward,4),
                              'net_rr_estimate':safe(net_rr,3) if net_rr is not None else None,
                              'roundtrip_cost_bps':safe(total_cost_bps,3) if total_cost_bps is not None else None})
        return {'status':'illustrative','source':'Bitget XAUUSDT kapanmış 5m mumlar',
                'last_closed_time':closed_bars[-1]['t'],'atr14':safe(atr,5),
                'scenarios':scenarios,'note':'LONG ve SHORT ayrı senaryo, gerçek giriş veya onay değil. Stop önceki 12 mum ve 1.5 ATR ile, hedef 2.25 ATR ile belirlendi.'}

    @staticmethod
    def save_sample(report, path=JOURNAL_PATH):
        """Idempotent ~5-minute sampled decision journal, not trade fills.
        Render ephemeral disk resets can delete it. Set GOLD_JOURNAL_PATH to mounted disk.
        """
        record={'time_ms':ms(),'mode':report.get('mode'),
                'decision':(report.get('score') or {}).get('final'),
                'long':(report.get('score') or {}).get('long_points'),
                'short':(report.get('score') or {}).get('short_points'),
                'regime':(report.get('regime') or {}).get('code'),
                'veto':(report.get('score') or {}).get('veto') or []}
        key=record['time_ms']//300000
        try:
            Path(path).parent.mkdir(parents=True,exist_ok=True)
            with sqlite3.connect(path,timeout=2) as conn:
                conn.execute('CREATE TABLE IF NOT EXISTS samples (bucket INTEGER PRIMARY KEY, ts INTEGER NOT NULL, content TEXT NOT NULL)')
                conn.execute('INSERT OR IGNORE INTO samples(bucket,ts,content) VALUES(?,?,?)',(key,record['time_ms'],json.dumps(record,ensure_ascii=False)))
                conn.execute('DELETE FROM samples WHERE bucket < ?', (key-12000,))
            return {'stored':True,'path_persistent':os.getenv('GOLD_JOURNAL_PATH') is not None}
        except (OSError,sqlite3.Error) as ex:
            return {'stored':False,'error':type(ex).__name__}

    @staticmethod
    def journal(limit=100,path=JOURNAL_PATH):
        try:
            with sqlite3.connect(path,timeout=2) as conn:
                rows=conn.execute('SELECT content FROM samples ORDER BY bucket DESC LIMIT ?', (min(500,max(1,int(limit))),)).fetchall()
            return {'status':'ready','items':[json.loads(r[0]) for r in rows],
                    'storage':'ephemeral' if not os.getenv('GOLD_JOURNAL_PATH') else 'configured_path',
                    'note':'Karar örnekleri, işlem gerçekleşmeleri değildir. Render diski kalıcı değilse kayıtlar sıfırlanır.'}
        except (OSError,sqlite3.Error):return {'status':'empty','items':[],'note':'Henüz kayıt yok'}
