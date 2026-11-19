"""GOLD QUANT HUB — independent, research-only adaptations of seven published ideas.

Does NOT bundle upstream projects or claim to execute GS Quant, NautilusTrader,
Riskfolio-Lib, XGBoost, LightGBM, or original pretrained models.
No user credentials or order placement. Only closed, source-tagged candles.
"""
from __future__ import annotations

import math
import statistics
from collections import defaultdict
from datetime import datetime, timezone
from typing import Any

from quant import indicators

VERSION = "3.0.0"
SOURCES = {
    'soloshun': ('Soloshun', 'https://github.com/soloshun/Quantitative-XAUUSD-Strategy', 'Seans hipotezi uyarlaması', 'DIRECTION'),
    'quantalytics': ('Quantalytics-26', 'https://github.com/abhishukla0204/Quantalytics-26', 'Hibrit momentum / dönüş uyarlaması', 'DIRECTION'),
    'joshua': ('Gold Prediction', 'https://github.com/Joshua-Leow/gold_prediction', 'Bağımsız temel ML sınıflandırıcısı', 'DIRECTION'),
    'mcm': ('MCM 2022', 'https://github.com/Junxiao-Liao/MCM2022-Trading-Strategies-for-Gold-and-Bitcoin', 'Sadece altın günlük tahsis uyarlaması', 'CONTEXT'),
    'gsquant': ('GS Quant', 'https://github.com/goldmansachs/gs-quant', 'Bağımsız VaR / ES risk hesabı', 'RISK'),
    'nautilus': ('NautilusTrader', 'https://github.com/nautechsystems/nautilus_trader', 'Olay sıralı mum simülasyonu', 'EXECUTION'),
    'riskfolio': ('Riskfolio-Lib', 'https://github.com/dcajasn/Riskfolio-Lib', 'Basit altın / nakit CVaR taraması', 'ALLOCATION'),
}
DEFAULTS = {
 'soloshun': {'min_pairs':12,'min_abs_corr':0.25,'session_shift_utc':0},
 'quantalytics': {'rsi_low':33,'rsi_high':67,'min_adx':12,'min_votes':2},
 'joshua': {'horizon':3,'signal_threshold':0.60,'min_test_lift':0.02},
 'mcm': {'momentum_days':20,'max_gold_pct':60},
 'gsquant': {'tail_pct':5,'es_limit_pct':0.9,'max_vol_pct':2.2},
 'nautilus': {'fee_bps':4,'slippage_bps':1,'spread_bps':1,'max_hold_bars':12,'min_sample_trades':12},
 'riskfolio': {'risk_penalty':3,'gold_cap_pct':80,'tail_pct':5},
 'consensus': {'min_directional':2,'min_agreement_pct':70,'min_margin_pts':25}
}
PARAM_RULES = {
 'soloshun': {'min_pairs':(8,80,1),'min_abs_corr':(0.05,0.9,0.05),'session_shift_utc':(-5,5,1)},
 'quantalytics': {'rsi_low':(15,45,1),'rsi_high':(55,85,1),'min_adx':(8,40,1),'min_votes':(2,5,1)},
 'joshua': {'horizon':(1,8,1),'signal_threshold':(0.52,0.85,.01),'min_test_lift':(0,0.25,.01)},
 'mcm': {'momentum_days':(5,60,1),'max_gold_pct':(0,100,5)},
 'gsquant': {'tail_pct':(1,10,1),'es_limit_pct':(.05,5,.05),'max_vol_pct':(.2,10,.1)},
 'nautilus': {'fee_bps':(0,30,.5),'slippage_bps':(0,30,.5),'spread_bps':(0,30,.5),'max_hold_bars':(3,50,1),'min_sample_trades':(5,50,1)},
 'riskfolio': {'risk_penalty':(.1,15,.1),'gold_cap_pct':(0,100,5),'tail_pct':(1,10,1)},
 'consensus': {'min_directional':(2,3,1),'min_agreement_pct':(55,95,5),'min_margin_pts':(5,75,5)}
}
DIRECTIONAL = {'soloshun': .23, 'quantalytics': .42, 'joshua': .35}

