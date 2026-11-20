"""GOLD SCALP PRO V5 — cloud-only prospective, research-only session shadow journal.

The exchange/telephone/Render do not control this process: execute from scheduled
GitHub Actions against direct Bitget public H1 market data. No orders, keys,
consensus voting, or transaction advice. Predictions are deliberately unavailable
outside the narrow London-open capture window and cannot be backfilled.
"""
from __future__ import annotations
import argparse
import csv
import hashlib
import json
import math
import os
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Any

from gold_ml_v3 import COLUMNS, FEAT_VERSION, MIN_SESSIONS, _model, sessions

UTC=timezone.utc
ROOT=Path(__file__).resolve().parent
HOUR=3600
SOURCE='bitget_xauusdt'
SOURCE_ID='bitget_futures_market_h1'
MODEL='XGBoost'
CSV=ROOT/'data'/'bitget_xauusdt_h1.csv'
JOURNAL=ROOT/'datasets'/'gold_shadow_v5'/'events.jsonl'
STATUS=ROOT/'models'/'gold_shadow_v5_status.json'
VERSION='5.0.0'
ZERO_HASH='0'*64
# 08:00 UTC = Asia end / London open, when the 07:00 H1 candle closes.
# 08:05–08:55 is a capture grace window, NOT a claim of 08:00 publication.
FORECAST_FROM=(8,5)
FORECAST_UNTIL=(8,55)
SETTLE_FROM=(17,10)


def utc_iso(ts):return datetime.fromtimestamp(int(ts),UTC).isoformat()

def _canon(item):return json.dumps(item,ensure_ascii=False,sort_keys=True,separators=(',',':'),allow_nan=False)

def _sha(item):return hashlib.sha256(item).hexdigest()

def read_events(path=JOURNAL):
    if not path.exists():return []
    events=[];previous=ZERO_HASH
    with path.open(encoding='utf-8') as stream:
        for idx,line in enumerate(stream,1):
            if not line.strip():raise ValueError(f'Empty journal line {idx}')
            e=json.loads(line)
            if not isinstance(e,dict):raise ValueError(f'Bad journal event {idx}')
            h=e.get('hash');payload={k:v for k,v in e.items() if k!='hash'}
            expected=_sha((previous+'|'+_canon(payload)).encode('utf-8'))
            if e.get('prev_hash')!=previous or e.get('seq')!=idx or h!=expected:
                raise ValueError(f'TAMPERED_JOURNAL_EVENT_{idx}')
            if e.get('event') not in ('FORECAST','SETTLED','MISSED'):
                raise ValueError(f'Unknown journal event {idx}')
            previous=h;events.append(e)
    return events


def append_event(event,path=JOURNAL):
    events=read_events(path)
    payload={**event,'seq':len(events)+1,'prev_hash':events[-1]['hash'] if events else ZERO_HASH}
    payload['hash']=_sha((payload['prev_hash']+'|'+_canon(payload)).encode('utf-8'))
    path.parent.mkdir(parents=True,exist_ok=True)
    with path.open('a',encoding='utf-8',newline='\n') as f:
        f.write(_canon(payload)+'\n');f.flush();os.fsync(f.fileno())
    return payload


def load_bars(path=CSV):
    if not path.is_file():return []
    with path.open(encoding='utf-8',newline='') as f:return list(csv.DictReader(f))


def _hour_minutes(when):return when.hour*60+when.minute


def can_forecast(when):
    m=_hour_minutes(when)
    return 8*60+5<=m<8*60+55 and when.weekday()<5


def can_settle(when):return _hour_minutes(when)>=17*60+10 and when.weekday()<5


def _id(day):return f'{SOURCE}:{MODEL}:{day}'


def _find(events,day,event):return next((x for x in events if x.get('day')==day and x.get('event')==event),None)


