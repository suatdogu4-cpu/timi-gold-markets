"""GOLD SCALP PRO / v3: source-isolated research feature engineering and ML comparison.

Read-only. Never places orders, contributes a consensus vote, or issues a live signal.
Training needs XGBoost, LightGBM, NumPy and scikit-learn (GitHub Actions only).
Render loads only the JSON report with Python's standard library.
Feature timestamps end strictly before 08:00 UTC, the beginning of London.
"""
from __future__ import annotations
from datetime import datetime, timedelta, timezone
import json
import math
from pathlib import Path
import statistics
import time
from typing import Any

UTC = timezone.utc
HOUR = 3600
FEAT_VERSION = "3.0.0"
MIN_SESSIONS = 180
SOURCES = {
    'bitget_xauusdt': {'symbol': 'XAUUSDT', 'exchange': 'Bitget', 'market': 'USDT-FUTURES', 'source_id': 'bitget_futures_market_h1'},
    'binance_xauusdt': {'symbol': 'XAUUSDT', 'exchange': 'Binance', 'market': 'USD-M-FUTURES', 'source_id': 'binance_usdm_trade_h1'},
    'dukascopy_xauusd': {'symbol': 'XAUUSD', 'exchange': 'Dukascopy', 'market': 'SPOT-BID', 'source_id': 'dukascopy_xauusd_bid_h1'},
}
COLUMNS = (
    'asia_log_return', 'asia_range_pct', 'asia_body_pct', 'asia_volatility',
    'asia_first_half_pct', 'asia_last_half_pct', 'asia_wick_balance_pct',
    'day_of_week_sin', 'day_of_week_cos', 'rsi14', 'macd_hist_pct',
    'ema20_50_gap_pct', 'price_ema20_gap_pct', 'atr14_pct',
    'volatility_24', 'volatility_72', 'volatility_ratio',
    'momentum_6', 'momentum_24', 'prior_asia_return', 'prior_london_return',
    'prior_session_missing', 'trend_regime', 'vol_regime', 'asia_volume_ratio',
    'last_candle_range_pct',
)


def valid_bars(rows: list[dict], now_s: int | None = None) -> list[dict]:
    """Unique, sorted, closed, on-hour OHLC only. Never synthesize missing candles."""
    if now_s is None: now_s=int(time.time())
    out={}
    for r in rows:
        try:
            t=int(r['t'])
            o,h,l,c=(float(r[k]) for k in 'ohlc')
            if (t <= 0 or t % HOUR or t + HOUR > now_s or
                not all(math.isfinite(v) for v in (o,h,l,c)) or
                min(o,h,l,c) <= 0 or h < l or not l <= o <= h or not l <= c <= h):
                continue
            v=float(r.get('v',0) or 0)
            if t not in out:
                out[t]={'t':t,'o':o,'h':h,'l':l,'c':c,'v':v if math.isfinite(v) and v>=0 else 0.0}
        except (KeyError,ValueError,TypeError,OverflowError):
            continue
    return sorted(out.values(),key=lambda x:x['t'])


def ema(xs: list[float], period: int) -> float:
    if len(xs)<period:raise ValueError('Insufficient EMA candles')
    e=sum(xs[:period])/period
    alpha=2/(period+1)
    for x in xs[period:]:e+=alpha*(x-e)
    return e


def ema_series(xs: list[float], period: int) -> list[float]:
    if len(xs)<period:raise ValueError('Insufficient EMA series')
    e=sum(xs[:period])/period
    out=[e]
    for x in xs[period:]:
        e+=2/(period+1)*(x-e);out.append(e)
    return out


def rsi(xs: list[float], period: int=14) -> float:
    if len(xs)<period+1:raise ValueError('Insufficient RSI candles')
    ds=[xs[i]-xs[i-1] for i in range(1,len(xs))]
    up=sum(max(x,0) for x in ds[:period])/period
    down=sum(max(-x,0) for x in ds[:period])/period
    for d in ds[period:]:
        up=(up*(period-1)+max(d,0))/period
        down=(down*(period-1)+max(-d,0))/period
    return 100.0 if down==0 and up>0 else (50.0 if down==0 else 100-100/(1+up/down))


def macd_histogram(xs: list[float]) -> float:
    if len(xs)<60:raise ValueError('Insufficient MACD history')
    e12=ema_series(xs,12)
    e26=ema_series(xs,26)
    aligned=[e12[i+14]-e26[i] for i in range(len(e26))]
    return aligned[-1]-ema(aligned,9)