def finite(x):
    try:
        f=float(x)
        return f if math.isfinite(f) else None
    except (ValueError,TypeError,OverflowError): return None

def round_or_none(x,n=4):
    v=finite(x)
    return round(v,n) if v is not None else None

def clamp(x,lo,hi):return max(lo,min(hi,x))

def config_for(input_config=None):
    input_config=input_config if isinstance(input_config,dict) else {}
    out={}
    for engine,params in DEFAULTS.items():
        user=input_config.get(engine,{})
        user=user if isinstance(user,dict) else {}
        out[engine]={}
        for key,default in params.items():
            v=finite(user.get(key,default))
            lo,hi,step=PARAM_RULES[engine][key]
            v=clamp(v if v is not None else default,lo,hi)
            out[engine][key]=int(round(v)) if isinstance(default,int) else round(v,5)
    return out

def base_result(key,status='unavailable',reasons=None):
    name,url,desc,kind=SOURCES[key]
    return {'id':key,'name':name,'url':url,'kind':kind,'implementation':desc,
            'execution':'ORIGINAL ADAPTATION, not upstream library',
            'status':status,'direction':'BEKLE','strength':None,'eligible':False,
            'metrics':{},'reasons':reasons or [],'warnings':[], 'gate':'UNKNOWN'}

def good_bars(bars,minimum=55):
    if not isinstance(bars,list) or len(bars)<minimum:return False
    return all(isinstance(x,dict) and all(finite(x.get(k)) is not None for k in ('t','o','h','l','c')) and finite(x.get('c'))>0 for x in bars[-minimum:])

def pct_returns(bars):
    close=[finite(b.get('c')) for b in bars]
    return [math.log(y/x) for x,y in zip(close,close[1:]) if x and y and x>0 and y>0]

def tail_stats(ret,tail_pct=5):
    if len(ret)<40:return None
    losses=sorted([max(0.0,-x*100) for x in ret],reverse=True)
    k=max(1,int(math.ceil(len(losses)*tail_pct/100)))
    return {'var_pct':round_or_none(losses[k-1],5),'es_pct':round_or_none(statistics.mean(losses[:k]),5),
            'vol_pct':round_or_none(statistics.pstdev(ret)*100,5),'sample':len(ret)}

def signal_out(key,side,strength,reasons,metrics=None,status='ready',eligible=True,warnings=None):
    o=base_result(key,status,reasons)
    o['direction']=side if side in ('LONG','SHORT') else 'BEKLE'
    o['strength']=round_or_none(strength,1)
    o['eligible']=bool(eligible and side in ('LONG','SHORT'))
    o['metrics']=metrics or {}
    o['warnings']=warnings or []
    return o

def soloshun_engine(bars,cfg):
    out=base_result('soloshun',reasons=['En az 18 gün H1 kapanmış mum gerekli'])
    if not good_bars(bars,18*20):return out
    # Fixed UTC sessions, not DST-adjusted exchange sessions; compare the completed
    # Asia return of day D only against D's subsequently completed London return.
    by_day=defaultdict(list);shift=cfg['session_shift_utc']
    for b in bars:
        d=datetime.fromtimestamp(b['t']-shift*3600,timezone.utc)
        by_day[d.date().isoformat()].append((d.hour,b))
    obs=[];most_recent=None;last_day=max(by_day) if by_day else None
    for day,rows in sorted(by_day.items()):
        rows=sorted(rows,key=lambda x:x[0]);asia=[b for h,b in rows if 0<=h<8];london=[b for h,b in rows if 8<=h<13]
        if len(asia)>=8:
            a_return=math.log(asia[-1]['c']/asia[0]['o'])
            if day==last_day:most_recent=a_return
            if len(london)>=5 and day!=last_day:
                l_return=math.log(london[-1]['c']/london[0]['o'])
                obs.append((a_return,l_return))
    if len(obs)<cfg['min_pairs']:
        out['reasons']=[f"Yeterli tamamlanmış Asya→Londra çifti yok ({len(obs)}/{cfg['min_pairs']})"]
        return out
    a=[x for x,y in obs];b=[y for x,y in obs]
    if statistics.pstdev(a)<1e-12 or statistics.pstdev(b)<1e-12:
        out['reasons']=['Seans değişkenliği korelasyona uygun değil'];return out
    corr=statistics.correlation(a,b)
    out['metrics']={'completed_pairs':len(obs),'asia_london_corr':round_or_none(corr,3),
                    'last_asia_return_pct':round_or_none((most_recent or 0)*100,4),'session_timezone':'Sabit UTC, DST uygulanmaz'}
    if most_recent is None or abs(corr)<cfg['min_abs_corr']:
        out['status']='research';out['reasons']=['Güncel Asya oturumu henüz tamamlanmadı veya geçmiş seans bağlantısı zayıf'];return out
    direction='LONG' if corr*most_recent>0 else 'SHORT'
    strength=clamp(35+abs(corr)*42,0,75)
    return signal_out('soloshun',direction,strength,
            [f'Geçmiş Asya–Londra korelasyon adayı {corr:+.2f}',
             'XAUUSDT seans vekili, Soloshun XGBoost/LSTM modeli değil'],out['metrics'],warnings=['Korelasyon kestirimi ileri dönem başarısı kanıtı değildir'])