def forecast(when=None,csvpath=CSV,journal=JOURNAL,model_factory=None):
    """Emit a *new* prospective event, never a retroactive prediction.

    Model is fitted on completed session labels strictly prior to the forecast day.
    Raw classifier score is not calibrated profit probability or trade approval.
    """
    when=when or datetime.now(UTC)
    if when.tzinfo is None:raise ValueError('UTC timestamp required')
    when=when.astimezone(UTC)
    if not can_forecast(when):return {'status':'OUTSIDE_PROSPECTIVE_WINDOW','at_utc':when.isoformat()}
    day=when.date().isoformat();events=read_events(journal)
    old=_find(events,day,'FORECAST')
    if old:return {'status':'ALREADY_RECORDED','day':day,'direction':old['direction']}
    if _find(events,day,'MISSED'):return {'status':'DAY_ALREADY_MISSED','day':day}
    bars=load_bars(csvpath)
    dataset=sessions(bars,int(when.timestamp()))
    candidate=dataset['candidate']
    if not candidate or candidate['day']!=day:
        return {'status':'MISSING_CLOSED_ASIA_BARS','day':day,'audit':dataset['audit']}
    cutoff=int(candidate['cutoff'])
    # A model cannot use the same day's London return, even if the input file has it.
    train=[s for s in dataset['samples'] if s['cutoff']<cutoff and s['day']<day]
    if len(train)<MIN_SESSIONS:
        return {'status':'INSUFFICIENT_PAST_SESSIONS','day':day,'samples':len(train)}
    if len(set(s['y'] for s in train))<2:
        return {'status':'SINGLE_CLASS_HISTORY','day':day}
    if len(candidate['x'])!=len(COLUMNS) or any(not math.isfinite(float(x)) for x in candidate['x']):
        return {'status':'INVALID_FEATURES','day':day}
    model=model_factory() if model_factory else _model(MODEL)
    model.fit([s['x'] for s in train],[s['y'] for s in train])
    p=float(model.predict_proba([candidate['x']])[0][1])
    if not math.isfinite(p) or not 0<=p<=1:raise ValueError('Invalid model score')
    direction='LONG' if p>=0.55 else 'SHORT' if p<=0.45 else 'BEKLE'
    latest_ts=max(int(b['t']) for b in bars if int(b['t'])+HOUR<=int(when.timestamp()))
    # Require the final Asia hourly candle (07:00–08:00) in source history.
    if latest_ts<cutoff-HOUR:
        return {'status':'STALE_H1_SOURCE','day':day,'latest':utc_iso(latest_ts)}
    # Timestamp again AFTER training to avoid recording a late forecast as on-time.
    written_at=datetime.now(UTC) if model_factory is None else when
    if not can_forecast(written_at) or written_at.date()!=when.date():
        return {'status':'TRAINING_FINISHED_TOO_LATE','day':day}
    extra={}
    try:
        booster=model.get_booster()
        extra['model_sha256']=_sha(bytes(booster.save_raw(raw_format='json')))
    except (AttributeError,TypeError):
        extra['model_sha256']='UNAVAILABLE'
    event={
      'event':'FORECAST','day':day,'id':_id(day),'timestamp_utc':written_at.isoformat(),
      'session_cutoff_utc':utc_iso(cutoff), 'source':SOURCE_ID,'symbol':'XAUUSDT',
      'model':MODEL,'model_version':VERSION,'feature_version':FEAT_VERSION,
      'trained_through_day':train[-1]['day'],'train_sessions':len(train),
      'feature_sha256':_sha(_canon([round(float(v),10) for v in candidate['x']]).encode('utf-8')),
      'data_last_hour_start_utc':utc_iso(latest_ts),'github_source_sha':os.environ.get('GITHUB_SHA','LOCAL'),
      'direction':direction,'raw_up_score':round(p,6),'trade_decision':'BEKLE',
      'prediction_quality':'EXPERIMENTAL_UNCALIBRATED','consensus_vote':False,
      'live_order':False,'label':'London 08:00–17:00 UTC H1 direction',**extra}
    appended=append_event(event,journal)
    return {'status':'PROSPECTIVE_FORECAST_LOGGED','day':day,'direction':direction,
            'raw_up_score':round(p,6),'journal_hash':appended['hash'],'samples':len(train)}