def atr(bars:list[dict],period:int=14) -> float:
    if len(bars)<period+1:raise ValueError('Insufficient ATR candles')
    true_ranges=[]
    for i in range(1,len(bars)):
        b=bars[i];pc=bars[i-1]['c']
        true_ranges.append(max(b['h']-b['l'],abs(b['h']-pc),abs(b['l']-pc)))
    val=sum(true_ranges[:period])/period
    for t in true_ranges[period:]:val=(val*(period-1)+t)/period
    return val


def _pct(x):return 100*x


def _features(asia:list[dict],past:list[dict],day,prev:dict|None):
    closes=[x['c'] for x in past]
    last=closes[-1]
    e20,e50=ema(closes,20),ema(closes,50)
    ret=[math.log(closes[i]/closes[i-1]) for i in range(1,len(closes))]
    v24=statistics.pstdev(ret[-24:])*100
    v72=statistics.pstdev(ret[-72:])*100
    asiac=[b['c'] for b in asia]; ao=asia[0]['o'];ac=asia[-1]['c']
    hi=max(b['h'] for b in asia);lo=min(b['l'] for b in asia)
    aup=sum(b['h']-max(b['o'],b['c']) for b in asia)
    alow=sum(min(b['o'],b['c'])-b['l'] for b in asia)
    av=statistics.pstdev([math.log(asiac[i]/asiac[i-1]) for i in range(1,len(asiac))])*100
    volavg=statistics.mean(b['v'] for b in past[-72:])
    asvol=statistics.mean(b['v'] for b in asia)
    trend=1 if last>e20>e50 else -1 if last<e20<e50 else 0
    prior_asia=prev.get('asia_return',0) if prev is not None else 0
    prior_lon=prev.get('london_return',0) if prev is not None else 0
    values=(
        _pct(math.log(ac/ao)),_pct((hi-lo)/ao),_pct((ac-ao)/ao),av,
        _pct(math.log(asia[4]['c']/ao)),_pct(math.log(ac/asia[4]['c'])),
        _pct((alow-aup)/ao),math.sin(2*math.pi*day.weekday()/7),
        math.cos(2*math.pi*day.weekday()/7),rsi(closes),
        _pct(macd_histogram(closes)/last),_pct((e20-e50)/e50),
        _pct((last-e20)/e20),_pct(atr(past)/last),
        v24,v72,v24/max(v72,1e-9),
        _pct(math.log(last/closes[-7])),_pct(math.log(last/closes[-25])),
        prior_asia,prior_lon,0 if prev else 1,trend,
        1 if v24>v72*1.15 else -1 if v24<v72*.85 else 0,
        min(asvol/max(volavg,1e-9),25.0) if volavg else 0,
        _pct((past[-1]['h']-past[-1]['l'])/last),
    )
    if len(values)!=len(COLUMNS) or not all(math.isfinite(x) for x in values):
        raise ValueError('Feature schema / nonfinite feature')
    return list(values)


def sessions(rows:list[dict],now_s:int|None=None):
    """Compute only London-open-known features from the SAME source and instrument."""
    if now_s is None:now_s=int(time.time())
    bars=valid_bars(rows,now_s)
    by={b['t']:b for b in bars}
    keys=sorted(by)
    all_days=set()
    for t in keys:
        dt=datetime.fromtimestamp(t,UTC)
        if dt.hour>=22:all_days.add(dt.date()+timedelta(days=1))
        else:all_days.add(dt.date())
    previous_by_day={}
    data=[];candidate=None;miss_asia=miss_london=miss_hist=0
    for day in sorted(all_days):
        start=int(datetime(day.year,day.month,day.day,tzinfo=UTC).timestamp())
        cutoff=start+8*HOUR
        asia_ts=[start-2*HOUR+i*HOUR for i in range(10)]
        london_ts=[cutoff+i*HOUR for i in range(9)]
        if any(t not in by for t in asia_ts):
            miss_asia+=1;continue
        # All indicators are computed on PRE-cutoff bars. Asia closes exactly at 08:00.
        history=[by[t] for t in keys if t+HOUR<=cutoff]
        if len(history)<121 or history[-1]['t']!=cutoff-HOUR:
            miss_hist+=1;continue
        asia=[by[t] for t in asia_ts]
        prev=previous_by_day.get(day-timedelta(days=1))
        features=_features(asia,history[-160:],day,prev)
        entry={'day':day.isoformat(),'cutoff':cutoff,'x':features,'asia_return':100*(asia[-1]['c']/asia[0]['o']-1)}
        if all(t in by for t in london_ts) and cutoff+9*HOUR<=now_s:
            london=[by[t] for t in london_ts]
            entry['y']=int(london[-1]['c']>london[0]['o'])
            entry['london_return']=100*(london[-1]['c']/london[0]['o']-1)
            data.append(entry)
            previous_by_day[day]=entry
        else:
            miss_london+=1
            if cutoff<=now_s<cutoff+9*HOUR:candidate=entry
    return {'samples':data,'candidate':candidate,'audit':{
        'valid_closed_h1':len(bars),'complete_sessions':len(data),
        'missing_asia':miss_asia,'missing_london':miss_london,
        'missing_indicator_history':miss_hist,
        'last_closed_utc':datetime.fromtimestamp(bars[-1]['t']+HOUR,UTC).isoformat() if bars else None,
        'feature_cutoff':'08:00 UTC London open, no London candles in X',
    }}