def quantalytics_engine(bars,cfg):
    out=base_result('quantalytics',reasons=['En az 220 kapalı mum gerekli'])
    if not good_bars(bars,220):return out
    ix=indicators(bars)['latest'];c=bars[-1]['c'];r=finite(ix.get('rsi14'));m=finite(ix.get('macd_hist'))
    ema20=finite(ix.get('ema20'));ema50=finite(ix.get('ema50'));adx=finite(ix.get('adx14'))
    atr=finite(ix.get('atr14'));up=finite(ix.get('bb_up'));low=finite(ix.get('bb_low'))
    if None in (r,m,ema20,ema50,adx,atr,up,low):return out
    bullish=int(ema20>ema50)+int(m>0)+int(c>ema20)+int(r<cfg['rsi_low'] or c<=low)
    bearish=int(ema20<ema50)+int(m<0)+int(c<ema20)+int(r>cfg['rsi_high'] or c>=up)
    v=max(bullish,bearish);side='LONG' if bullish>bearish else 'SHORT' if bearish>bullish else 'BEKLE'
    metrics={'rsi14':round_or_none(r,2),'adx14':round_or_none(adx,2),'macd_hist':round_or_none(m,4),
             'bullish_conditions':bullish,'bearish_conditions':bearish,'atr14':round_or_none(atr,3)}
    if v<cfg['min_votes'] or adx<cfg['min_adx'] or side=='BEKLE':
        out['status']='research';out['reasons']=['Trend/volatilite veya koşul sayısı yeterli değil'];out['metrics']=metrics;return out
    strength=clamp(35+v*12+(adx-15)*.25,0,85)
    return signal_out('quantalytics',side,strength,
                      ['Momentum + dönüş + trend koşulları (bağımsız sadeleştirilmiş hibrit model)',
                       'Sözleşmeye özel giriş ve maliyet doğrulaması ayrıca gereklidir'],metrics)

def _features(bars):
    # Cheap leak-free features (nothing from bar i+1). Train only on past labels.
    ret=[];c=[x['c'] for x in bars]
    for i in range(24,len(bars)):
        window=c[i-19:i+1]
        mean=statistics.mean(window);sd=statistics.pstdev(window)
        r1=math.log(c[i]/c[i-1]);r3=math.log(c[i]/c[i-3]);r8=math.log(c[i]/c[i-8])
        vol=statistics.pstdev(math.log(c[j]/c[j-1]) for j in range(i-10,i+1)) if False else 0
        ret.append((i,[r1*100,r3*100,r8*100,(c[i]/mean-1)*100,(sd/mean)*100,(c[i]/c[i-20]-1)*100]))
    return ret

