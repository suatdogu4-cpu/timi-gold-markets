"""GOLD SCALP PRO Quant AI: auditable XAU session ML and stdlib XGBoost inference.

Upstream research: soloshun/Quantitative-XAUUSD-Strategy (MIT).
Independent, read-only adaptation. It does not load upstream pickle/joblib weights.
Uses only finalized hourly OHLC from an identified single-source instrument.
"""
from __future__ import annotations
import csv
from datetime import datetime, date, timedelta, timezone
import hashlib
import json
import math
from pathlib import Path
import statistics
import struct
import time

UTC=timezone.utc
ONE_HOUR=3600
FEATURES=('asia_return','asia_range','asia_body','asia_volatility','asia_first_half','asia_last_half','asia_wick_balance','day_of_week')
MIN_ROWS=180
MODEL_VERSION='1.0.0'
SOURCE={
    'XAUUSDT':'bitget_futures_market_h1',
    'XAUUSD':'dukascopy_xauusd_bid_h1'
}
PATHS={
    'XAUUSDT':('data/bitget_xauusdt_h1.csv','models/bitget_xauusdt_session_xgb.json'),
    'XAUUSD':('data/dukascopy_xauusd_h1.csv','models/dukascopy_xauusd_session_xgb.json')
}

def floatnum(x):
    try:
        f=float(x)
        return f if math.isfinite(f) else None
    except (TypeError,ValueError,OverflowError):
        return None

def clean_bars(bars, now_s=None):
    now_s=int(now_s or time.time()); by={}; errors=0
    for b in bars:
        try:
            t=int(b['t']); o,h,l,c=(floatnum(b[k]) for k in ('o','h','l','c'))
            if t%3600 or t<=0 or t+3600>now_s or None in (o,h,l,c) or min(o,h,l,c)<=0 or h<l or not(l<=o<=h and l<=c<=h):
                errors+=1;continue
            if t not in by:by[t]={'t':t,'o':o,'h':h,'l':l,'c':c,'v':floatnum(b.get('v')) or 0.0}
        except (KeyError,ValueError,TypeError):errors+=1
    return sorted(by.values(),key=lambda b:b['t']),errors

def read_csv(path):
    p=Path(path)
    if not p.exists():return []
    with p.open(encoding='utf-8',newline='') as f:
        return list(csv.DictReader(f))

def write_csv(path, rows):
    p=Path(path);p.parent.mkdir(parents=True,exist_ok=True)
    with p.open('w',encoding='utf-8',newline='') as f:
        writer=csv.DictWriter(f,fieldnames=['t','o','h','l','c','v'])
        writer.writeheader()
        for r in rows:writer.writerow({k:r.get(k,'') for k in ['t','o','h','l','c','v']})

def session_hours(day:date):
    start=datetime(day.year,day.month,day.day,tzinfo=UTC)
    prev=int((start-timedelta(hours=2)).timestamp())
    lon=int((start+timedelta(hours=8)).timestamp())
    return [prev+i*ONE_HOUR for i in range(10)],[lon+i*ONE_HOUR for i in range(9)]

def feature_vector(asia,day):
    op=asia[0]['o'];last=asia[-1]['c']
    c=[b['c'] for b in asia]; h=max(b['h'] for b in asia);l=min(b['l'] for b in asia)
    vol=statistics.pstdev([math.log(c[i]/c[i-1]) for i in range(1,len(c))])
    up=sum(b['h']-max(b['o'],b['c']) for b in asia)
    low=sum(min(b['o'],b['c'])-b['l'] for b in asia)
    # All features are known at London open (08:00 UTC), never from London.
    return [100*math.log(last/op),100*math.log(h/l),100*(last-op)/op,
            100*vol,100*math.log(asia[4]['c']/op),
            100*math.log(last/asia[4]['c']),100*(low-up)/op,day.weekday()/6]

def session_dataset(bars,now_s=None):
    now_s=int(now_s or time.time())
    valid,invalid=clean_bars(bars,now_s)
    by={b['t']:b for b in valid}
    days=sorted(set((datetime.fromtimestamp(t,UTC).date()+timedelta(days=1) if datetime.fromtimestamp(t,UTC).hour>=22 else datetime.fromtimestamp(t,UTC).date()) for t in by))
    data=[];candidates=[];partial_asia=0;partial_london=0
    for d in days:
        ah,lh=session_hours(d)
        if not all(t in by for t in ah):
            partial_asia+=1;continue
        asia=[by[t] for t in ah]
        row={'date':d.isoformat(),'cutoff':ah[-1]+ONE_HOUR,'features':feature_vector(asia,d),
             'asia_return_pct':100*(asia[-1]['c']/asia[0]['o']-1)}
        # Complete London session only; labels never created from partial sessions.
        if all(t in by for t in lh) and lh[-1]+ONE_HOUR<=now_s:
            london=[by[t] for t in lh]
            row['y']=int(london[-1]['c']>london[0]['o'])
            row['london_return_pct']=100*(london[-1]['c']/london[0]['o']-1)
            data.append(row)
        else:
            partial_london+=1
            # 08:00–16:59 UTC is the *only* live forecast interval.
            if lh[0]<=now_s<lh[-1]+ONE_HOUR:candidates.append(row)
    # A model trained on an older dataset can be stale; candidate is only today's completed Asia.
    return {'rows':data,'candidate':candidates[-1] if candidates else None,
            'audit':{'valid_hourly':len(valid),'invalid':invalid,'partial_asia':partial_asia,
                     'partial_london':partial_london,
                     'first_hour_utc':datetime.fromtimestamp(valid[0]['t'],UTC).isoformat() if valid else None,
                     'last_hour_utc':datetime.fromtimestamp(valid[-1]['t'],UTC).isoformat() if valid else None}}