def _model(name:str):
    if name=='XGBoost':
        from xgboost import XGBClassifier
        return XGBClassifier(n_estimators=90,max_depth=2,learning_rate=.045,
            subsample=.8,colsample_bytree=.85,reg_lambda=10,random_state=42,
            n_jobs=2,objective='binary:logistic',eval_metric='logloss',tree_method='hist')
    if name=='LightGBM':
        from lightgbm import LGBMClassifier
        return LGBMClassifier(n_estimators=90,learning_rate=.035,num_leaves=5,
            min_child_samples=15,max_depth=3,reg_lambda=10,verbosity=-1,
            random_state=42,n_jobs=2)
    if name=='LogisticRegression':
        from sklearn.pipeline import Pipeline
        from sklearn.preprocessing import StandardScaler
        from sklearn.linear_model import LogisticRegression
        return Pipeline([('scale',StandardScaler()),
            ('model',LogisticRegression(C=.15,max_iter=1500,random_state=42))])
    raise ValueError('Unknown model name')


def _score(y,p,base):
    import numpy as np
    y=np.asarray(y,dtype=int);p=np.asarray(p,dtype=float)
    p=np.clip(p,1e-6,1-1e-6)
    baseline_label=int(base>=.5)
    return {'samples':len(y),
        'accuracy_pct':round(100*float(np.mean((p>=.5)==y)),2),
        'baseline_accuracy_pct':round(100*float(np.mean(y==baseline_label)),2),
        'test_majority_pct':round(100*max(float(np.mean(y)),1-float(np.mean(y))),2),
        'brier':round(float(np.mean((p-y)**2)),6),
        'baseline_brier':round(float(np.mean((base-y)**2)),6),
        'log_loss':round(float(np.mean(-y*np.log(p)-(1-y)*np.log(1-p))),6)}