def _fit_logit(data,labels):
    x=[a for i,a in data];n=len(x);d=len(x[0])
    means=[statistics.mean(r[j] for r in x) for j in range(d)]
    stds=[max(1e-6,statistics.pstdev(r[j] for r in x)) for j in range(d)]
    norm=[[clamp((row[j]-means[j])/stds[j],-5,5) for j in range(d)] for row in x]
    w=[0.0]*(d+1)
    for epoch in range(100):
        grad=[0.0]*(d+1)
        for row,y in zip(norm,labels):
            z=clamp(w[0]+sum(a*b for a,b in zip(w[1:],row)),-20,20)
            delta=1/(1+math.exp(-z))-y
            grad[0]+=delta
            for j in range(d):grad[j+1]+=delta*row[j]
        lr=.48/(n*(1+epoch*.015))
        w[0]-=lr*grad[0]
        for j in range(d):w[j+1]-=lr*(grad[j+1]+0.06*n*w[j+1])
    def pred(row):
        z=clamp(w[0]+sum(w[j+1]*clamp((row[j]-means[j])/stds[j],-5,5) for j in range(d)),-20,20)
        return 1/(1+math.exp(-z))
    return pred

def joshua_engine(bars,cfg):
    out=base_result('joshua',reasons=['En az 240 kapalı mum gerekli'])
    if not good_bars(bars,240):return out
    rows=_features(bars);h=cfg['horizon'];max_label=len(bars)-h
    train_limit=int(max_label*.7)
    train=[(i,x) for i,x in rows if i+h<train_limit]
    test=[(i,x) for i,x in rows if train_limit<=i and i+h<len(bars)]
    if len(train)<100 or len(test)<45:return out
    y=[int(bars[i+h]['c']>bars[i]['c']) for i,x in train]
    if len(set(y))<2:return out
    model=_fit_logit(train,y)
    yh=[int(bars[i+h]['c']>bars[i]['c']) for i,x in test]
    pred=[model(x) for i,x in test]
    acc=sum(int((p>=.5)==bool(v)) for p,v in zip(pred,yh))/len(yh)
    majority=max(sum(yh)/len(yh),1-sum(yh)/len(yh))
    recent_prob=model(rows[-1][1])
    metrics={'forward_samples':len(test),'forward_accuracy_pct':round_or_none(acc*100,1),
            'majority_baseline_pct':round_or_none(majority*100,1),
            'raw_class_score_pct':round_or_none(recent_prob*100,1),'horizon_bars':h,
            'model':'Yerel L2 lojistik sınıflandırıcı; orijinal Joshua RF/XGBoost/LightGBM değildir'}
    out['metrics']=metrics
    if acc<majority+cfg['min_test_lift']:
        out['status']='research';out['reasons']=['İleri örnek isabeti çoğunluk taban çizgisini yeterince aşmadı; oy dışı'];return out
    if max(recent_prob,1-recent_prob)<cfg['signal_threshold']:
        out['status']='research';out['reasons']=['Ham sınıflandırma çıktısı eşik altında, oy dışı'];return out
    return signal_out('joshua','LONG' if recent_prob>=.5 else 'SHORT',clamp(50+abs(recent_prob-.5)*75,0,85),
                     ['Kronolojik %70 eğitim / %30 test; ileri etiketler eğitime sızdırılmadı',
                      'Ham çıktı kalibre edilmiş kazanma olasılığı değildir'],metrics,warnings=['Yalnız temel model; upstream eğitilmiş modeller yüklü değil'])

def mcm_engine(bars,cfg):
    out=base_result('mcm',reasons=['En az 100 günlük kapanmış mum gerekli'])
    if not good_bars(bars,100):return out
    days=cfg['momentum_days'];close=[b['c'] for b in bars]
    momentum=(close[-1]/close[-days-1]-1)*100
    rets=pct_returns(bars);risk=tail_stats(rets)
    if not risk:return out
    suggested=cfg['max_gold_pct'] if momentum>1 else cfg['max_gold_pct']*.5 if momentum>0 else 0
    out.update(status='research',direction='LONG' if momentum>0.4 else 'SHORT' if momentum<-.4 else 'BEKLE',
               strength=round_or_none(clamp(abs(momentum)*12+25,0,75),1),
               metrics={'daily_momentum_pct':round_or_none(momentum,3),
               'illustrative_cash_pct':round(100-suggested,1),'illustrative_gold_pct':round(suggested,1),
               'daily_var_pct':risk['var_pct'],'daily_es_pct':risk['es_pct']},
               reasons=['MCM günlük altın+Bitcoin modelinden yalnız altın/nakit araştırma uyarlaması',
                        'XAUUSDT vadeli pozisyon ile altın/nakit portföy aynı ürün değildir'],
               warnings=['Scalping yön oylamasında kullanılmaz'])
    return out