def _float32(value):
    """Match XGBoost's float32 feature AND split-threshold semantics.

    JSON dump decimals (e.g. 0.6666667) can round differently from the
    original float32 threshold. Casting only the feature is NOT sufficient:
    both sides must be interpreted as IEEE 754 binary32 before comparing.
    """
    return struct.unpack('<f', struct.pack('<f', float(value)))[0]


def eval_tree(tree,features):
    node=tree
    for _ in range(12):
        if 'leaf' in node:return float(node['leaf'])
        split=node['split']; idx=int(split[1:]) if split.startswith('f') else FEATURES.index(split)
        value = None if features[idx] is None else _float32(features[idx])
        threshold = _float32(node['split_condition'])
        direction = node['yes'] if (value is None or value < threshold) else node['no']
        node=next(c for c in node['children'] if c['nodeid']==direction)
    raise ValueError('Bad tree: maximum depth exceeded')

def predict_margin(model,features):
    if len(features)!=len(FEATURES) or any(x is None or not math.isfinite(x) for x in features):
        raise ValueError('Invalid feature vector')
    return float(model['intercept'])+sum(eval_tree(tree,features) for tree in model['trees'])

def predict_probability(model,features):
    margin=predict_margin(model,features)
    return (1/(1+math.exp(-margin))) if margin>=0 else (math.exp(margin)/(1+math.exp(margin)))

def train_xgb(bars,symbol):
    if symbol not in SOURCE:raise ValueError('Invalid symbol')
    out=session_dataset(bars)
    rows=out['rows'];n=len(rows)
    meta={'symbol':symbol,'source':SOURCE[symbol],'labelled_sessions':n,
          'minimum_sessions':MIN_ROWS,'audit':out['audit'],
          'cutoff_utc':datetime.now(UTC).isoformat(),'trained':False,
          'approved':False,'orders_enabled':False,'consensus_vote':False,
          'reasons':[]}
    if n<MIN_ROWS:
        meta['reasons']=[f'Yeterli tarihsel seans yok: {n}/{MIN_ROWS}. Gerçek veri bekleniyor.']
        return None,meta
    try:
        from xgboost import XGBClassifier
        import numpy as np
    except (ImportError, OSError) as ex:
        meta['status']='DEPENDENCY_UNAVAILABLE'
        meta['reasons']=[f'XGBoost araştırma bağımlılığı yüklenemedi ({type(ex).__name__}); eğitim için GOLD ML GitHub Actions iş akışını kullanın.']
        return None,meta
    ntrain=int(n*.75)
    if n-ntrain<40:meta['reasons']=['Kronolojik test örneği 40 altında'];return None,meta
    xtrain=np.array([r['features'] for r in rows[:ntrain]],dtype=float)
    ytrain=np.array([r['y'] for r in rows[:ntrain]],dtype=int)
    xtest=np.array([r['features'] for r in rows[ntrain:]],dtype=float)
    ytest=np.array([r['y'] for r in rows[ntrain:]],dtype=int)
    if len(set(ytrain))<2 or min(sum(ytrain),len(ytrain)-sum(ytrain))<20:
        meta['reasons']=['Eğitimde iki yön için yeterli örnek yok'];return None,meta
    classifier=XGBClassifier(n_estimators=70,max_depth=3,learning_rate=.055,subsample=.85,
               colsample_bytree=.85,reg_lambda=8,random_state=42,n_jobs=2,
               objective='binary:logistic',eval_metric='logloss',tree_method='hist')
    classifier.fit(xtrain,ytrain)
    p=classifier.predict_proba(xtest)[:,1]
    pred=(p>=.5).astype(int)
    acc=float((pred==ytest).mean())
    majority=max(float(ytest.mean()),float(1-ytest.mean()))
    brier=float(np.mean((p-ytest)**2))
    base_brier=float(np.mean((np.full(len(ytest),ytrain.mean())-ytest)**2))
    # Conservative gate: must beat majority and constant-probability baseline out-of-sample.
    approved=(acc>=majority+.02 and brier<base_brier and n>=MIN_ROWS)
    trees=[json.loads(x) for x in classifier.get_booster().get_dump(dump_format='json')]
    raw_margin=classifier.predict(xtest,output_margin=True)
    # Obtain intercept from actual XGBoost margin; avoids version-dependent base_score assumptions.
    intercept=float(raw_margin[0])-sum(eval_tree(t,xtest[0]) for t in trees)
    model={'version':MODEL_VERSION,'symbol':symbol,'source':SOURCE[symbol],
           'training_end_day':rows[ntrain-1]['date'],'test_end_day':rows[-1]['date'],
           'trained_at_utc':datetime.now(UTC).isoformat(),'features':list(FEATURES),
           'train_sessions':ntrain,'test_sessions':n-ntrain,
           'test_accuracy_pct':round(100*acc,2),'test_majority_pct':round(100*majority,2),
           'test_brier':round(brier,6),'test_baseline_brier':round(base_brier,6),
           'approved':approved,'orders_enabled':False,'consensus_vote':False,
           'intercept':intercept,'trees':trees}
    # Portable tree evaluator must exactly match the trained library before deployment.
    diffs=[abs(predict_margin(model,xtest[i])-float(raw_margin[i])) for i in range(len(xtest))]
    if max(diffs)>1e-3:raise RuntimeError(f'Unsafe portable XGBoost export, worst margin diff: {max(diffs)}')
    meta.update({'trained':True,'approved':approved,
        'train_sessions':ntrain,'test_sessions':n-ntrain,'test_accuracy_pct':model['test_accuracy_pct'],
        'test_majority_pct':model['test_majority_pct'],'test_brier':model['test_brier'],
        'test_baseline_brier':model['test_baseline_brier'],
        'portable_export_max_margin_diff':max(diffs),
        'reasons':(['Kronolojik ileri test kapıları geçildi; araştırma tahmini aktif.'] if approved
                   else ['İleri test referans başarısı / Brier filtresi geçilmedi: canlı yön tahmini devre dışı.'])})
    return model,meta