def settle(when=None,csvpath=CSV,journal=JOURNAL,day=None):
    when=when or datetime.now(UTC)
    if when.tzinfo is None:raise ValueError('UTC timestamp required')
    when=when.astimezone(UTC)
    day=day or when.date().isoformat()
    target=datetime.fromisoformat(day).replace(tzinfo=UTC)
    if target.weekday()>=5 or when<target+timedelta(hours=17,minutes=10):
        return {'status':'OUTSIDE_SETTLEMENT_WINDOW','at_utc':when.isoformat(),'day':day}
    events=read_events(journal)
    if _find(events,day,'SETTLED') or _find(events,day,'MISSED'):
        return {'status':'ALREADY_SETTLED_OR_MISSED','day':day}
    forecast_event=_find(events,day,'FORECAST')
    completed=sessions(load_bars(csvpath),int(when.timestamp()))
    actual=next((x for x in completed['samples'] if x['day']==day),None)
    if actual is None:
        return {'status':'RESULT_BARS_INCOMPLETE','day':day,'audit':completed['audit']}
    if forecast_event is None:
        marker=append_event({'event':'MISSED','day':day,'timestamp_utc':when.isoformat(),
           'reason':'NO_PROSPECTIVE_FORECAST_IN_GITHUB_JOURNAL','trade_decision':'BEKLE'},journal)
        return {'status':'MISSED_DAY_MARKED','day':day,'hash':marker['hash']}
    # Forecast must truly pre-date London 17:00 and be in the allowed same-day window.
    t=datetime.fromisoformat(forecast_event['timestamp_utc']).astimezone(UTC)
    if not can_forecast(t) or t.date().isoformat()!=day:
        raise ValueError('Prospective timestamp invalid: refusing hindsight settlement')
    y=int(actual['y']);p=float(forecast_event['raw_up_score'])
    real='LONG' if y==1 else 'SHORT'
    guessed=forecast_event['direction']
    done={'event':'SETTLED','day':day,'forecast_hash':forecast_event['hash'],
       'timestamp_utc':when.isoformat(),'source':SOURCE_ID,'actual_direction':real,
       'london_return_pct':round(float(actual['london_return']),5),'brier':round((p-y)**2,6),
       'correct':bool(guessed==real) if guessed in ('LONG','SHORT') else None,
       'forecast_direction':guessed,'trade_decision':'BEKLE','live_order':False}
    appended=append_event(done,journal)
    return {'status':'SETTLED_PROSPECTIVE_FORECAST','day':day,'correct':done['correct'],
        'actual_direction':real,'hash':appended['hash']}


def summary(journal=JOURNAL,status_path=STATUS):
    events=read_events(journal)
    forecasts=[e for e in events if e['event']=='FORECAST']
    settled=[e for e in events if e['event']=='SETTLED']
    missed=[e for e in events if e['event']=='MISSED']
    directional=[e for e in settled if e['correct'] is not None]
    accuracy=round(100*sum(e['correct'] for e in directional)/len(directional),2) if directional else None
    brier=round(sum(e['brier'] for e in settled)/len(settled),6) if settled else None
    latest=forecasts[-1] if forecasts else None
    today=datetime.now(UTC).date().isoformat()
    # Be explicit that a historical/matured forecast is not a currently actionable view.
    last_event=events[-1]['timestamp_utc'] if events else None
    result={
      'version':VERSION,'status':'SHADOW_RESEARCH_ONLY','source':SOURCE_ID,
      'market':'Bitget USDT-FUTURES XAUUSDT','session_clock':'fixed_UTC_Asia_22_to_08_London_08_to_17',
      'orders_enabled':False,'consensus_vote':False,'live_trade_signal':False,
      'latest_forecast':{k:latest.get(k) for k in ('day','timestamp_utc','direction','raw_up_score','train_sessions','model','source','feature_version','trade_decision','model_sha256','hash')} if latest else None,
      'latest_forecast_is_today':bool(latest and latest['day']==today),
      'last_event_utc':last_event,'forecasts_recorded':len(forecasts),
      'sessions_settled':len(settled),'sessions_missed':len(missed),
      'directional_settled':len(directional),'directional_accuracy_pct':accuracy,
      'brier':brier,'min_forward_sessions_before_review':30,
      'future_validation_ready':bool(len(directional)>=30),
      'last_settlement':{k:settled[-1].get(k) for k in ('day','actual_direction','forecast_direction','correct','brier')} if settled else None,
      'journal_chain_head':events[-1]['hash'] if events else ZERO_HASH,
      'note':'Raw LONG/SHORT is experimental next-London session direction, NOT validated scalp signal or profitability probability. Trade decision stays BEKLE.',
    }
    status_path.parent.mkdir(parents=True,exist_ok=True)
    status_path.write_text(json.dumps(result,ensure_ascii=False,indent=2,sort_keys=True)+'\n',encoding='utf-8')
    return result