def gs_engine(bars,cfg):
    out=base_result('gsquant',reasons=['Risk hesabı için yeterli kapalı mum yok'])
    if not good_bars(bars,80):return out
    ret=pct_returns(bars);risk=tail_stats(ret,cfg['tail_pct'])
    if not risk:return out
    gate=bool(risk['es_pct'] is not None and risk['es_pct']<=cfg['es_limit_pct'] and risk['vol_pct']<=cfg['max_vol_pct'])
    out.update(status='ready',metrics={**risk,'tail_pct':cfg['tail_pct'],'es_limit_pct':cfg['es_limit_pct'],
              'max_vol_pct':cfg['max_vol_pct']},gate='PASS' if gate else 'BLOCK',
              reasons=['Tarihsel tek-bar kayıp kuyruğu; GS Quant veya Marquee API çağrısı yapılmadı',
                       'Risk eşiği geçti' if gate else 'ES/volatilite eşiği aşıldı'])
    return out

def naut_engine(bars,cfg):
    out=base_result('nautilus',reasons=['Olay tabanlı simülasyon için en az 260 kapalı mum gerekli'])
    if not good_bars(bars,260):return out
    raw=indicators(bars)['_raw'];c=bars;trades=[];fee=cfg['fee_bps'];slip=(cfg['slippage_bps']+cfg['spread_bps']/2)/10000
    costbps=2*(fee+cfg['slippage_bps'])+cfg['spread_bps'];maxhold=cfg['max_hold_bars'];i=205
    while i<len(c)-2:
        p=raw['ema20'][i];q=raw['ema50'][i];pp=raw['ema20'][i-1];qq=raw['ema50'][i-1];atr=raw['atr14'][i]
        if None in (p,q,pp,qq,atr) or atr<=0:i+=1;continue
        side=1 if pp<=qq and p>q else -1 if pp>=qq and p<q else 0
        if not side:i+=1;continue
        entry=c[i+1]['o']*(1+side*slip);stop=entry-side*1.5*atr;take=entry+side*2.25*atr
        j_end=min(i+1+maxhold,len(c)-1);j=i+1;exit=c[j_end]['c']
        for j in range(i+1,j_end+1):
            b=c[j];o=b['o'];lo=b['l'];hi=b['h']
            if side==1:
                if o<=stop:exit=o;break
                if lo<=stop:exit=stop;break
                if o>=take:exit=take;break
                if hi>=take:exit=take;break
            else:
                if o>=stop:exit=o;break
                if hi>=stop:exit=stop;break
                if o<=take:exit=take;break
                if lo<=take:exit=take;break
            exit=b['c']
        exitfill=exit*(1-side*slip)
        pnl=side*(exitfill-entry)-(abs(entry)+abs(exitfill))*fee/10000
        trades.append((i,pnl))
        i=j+1
    # Forward performance is a diagnostic, not a fitted signal or backtest promise.
    split=int(len(c)*.7);forward=[v for ix,v in trades if ix>=split]
    wins=sum(v for ix,v in trades if v>0);loss=-sum(v for ix,v in trades if v<0)
    pf=wins/loss if loss>0 else (None if not wins else None)
    latest_atr=raw['atr14'][-1];last=c[-1]['c']
    cost_atr=(last*costbps/10000/latest_atr) if latest_atr else math.inf
    gate=cost_atr<=.8
    # Only block from sample if there is a nontrivial independent forward sample.
    if len(forward)>=cfg['min_sample_trades'] and statistics.mean(forward)<0:gate=False
    out.update(status='ready',gate='PASS' if gate else 'BLOCK',metrics={
       'trades':len(trades),'forward_trades':len(forward),'profit_factor':round_or_none(pf,3),
       'pnl_ref':round_or_none(sum(v for i,v in trades),3), 'roundtrip_cost_bps':costbps,
       'cost_to_atr_ratio':round_or_none(cost_atr,3),'forward_avg_pnl_ref':round_or_none(statistics.mean(forward),4) if forward else None},
       reasons=['Kapalı mum → sonraki açılış; stop öncelikli mum simülasyonu',
                'NautilusTrader Rust motoru ve gerçek borsa dolumları kullanılmadı'],
       warnings=['Mum içi sıra bilinmez; canlı emir, komisyon hesabı ve order book replay yok'])
    return out

