"""GOLD SCALP V6 - time-ordered, fee-aware XAU 1/3/5/15m strategy search.
No live trading, no claimed win probability. Source isolation, no lookahead.
Requires numpy, pandas, scikit-learn, xgboost/lightgbm on GitHub Actions only.
Render reads the resulting JSON without these packages.
"""
from __future__ import annotations
import argparse, itertools, json, math, time, warnings
from datetime import datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo
import numpy as np
import pandas as pd
from gold_scalp_v6_data import ROOT, ARCHIVE, SOURCES, read_history

TIMES=(1,3,5,15)
OUT=ROOT/'models/gold_scalp_v6_research.json'
MIN_BASE=1200
MAX_ML_SAMPLES=6000
UTC=timezone.utc
COST_BPS={'fee_bps_per_side':4.0, 'slippage_bps_per_side':2.0,'spread_bps_roundtrip':2.0}


def df_from_history(rows):
    if not rows:return pd.DataFrame(columns=['t','o','h','l','c','v'])
    d=pd.DataFrame([rows[k] for k in sorted(rows)])
    return d.astype({'t':'int64','o':'float64','h':'float64','l':'float64','c':'float64','v':'float64'})

def resample_closed_1m(d,tf):
    """Strict complete UTC time buckets, no interpolation or artificial candles."""
    if d.empty:return d.copy()
    if tf==1:return d.reset_index(drop=True)
    work=d.copy();work['bucket']=work.t//(tf*60)
    g=work.groupby('bucket',sort=True)
    k=g.agg(t=('t','min'),o=('o','first'),h=('h','max'),l=('l','min'),c=('c','last'),
            v=('v','sum'),count=('t','size'),last_t=('t','max'))
    k=k[(k['count']==tf)&((k['last_t']-k['t'])==(tf-1)*60)&(k['t']==k.index*tf*60)]
    return k[['t','o','h','l','c','v']].reset_index(drop=True)

def features(df):
    """All predictors refer only to completed bar i; orders enter from i+1."""
    a=df.copy()
    c=a.c;high=a.h;low=a.l;v=a.v
    for p in (9,20,50,200):a[f'ema{p}']=c.ewm(span=p,adjust=False,min_periods=p).mean()
    dif=c.diff();up=dif.clip(lower=0).ewm(alpha=1/14,adjust=False,min_periods=14).mean()
    down=(-dif.clip(upper=0)).ewm(alpha=1/14,adjust=False,min_periods=14).mean()
    a['rsi']=100-100/(1+up/down.replace(0,np.nan))
    e12=c.ewm(span=12,adjust=False,min_periods=12).mean();e26=c.ewm(span=26,adjust=False,min_periods=26).mean()
    macd=e12-e26;a['macdh']=macd-macd.ewm(span=9,adjust=False,min_periods=9).mean()
    tr=pd.concat((high-low,(high-c.shift(1)).abs(),(low-c.shift(1)).abs()),axis=1).max(axis=1)
    a['atr']=tr.ewm(alpha=1/14,adjust=False,min_periods=14).mean()
    a['atr_pct']=100*a.atr/c
    a['volratio']=v/v.rolling(30,min_periods=30).mean().replace(0,np.nan)
    typical=(high+low+c)/3
    a['vwap']=(typical*v).rolling(30,min_periods=30).sum()/v.rolling(30,min_periods=30).sum().replace(0,np.nan)
    a['bbmid']=c.rolling(20,min_periods=20).mean();a['bbstd']=c.rolling(20,min_periods=20).std(ddof=0)
    a['donch_hi']=high.shift(1).rolling(20,min_periods=20).max()
    a['donch_lo']=low.shift(1).rolling(20,min_periods=20).min()
    a['realvol']=c.pct_change().rolling(30,min_periods=30).std(ddof=0)
    a['ema_gap']=(a.ema20-a.ema50)/c
    a['vwap_gap']=(c-a.vwap)/c
    a['macd_rel']=a.macdh/c
    a['candle_body']=(c-a.o)/c
    a['ret3']=c.pct_change(3)
    a['ret12']=c.pct_change(12)
    ts=pd.to_datetime(a.t,unit='s',utc=True)
    a['hour_utc']=ts.dt.hour.to_numpy()
    a['weekday']=ts.dt.dayofweek.to_numpy()
    # Use DST-correct exchange-independent local session clocks.
    a['london_hour']=ts.dt.tz_convert('Europe/London').dt.hour.to_numpy()
    a['ny_hour']=ts.dt.tz_convert('America/New_York').dt.hour.to_numpy()
    a['hour_sin']=np.sin(2*np.pi*a.hour_utc/24)
    a['hour_cos']=np.cos(2*np.pi*a.hour_utc/24)
    a['is_london']=((a.london_hour>=8)&(a.london_hour<16)).astype(int)
    a['is_ny']=((a.ny_hour>=8)&(a.ny_hour<16)).astype(int)
    return a