def compare_models(rows:list[dict],source_key:str,now_s:int|None=None):
    if source_key not in SOURCES:raise ValueError('Unknown source key')
    import numpy as np
    d=sessions(rows,now_s);samples=d['samples'];n=len(samples)
    source=SOURCES[source_key]
    report={'version':FEAT_VERSION,'source_key':source_key,'source':source,
        'features':list(COLUMNS),'feature_count':len(COLUMNS),
        'audit':d['audit'],'samples':n,'minimum_sessions':MIN_SESSIONS,
        'models':{},'selected_by_validation':None,'approved':False,
        'live_prediction_enabled':False,'consensus_vote':False,'orders_enabled':False,
        'created_at_utc':datetime.now(UTC).isoformat(),
        'limitations':['Validation and historical test are retrospective, not live-forward evidence.',
         'H1 direction is a research label, not a 1-5 minute scalping profit target.',
         'Calendar uses fixed UTC sessions, not London DST shifts.',
         'Exchange and spot prices are never interleaved.']}
    if n<MIN_SESSIONS:
        report['reason']=f'Insufficient complete sessions: {n}/{MIN_SESSIONS}'
        return report
    x=np.asarray([r['x'] for r in samples],dtype=float)
    y=np.asarray([r['y'] for r in samples],dtype=int)
    test_start=int(n*.75)
    initial=int(n*.44)
    if test_start-initial<45 or n-test_start<40:
        report['reason']='Insufficient independent temporal validation windows'
        return report
    # Three expanding train/forward-validation windows; last 25% used only once for audit.
    chunks=[initial+int(i*(test_start-initial)/3) for i in range(4)]
    fold_plan=[(0,chunks[i],chunks[i],chunks[i+1]) for i in range(3)]
    val_scores={}
    for name in ('XGBoost','LightGBM','LogisticRegression'):
        vals=[]
        for _,train_end,val_start,val_end in fold_plan:
            if len(set(y[:train_end]))<2:continue
            model=_model(name)
            model.fit(x[:train_end],y[:train_end])
            p=model.predict_proba(x[val_start:val_end])[:,1]
            vals.append(_score(y[val_start:val_end],p,float(np.mean(y[:train_end]))))
        if not vals:
            report['models'][name]={'status':'NO_VALIDATION_FOLDS'}
            continue
        val_scores[name]=statistics.mean(s['brier'] for s in vals)
        report['models'][name]={'status':'VALIDATED','walk_forward_folds':len(vals),
            'walk_forward_avg_brier':round(val_scores[name],6),
            'walk_forward_avg_baseline_brier':round(statistics.mean(v['baseline_brier'] for v in vals),6),
            'walk_forward_avg_accuracy_pct':round(statistics.mean(v['accuracy_pct'] for v in vals),2)}
    if not val_scores:
        report['reason']='No usable walk-forward validation results'
        return report
    selected=min(val_scores,key=lambda k:(val_scores[k],k))
    report['selected_by_validation']=selected
    ytr=y[:test_start];ytest=y[test_start:]
    for name in ('XGBoost','LightGBM','LogisticRegression'):
        if name not in val_scores:continue
        trained=_model(name)
        trained.fit(x[:test_start],ytr)
        p=trained.predict_proba(x[test_start:])[:,1]
        report['models'][name]['final_holdout']=_score(ytest,p,float(np.mean(ytr)))
        # All three holdout scores are diagnostic only; model selection used validation, never holdout.
    chosen=report['models'][selected]
    valid=chosen['final_holdout']
    avg_brier=chosen['walk_forward_avg_brier']
    avg_base=chosen['walk_forward_avg_baseline_brier']
    approved=(
        chosen['walk_forward_folds']==3 and avg_brier<avg_base and
        valid['accuracy_pct']>=max(valid['baseline_accuracy_pct'],valid['test_majority_pct'])+2 and
        valid['brier']<valid['baseline_brier'] and n>=MIN_SESSIONS
    )
    report['approved']=bool(approved)
    report['reason']=('Passes retrospective research gates, live prediction disabled pending shadow prospective validation'
       if approved else 'Walk-forward or final holdout gates not met; no signal')
    report['split']={'train_validation_end_day':samples[test_start-1]['day'],
        'final_holdout_first_day':samples[test_start]['day'],
        'final_holdout_last_day':samples[-1]['day'],
        'final_holdout_count':len(ytest),
        'selection':'validation-only Brier, before final holdout'}
    return report


def report_for_symbol(symbol:str,root:str|Path):
    """Safe standard-library reader called by Render. No training nor trading dependencies."""
    result={'status':'NO_REPORT','version':FEAT_VERSION,'symbol':symbol,
            'orders_enabled':False,'consensus_vote':False,'prediction':None}
    path=Path(root)/'models'/'gold_ml_v3_comparison.json'
    if not path.is_file():return result
    try:
        raw=json.loads(path.read_text(encoding='utf-8'))
        if raw.get('version')!=FEAT_VERSION:return {**result,'status':'SCHEMA_MISMATCH'}
        all_sources=raw.get('sources',{})
        allowed=[k for k,v in SOURCES.items() if v['symbol']==symbol]
        sources={k:all_sources[k] for k in allowed if k in all_sources and all_sources[k].get('source_key')==k}
        return {**result,'status':'RESEARCH_COMPARISON','sources':sources,
            'last_run_utc':raw.get('generated_at_utc'),
            'storage':raw.get('storage',{}),'source_health':{k:v for k,v in (raw.get('source_health') or {}).items() if k in allowed},'signal_policy':'NO_V3_LIVE_SIGNAL'}
    except (OSError,ValueError,TypeError) as e:
        return {**result,'status':'REPORT_ERROR','error':str(e)[:100]}