def riskfolio_engine(bars,cfg):
    out=base_result('riskfolio',reasons=['Altın/nakit optimizasyonu için en az 80 günlük kapanmış mum gerekli'])
    if not good_bars(bars,80):return out
    ret=pct_returns(bars);risk=tail_stats(ret,cfg['tail_pct'])
    if not risk:return out
    mu=statistics.mean(ret)*.25  # shrink noisy expected return toward zero
    options=[]
    for i in range(0,21):
        w=min(cfg['gold_cap_pct']/100,i/20)
        loss=sorted([max(0.0,-w*r) for r in ret],reverse=True)
        k=max(1,math.ceil(len(loss)*cfg['tail_pct']/100))
        es=statistics.mean(loss[:k]);obj=w*mu-cfg['risk_penalty']*es
        options.append((obj,w,es))
    _,w,es=max(options,key=lambda x:x[0])
    out.update(status='research',metrics={'illustrative_gold_pct':round(w*100,1),'cash_pct':round((1-w)*100,1),
                 'optimized_tail_loss_pct':round_or_none(es*100,4),'expected_daily_pct_shrunk':round_or_none(mu*100,4),
                 'daily_samples':len(ret)},
                 reasons=['Nakit + altın için küçük ayrık CVaR taraması; Riskfolio-Lib/CVXPY çözücüsü kullanılmadı',
                          'Tahsis önerisi vadeli XAUUSDT emir büyüklüğü değildir'],
                 warnings=['Portföy alokasyonu LONG/SHORT yön oyu olarak sayılmaz'])
    return out

def consensus(modules,cfg,data_quality=None):
    options=[];missing=[]
    for key,wt in DIRECTIONAL.items():
        m=modules[key]
        if m['eligible'] and m['strength'] is not None:
            options.append((key,m['direction'],m['strength'],wt))
        else: missing.append(key)
    total=sum(wt for _,_,_,wt in options)
    points_long=sum(strength*wt for _,d,strength,wt in options if d=='LONG')/total if total else 0
    points_short=sum(strength*wt for _,d,strength,wt in options if d=='SHORT')/total if total else 0
    active_weight=total/sum(DIRECTIONAL.values()) if DIRECTIONAL else 0
    votes_l=sum(d=='LONG' for _,d,s,w in options);votes_s=sum(d=='SHORT' for _,d,s,w in options)
    agreement=100*max(votes_l,votes_s)/len(options) if options else 0
    quality=data_quality or {}
    blocks=[]
    if len(options)<cfg['min_directional']:blocks.append('Yeterli bağımsız yön tahmini yok')
    if agreement<cfg['min_agreement_pct']:blocks.append('Yön motorları yeterince uzlaşmıyor')
    if abs(points_long-points_short)<cfg['min_margin_pts']:blocks.append('Yönsel fark eşiği altında')
    if modules['gsquant']['gate']!='PASS':blocks.append('GS-tipi risk denetimi belirsiz veya veto')
    if modules['nautilus']['gate']!='PASS':blocks.append('İşlem maliyeti / olay testi vetosu')
    if not quality.get('candles_ok'):blocks.append('Güncel kapalı mum örneklemi yetersiz')
    if not quality.get('ticker_fresh'):blocks.append('Canlı Bitget fiyat kaynağı doğrulanmadı')
    if quality.get('symbol')=='XAUUSD' and not quality.get('spot_configured'):blocks.append('Spot fiyat veri kaynağı yapılandırılmadı')
    proposed='LONG' if points_long>points_short else 'SHORT' if points_short>points_long else 'BEKLE'
    decision=proposed if not blocks else 'BEKLE'
    return {'decision':decision,'proposed_direction':proposed,'mode':'SHADOW_ONLY',
            'long_strength':round_or_none(points_long,1),'short_strength':round_or_none(points_short,1),
            'agreement_pct':round_or_none(agreement,1),'active_directional_engines':len(options),
            'configured_directional_engines':len(DIRECTIONAL),'coverage_pct':round_or_none(active_weight*100,1),
            'used_votes':[{'id':key,'direction':d,'strength':round_or_none(s,1),'weight':wt} for key,d,s,wt in options],
            'excluded':missing,'veto':list(dict.fromkeys(blocks)),
            'risk_status':{key:modules[key]['gate'] for key in ('gsquant','nautilus')},
            'context':{'mcm_daily':modules['mcm']['direction'],'riskfolio_gold_pct':modules['riskfolio']['metrics'].get('illustrative_gold_pct')},
            'explanation':'Yönsel güç puanları ağırlıklı gösterimdir, gerçek işlem başarı olasılığı değildir. Nakit tahsisi ve risk motorları yön oyu değildir.',
            'orders_enabled':False}