def public_status(symbol,root=ROOT):
    result={'status':'NO_SHADOW_RECORD','orders_enabled':False,'consensus_vote':False,'live_trade_signal':False}
    if symbol!='XAUUSDT':return {**result,'status':'SOURCE_NOT_AVAILABLE_FOR_SYMBOL'}
    path=Path(root)/'models'/'gold_shadow_v5_status.json'
    if not path.is_file():return result
    try:
        data=json.loads(path.read_text(encoding='utf-8'))
        if data.get('version')!=VERSION:return {**result,'status':'VERSION_MISMATCH'}
        if data.get('source')!=SOURCE_ID:return {**result,'status':'SOURCE_MISMATCH'}
        # A Git commit persists indefinitely; its previous 'today' flag must not.
        now=datetime.now(UTC)
        f=data.get('latest_forecast') or {}
        data['latest_forecast_is_today']=bool(f.get('day')==now.date().isoformat() and now.hour<17)
        allowed={'version','status','source','market','session_clock','latest_forecast','latest_forecast_is_today',
         'last_event_utc','forecasts_recorded','sessions_settled','sessions_missed','directional_settled',
         'directional_accuracy_pct','brier','min_forward_sessions_before_review',
         'future_validation_ready','last_settlement','note'}
        return {k:v for k,v in data.items() if k in allowed}|{'orders_enabled':False,
           'consensus_vote':False,'live_trade_signal':False}
    except (OSError,ValueError,TypeError):return {**result,'status':'INVALID_SHADOW_STATUS'}


def main():
    parser=argparse.ArgumentParser(description='Prospective shadow run, GitHub cloud only')
    parser.add_argument('command',choices=['auto','forecast','settle','status','check-journal'])
    args=parser.parse_args()
    if args.command=='check-journal':print('VALID_JOURNAL',len(read_events()));return
    result={}
    if args.command=='forecast':result=forecast()
    elif args.command=='settle':result=settle()
    elif args.command=='auto':
        now=datetime.now(UTC)
        # Recover settlements for already PRE-recorded predictions on later days.
        # This is legitimate: only outcomes are late; never create late forecasts.
        pending=[];events=read_events()
        finished={(e['day']) for e in events if e['event'] in ('SETTLED','MISSED')}
        for e in events:
            if e['event']=='FORECAST' and e['day'] not in finished:
                pending.append(e['day'])
        recovered=[]
        for old_day in sorted(set(pending)):
            target=datetime.fromisoformat(old_day).replace(tzinfo=UTC)
            if now>=target+timedelta(hours=17,minutes=10):
                recovered.append(settle(now,day=old_day))
        result={'recovered_settlements':recovered}
        if can_forecast(now):result['forecast']=forecast(now)
        elif can_settle(now):result['settlement']=settle(now)
        else:result['status']='NO_NEW_ACTION_OUTSIDE_SAFE_WINDOWS'
    if result:print('GOLD_SHADOW_V5',_canon(result))
    s=summary()
    print('GOLD_SHADOW_STATUS',_canon({k:s[k] for k in ('forecasts_recorded','sessions_settled','sessions_missed','journal_chain_head')}))

if __name__=='__main__':main()