def configs():
    out=[]
    # Bounded, predefined search space: no tuning on final holdout.
    for family in ('trend','breakout','reversion'):
        for vol in (1.0,1.45):
            for session in ('all','london','newyork'):
                for sensitivity in (0,1):
                    out.append({'family':family,'vol_min':vol,'session':session,'sensitivity':sensitivity,
                                'hold_bars':4 if sensitivity==0 else 7,
                                'atr_stop':1.3,'atr_take':2.0})
    return out

def signals(a,cfg):
    """Signals generated ONLY after bar i closes, NEVER from i+1."""
    f=cfg['family'];s=cfg['sensitivity'];c=a.c
    if f=='trend':
        up=(a.ema20>a.ema50)&(c>a.ema20)&(a.macdh>0)&(a.rsi>(53 if s==0 else 57))
        dn=(a.ema20<a.ema50)&(c<a.ema20)&(a.macdh<0)&(a.rsi<(47 if s==0 else 43))
    elif f=='breakout':
        up=(c>a.donch_hi)&(a.macdh>0 if s==0 else a.ema20>a.ema50)
        dn=(c<a.donch_lo)&(a.macdh<0 if s==0 else a.ema20<a.ema50)
    else:
        width=(1.45 if s==0 else 1.9)*a.bbstd
        up=(c<a.bbmid-width)&(a.rsi<(35 if s==0 else 30))
        dn=(c>a.bbmid+width)&(a.rsi>(65 if s==0 else 70))
    ok=(a.volratio>=cfg['vol_min'])&(a.atr_pct>0)&(a.weekday<5)
    if cfg['session']=='london':ok&=a.is_london.astype(bool)
    if cfg['session']=='newyork':ok&=a.is_ny.astype(bool)
    return np.where(ok&up,1,np.where(ok&dn,-1,0)).astype(np.int8)

def backtest(a, signal, start, end, cfg, gap_penalty=True):
    """Single position: signal at closed i, entry OPEN(i+1), stop-first at intrabar tie.
    Exit at first stop/take or max holding close. Gap across missing bars blocks entry.
    """
    n=len(a);start=max(230,int(start));end=min(int(end),n-1)
    if end<=start:return metrics([])
    o=a.o.to_numpy();hi=a.h.to_numpy();lo=a.l.to_numpy();cl=a.c.to_numpy()
    t=a.t.to_numpy();atr=a.atr.to_numpy();fee=COST_BPS
    cost=2*(fee['fee_bps_per_side']+fee['slippage_bps_per_side'])+fee['spread_bps_roundtrip']
    pnl=[];i=start
    while i<end-1:
        if signal[i]==0 or not np.isfinite(atr[i]) or atr[i]<=0 or t[i+1]-t[i] != cfg['tf_seconds']:
            i+=1;continue
        direction=int(signal[i]);entry=float(o[i+1]);distance=cfg['atr_stop']*atr[i]
        stop=entry-direction*distance;take=entry+direction*cfg['atr_take']*atr[i]
        exit_price=None;exit_i=i+1;valid=True
        for j in range(i+1,min(end,i+1+cfg['hold_bars'])):
            if j>i+1 and t[j]-t[j-1]!=cfg['tf_seconds']:valid=False;break
            sl=lo[j]<=stop if direction==1 else hi[j]>=stop
            tp=hi[j]>=take if direction==1 else lo[j]<=take
            if sl:exit_price=stop;exit_i=j;break # loss first if both touched
            if tp:exit_price=take;exit_i=j;break
            exit_i=j
        if valid:
            if exit_price is None:exit_price=float(cl[exit_i])
            # Conservative gap/open adverse execution even when stop gapped.
            if direction==1 and o[exit_i]<stop:exit_price=min(exit_price,float(o[exit_i]))
            elif direction==-1 and o[exit_i]>stop:exit_price=max(exit_price,float(o[exit_i]))
            pnl.append(direction*(exit_price-entry)/entry*10000-cost)
        i=max(i+1,exit_i+1)
    return metrics(pnl)