def analyze(closed_by_tf:dict,source:str,cfg_input=None,quality=None):
    """Pure, deterministic calculation; no I/O, no API keys, no upstream package import."""
    cfg=config_for(cfg_input)
    base=closed_by_tf.get('5m') or []
    h1=closed_by_tf.get('1H') or []
    d1=closed_by_tf.get('1D') or []
    def guard(key,fn,*args):
        try:return fn(*args,cfg[key])
        except Exception as exc:return base_result(key,reasons=[f'Analiz gerçekleştirilemedi: {type(exc).__name__}'])
    out={
       'soloshun':guard('soloshun',soloshun_engine,h1),
       'quantalytics':guard('quantalytics',quantalytics_engine,base),
       'joshua':guard('joshua',joshua_engine,base),
       'mcm':guard('mcm',mcm_engine,d1),
       'gsquant':guard('gsquant',gs_engine,h1 if len(h1)>=80 else base),
       'nautilus':guard('nautilus',naut_engine,base),
       'riskfolio':guard('riskfolio',riskfolio_engine,d1),
    }
    quality=quality or {}
    # Validate timestamp regularity and recency on the selected base timeframe.
    tf_seconds=int(quality.get('base_tf_seconds') or 300)
    recent=base[-60:]
    gaps=sum(1 for a,b in zip(recent,recent[1:]) if b['t']-a['t']!=tf_seconds)
    last_close_age=(__import__('time').time()-(base[-1]['t']+tf_seconds)) if base else float('inf')
    candle_fresh=last_close_age<=max(tf_seconds*2.5,120) and last_close_age>=-5
    quality={**quality,'recent_candle_gap_count':gaps,'last_closed_candle_age_s':round_or_none(last_close_age,1),
             'candles_ok':good_bars(base,260) and gaps==0 and candle_fresh}
    return {'version':VERSION,'source':source,'mode':'SHADOW_ONLY','orders_enabled':False,
            'sample_sizes':{key:len(v) for key,v in closed_by_tf.items()},
            'modules':out,'consensus':consensus(out,cfg['consensus'],quality),
            'config':cfg,'quality':quality,
            'disclaimer':'Orijinal 7 projeden kaynak kodu/model ağırlıkları çalıştırılmadı; proje yaklaşımlarına dayanan özgün, okunabilir adaptörlerdir.'}

def catalog():
    return {'version':VERSION,'sources':[{'id':k,'name':v[0],'url':v[1],'implementation':v[2],'kind':v[3],
                                        'settings':DEFAULTS[k], 'rules':PARAM_RULES[k]}
                     for k,v in SOURCES.items()],
            'consensus':{'settings':DEFAULTS['consensus'],'rules':PARAM_RULES['consensus']},
            'mode':'SHADOW_ONLY','orders_enabled':False,
            'note':'Uyarlama motorlarıdır, orijinal yedi kütüphane paketinin tam kurulumu değildir.'}