def live_status(bars,symbol,model_root=None,now_s=None):
    """Read-only inference for existing Quant Hub. Never alters voting/consensus."""
    if symbol not in SOURCE:return {'status':'UNSUPPORTED','prediction':None}
    root=Path(model_root or Path(__file__).resolve().parent)
    path=root/PATHS[symbol][1]
    fallback={'symbol':symbol,'status':'MODEL_NOT_TRAINED','prediction':None,'probability':None,
              'orders_enabled':False,'consensus_vote':False,'model_approved':False}
    if not path.exists():return fallback
    try:
        model=json.loads(path.read_text(encoding='utf-8'))
        if model.get('symbol')!=symbol or model.get('source')!=SOURCE[symbol] or model.get('features')!=list(FEATURES):
            raise ValueError('Model identity / feature schema mismatch')
        metrics={k:model.get(k) for k in ['train_sessions','test_sessions','test_accuracy_pct','test_majority_pct','test_brier','test_baseline_brier','test_end_day','trained_at_utc']}
        out={**fallback,'status':'RESEARCH_ONLY','model_approved':bool(model.get('approved')),'metrics':metrics,
             'data_source':model['source']}
        if not model.get('approved'):
            out['reason']='İleri test filtresi geçilmedi; model oy vermez ve yön tahmini gösterilmez.'
            return out
        trained_time=datetime.fromisoformat(model['trained_at_utc']).timestamp()
        if int(now_s or time.time())-trained_time>8*86400:
            out['status']='STALE_MODEL'
            out['reason']='Model 8 günden eski; zamanlanmış veri/ML eğitimi kontrol edilmeli.'
            return out
        # Do not infer a Dukascopy-trained BID model from OANDA MID prices.
        if symbol=='XAUUSD':
            out['status']='SOURCE_MISMATCH';out['reason']='Dukascopy BID modeli OANDA MID canlı mumlarıyla çalıştırılmaz.'
            return out
        sample=session_dataset(bars,now_s=now_s)['candidate']
        if not sample:
            out['status']='NO_CURRENT_ASIA';out['reason']='Bugünün tamamlanmış Asya seansı veya Londra aktif saatleri bulunamadı.'
            return out
        p=predict_probability(model,sample['features'])
        out.update({'status':'VALIDATED_RESEARCH','candidate_day':sample['date'],
                    'probability':round(p*100,2),
                    'prediction':'LONG' if p>=.6 else 'SHORT' if p<=.4 else 'BEKLE',
                    'reason':'Londra seans yönüne ilişkin araştırma tahmini; işlem/garanti değildir.'})
        return out
    except Exception as e:
        return {**fallback,'status':'ERROR','reason':f'{type(e).__name__}: {str(e)[:120]}'}