def metrics(pnls):
    n=len(pnls)
    if not n:return {'trades':0,'expectancy_bps':None,'profit_factor':None,'win_pct':None,
                    'net_bps':None,'max_drawdown_bps':None}
    ar=np.asarray(pnls,dtype=float);wins=ar[ar>0];losses=ar[ar<0]
    curve=np.cumsum(ar);dd=np.maximum.accumulate(np.r_[0,curve])[1:]-curve
    return {'trades':n,'expectancy_bps':round(float(ar.mean()),3),
            'profit_factor':round(float(wins.sum()/abs(losses.sum())),3) if len(losses) else None,
            'win_pct':round(100*float((ar>0).mean()),2),
            'net_bps':round(float(ar.sum()),2),
            'max_drawdown_bps':round(float(max(dd)),2)}

def validation_plan(n):
    # First 80%: expanding train then 3 validation folds; last 20% untouched.
    end=int(n*.8);test_start=end+min(12,max(3,n//2000))
    return [(int(n*.35),int(n*.46)),(int(n*.46),int(n*.60)),(int(n*.60),int(n*.8))],test_start

def optimize_strategies(a,source,tf):
    n=len(a);required=max(MIN_BASE,300 if tf>=5 else 1600)
    result={'source':source,'timeframe':f'{tf}m','bars':n,'tested_configurations':0,
            'status':'INSUFFICIENT_HISTORY','best':None,'shortlist':[],'live_signal':False}
    if n<required:return result
    folds,final_start=validation_plan(n);results=[]
    for c0 in configs():
        cfg={**c0,'tf_seconds':tf*60}
        sig=signals(a,cfg)
        val=[backtest(a,sig,start+min(12,n//2000),end,cfg) for start,end in folds]
        trades=sum(x['trades'] for x in val)
        if trades<18 or sum(x['trades']>=3 for x in val)<3:continue
        # Strict risk-aware selection, penalize fold instability and drawdown.
        mean_exp=sum((v['expectancy_bps'] or 0)*v['trades'] for v in val)/trades
        negfold=sum((v['expectancy_bps'] or 0)<=0 for v in val)
        dd=sum((v['max_drawdown_bps'] or 0) for v in val)/3
        score=mean_exp-5*negfold-0.02*dd
        results.append((score,cfg,sig,val,mean_exp,trades))
    result['tested_configurations']=len(configs());result['eligible_configurations']=len(results)
    if not results:return {**result,'status':'NO_VALIDATION_CANDIDATE'}
    results.sort(key=lambda x:(-x[0],-x[5],x[1]['family']))
    selected=results[0];_,cfg,sig,folds_out,valexp,valtrades=selected
    test=backtest(a,sig,final_start,n-1,cfg)
    val_positive=(all(x['expectancy_bps'] is not None and x['expectancy_bps']>0 for x in folds_out))
    accepted=bool(test['trades']>=15 and test['expectancy_bps'] is not None and test['expectancy_bps']>0
                  and test['profit_factor'] is not None and test['profit_factor']>=1.1 and val_positive
                  and valtrades>=30)
    result.update({'status':'RETROSPECTIVE_GATE_PASSED' if accepted else 'RESEARCH_ONLY_REJECTED',
      'best':{'configuration':cfg,'validation_folds':folds_out,
              'validation_weighted_expectancy_bps':round(valexp,3),
              'holdout':test,'historical_gate_passed':accepted,'trade_decision':'BEKLE'},
      'shortlist':[{'configuration':x[1],'validation_score':round(x[0],3),
                    'validation_trades':x[5]} for x in results[:5]],
      'final_holdout_start_utc':datetime.fromtimestamp(int(a.t.iloc[final_start]),UTC).isoformat()})
    return result

ML_COLUMNS=('ema_gap','vwap_gap','macd_rel','rsi','atr_pct','volratio',
            'realvol','candle_body','ret3','ret12','hour_sin','hour_cos','weekday')

def get_ml_model(name):
    if name=='LogisticRegression':
        from sklearn.preprocessing import StandardScaler
        from sklearn.pipeline import make_pipeline
        from sklearn.linear_model import LogisticRegression
        return make_pipeline(StandardScaler(),LogisticRegression(C=.15,max_iter=400,random_state=49))
    if name=='XGBoost':
        from xgboost import XGBClassifier
        return XGBClassifier(n_estimators=55,max_depth=2,learning_rate=.05,reg_lambda=15,
                             subsample=.9,colsample_bytree=.9,n_jobs=2,random_state=49,
                             objective='binary:logistic',eval_metric='logloss',tree_method='hist')
    if name=='LightGBM':
        from lightgbm import LGBMClassifier
        return LGBMClassifier(n_estimators=55,max_depth=3,num_leaves=7,learning_rate=.04,
                              min_child_samples=30,reg_lambda=15,n_jobs=2,random_state=49,verbosity=-1)
    raise ValueError(name)

def brier(y,p):return float(np.mean((p-y)**2))
def evaluate_classifier(y,p,base):
    y=np.asarray(y,int);p=np.asarray(p,float);p=np.clip(p,.00001,.99999)
    return {'samples':len(y),'accuracy_pct':round(float(100*np.mean((p>=.5)==y)),2),
            'majority_pct':round(float(100*max(np.mean(y),1-np.mean(y))),2),
            'brier':round(brier(y,p),6),'baseline_brier':round(brier(y,np.full(len(y),base)),6)}

def research_ml(a,tf):
    """Binary future direction research, not net-trade profitability/long-short approval."""
    n=len(a);report={'status':'INSUFFICIENT_HISTORY','features':list(ML_COLUMNS),
                     'target':'future close vs next bar open, no live predictions',
                     'selection':'validation-only Brier, last 20% untouched','models':{},'approved':False}
    horizon={1:3,3:2,5:2,15:1}[tf]
    b=a.copy()
    b['target']=(b.c.shift(-horizon)>b.o.shift(-1)).astype('float')
    b.loc[b.index>=n-horizon,'target']=np.nan
    # No target across discontinuities.
    step=tf*60
    aligned=(b.t.shift(-horizon)-b.t==step*horizon)
    b.loc[~aligned,'target']=np.nan
    b=b.replace([np.inf,-np.inf],np.nan).dropna(subset=list(ML_COLUMNS)+['target'])
    if len(b)<1500:return report
    # Stratified/random subsampling is forbidden. Deterministic uniform chronology only.
    stride=max(1,len(b)//MAX_ML_SAMPLES)
    b=b.iloc[::stride].reset_index(drop=True)
    x=b[list(ML_COLUMNS)].to_numpy(dtype=float);y=b.target.to_numpy(dtype=int);n=len(y)
    folds,final_start=validation_plan(n)
    purge=max(6,math.ceil(horizon/stride)+3)
    def fit_predict(name,train_end,start,end):
        if train_end<=30 or len(set(y[:train_end]))<2:return None
        m=get_ml_model(name);m.fit(x[:train_end-purge],y[:train_end-purge])
        p=m.predict_proba(x[start:end])[:,1]
        return evaluate_classifier(y[start:end],p,float(np.mean(y[:train_end-purge])))
    scores=[]
    for name in ('LogisticRegression','XGBoost','LightGBM'):
        vals=[]
        try:
            for tr,ed in folds:
                v=fit_predict(name,tr,tr+purge,ed)
                if v is not None:vals.append(v)
        except Exception as e:
            report['models'][name]={'status':'ERROR','reason':str(e)[:110]};continue
        if len(vals)!=3:continue
        score=float(np.mean([v['brier'] for v in vals]))
        report['models'][name]={'status':'VALIDATED','walk_forward':vals,
                                 'mean_validation_brier':round(score,6)}
        scores.append((score,name))
    if not scores:return {**report,'status':'NO_VALID_ML'}
    selected=min(scores)[1]
    for name,_ in [(n,0) for _,n in scores]:
        try:report['models'][name]['final_holdout']=fit_predict(name,final_start,final_start+purge,n)
        except Exception as e:report['models'][name]['final_holdout']={'error':str(e)[:110]}
    chosen=report['models'][selected]
    t=chosen['final_holdout']
    accepted=bool(t and 'brier' in t and t['samples']>=100 and
                  t['brier']<t['baseline_brier'] and t['accuracy_pct']>=t['majority_pct']+2 and
                  chosen['mean_validation_brier']<np.mean([f['baseline_brier'] for f in chosen['walk_forward']]))
    return {**report,'status':'HISTORICAL_GATE_PASSED' if accepted else 'RESEARCH_ONLY_REJECTED',
            'selected_by_validation':selected,'approved':accepted,'training_samples':n,
            'holdout_start_utc':datetime.fromtimestamp(int(b.t.iloc[final_start]),UTC).isoformat(),
            'no_live_signal':True}

def source_summary(source,source_rows):
    raw=df_from_history(source_rows)
    report={'source_key':source,'source_id':SOURCES[source],
            'source_type':'XAUUSDT futures OHLCV trade candles',
            'one_minute_bars':len(raw),'timeframes':{},'independent_source':True}
    for tf in TIMES:
        df=resample_closed_1m(raw,tf)
        d=features(df) if len(df)>210 else df
        if len(d)<=210:
            report['timeframes'][f'{tf}m']={'bars':len(d),'status':'INSUFFICIENT_HISTORY'};continue
        combo=optimize_strategies(d,source,tf)
        combo['ml']=research_ml(d,tf)
        combo['source_utc_last']=datetime.fromtimestamp(int(d.t.iloc[-1]+tf*60),UTC).isoformat()
        report['timeframes'][f'{tf}m']=combo
    return report

def main():
    p=argparse.ArgumentParser();p.add_argument('--max-tf',type=int,default=15);a=p.parse_args()
    output={'version':'6.0.0','generated_utc':datetime.now(UTC).isoformat(),
            'run_policy':'RESEARCH_ONLY_NO_LIVE_SIGNAL_NO_ORDERS',
            'commission_assumptions_bps':COST_BPS,
            'timeframes':['1m','3m','5m','15m'],'sources':{},
            'notes':['1m bars must be real closed source OHLCV, never upsampled from H1.',
                     '3/5/15m require complete consecutive 1m buckets; gaps skipped.',
                     'Validation selects configurations; independent final holdout is inspected once.',
                     'Volume is exchange-specific, not global gold volume.',
                     'No order book history inferred from candles; no real orders or forecasts.']}
    for source in SOURCES:
        data=read_history(source)
        try:output['sources'][source]=source_summary(source,data)
        except Exception as e:output['sources'][source]={'status':'ERROR','reason':str(e)[:220],'one_minute_bars':len(data)}
    OUT.parent.mkdir(parents=True,exist_ok=True)
    OUT.write_text(json.dumps(output,indent=2,ensure_ascii=False,allow_nan=False)+'\n',encoding='utf-8')
    print('GOLD_V6_RESEARCH',json.dumps({'sources':{k:{'bars':v.get('one_minute_bars'),
          'timeframes':{tf:{'status':t.get('status'),'eligible':t.get('eligible_configurations'),
                       'model':t.get('ml',{}).get('selected_by_validation')} for tf,t in v.get('timeframes',{}).items()}}
                       for k,v in output['sources'].items()},'report':str(OUT)},ensure_ascii=False))
    if not any(v.get('one_minute_bars',0)>0 for v in output['sources'].values()):
        raise SystemExit('Historical report has zero source minutes')
if __name__=='__main__':main()
