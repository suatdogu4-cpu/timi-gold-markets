"""GitHub Actions historical data pipeline for read-only GOLD SCALP PRO.

No trade endpoints, credentials or synthetic bars. Historical files are source-separated.
"""
from __future__ import annotations
import argparse
import csv
from datetime import datetime, timedelta, timezone
import glob
import json
from pathlib import Path
import sys
import time
from urllib.parse import urlencode
from urllib.request import Request,urlopen

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from gold_ml_core import PATHS,read_csv,write_csv,clean_bars,train_xgb,session_dataset

UTC=timezone.utc

def ensure_good(b):
    try:
        t=int(b['t']); o,h,l,c=[float(b[k]) for k in ('o','h','l','c')]
        return t>0 and t%3600==0 and min(o,h,l,c)>0 and l<=o<=h and l<=c<=h
    except (KeyError,ValueError,TypeError):return False

def parse_time(value):
    x=str(value).strip()
    try:
        f=float(x)
        return int(f/1000) if f>1e11 else int(f)
    except ValueError:
        d=datetime.fromisoformat(x.replace('Z','+00:00'))
        if d.tzinfo is None:d=d.replace(tzinfo=UTC)
        return int(d.timestamp())

def load_existing(symbol):
    rows=read_csv(ROOT/PATHS[symbol][0])
    return {int(x['t']):x for x in rows if ensure_good(x)}

def save_merged(symbol,mapping):
    vals=list(mapping.values());valid,bad=clean_bars(vals)
    write_csv(ROOT/PATHS[symbol][0],valid)
    return {'saved':len(valid),'invalid_or_unclosed':bad,
            'earliest':datetime.fromtimestamp(valid[0]['t'],UTC).isoformat() if valid else None,
            'latest':datetime.fromtimestamp(valid[-1]['t'],UTC).isoformat() if valid else None}

def query(url,tries=4):
    last=None
    for attempt in range(tries):
        try:
            with urlopen(Request(url,headers={'User-Agent':'GoldQuantMLResearch/1.0'}),timeout=25) as r:
                j=json.load(r)
            if str(j.get('code'))!='00000':raise RuntimeError(f'Bitget error: {j.get("code")} {j.get("msg")}')
            return j.get('data',[])
        except Exception as e:
            last=e
            if attempt<tries-1:time.sleep(min(2**attempt,8))
    raise RuntimeError('Bitget data fetch failed: '+str(last)[:200])

def collect_bitget(pages=180):
    symbol='XAUUSDT';existing=load_existing(symbol)
    last_existing=max(existing) if existing else 0
    now=int(time.time());end_ms=now*1000
    # Incremental overlap, never reset previously saved history.
    stop=(last_existing-7*86400) if existing else 0
    added=0;requests=0;oldest_seen=None;why='limit_reached'
    for _ in range(pages):
        start_ms=max(0,end_ms-96*3600*1000)  # <=100 H1 points: no ambiguous 90-day paging skips
        params={'category':'USDT-FUTURES','symbol':symbol,'interval':'1H',
                'type':'market','startTime':str(start_ms),'endTime':str(end_ms),'limit':'100'}
        url='https://api.bitget.com/api/v3/market/history-candles?'+urlencode(params)
        rows=query(url);requests+=1
        if not isinstance(rows,list) or not rows:
            why='no_older_data_or_source_gap';break
        batch={}
        for r in rows:
            try:
                t=int(r[0])//1000
                bar={'t':t,'o':r[1],'h':r[2],'l':r[3],'c':r[4],'v':r[5]}
                if t*1000>=end_ms or t*1000<start_ms or not ensure_good(bar) or t+3600>now:continue
                batch[t]=bar
            except (IndexError,ValueError,TypeError):continue
        if not batch:
            why='no_valid_bars';break
        oldest=min(batch)
        if oldest_seen is not None and oldest>=oldest_seen:
            why='pagination_no_progress';break
        oldest_seen=oldest
        for t,b in batch.items():
            if t not in existing:added+=1
            existing[t]=b
        if stop and oldest<=stop:
            why='caught_up_to_saved_history';break
        next_end_ms=oldest*1000-1
        if next_end_ms>=end_ms:
            why='pagination_not_descending';break
        end_ms=next_end_ms
        time.sleep(.25)
    summary=save_merged(symbol,existing)
    summary.update({'source':'Bitget public USDT-FUTURES market H1',
                    'requests':requests,'new_bars':added,'end_reason':why})
    print('BITGET_COLLECTION',json.dumps(summary,ensure_ascii=False))
    return summary

def import_dukascopy(pattern):
    # dukascopy-node output: timestamp,open,high,low,close,volume (UTC BID)
    files=glob.glob(pattern)
    if not files:
        print('DUKASCOPY_IMPORT_SKIPPED: no matching CSV; do not claim spot training succeeded')
        return False
    symbol='XAUUSD';existing=load_existing(symbol);incoming=0
    for file in files:
        with open(file,encoding='utf-8-sig',newline='') as f:
            reader=csv.DictReader(f)
            for r in reader:
                try:
                    t=parse_time(r.get('timestamp') or r.get('Date') or r.get('date') or '')
                    if t%3600:continue
                    bar={'t':t,'o':r.get('open') or r.get('Open'),
                         'h':r.get('high') or r.get('High'),'l':r.get('low') or r.get('Low'),
                         'c':r.get('close') or r.get('Close'),'v':r.get('volume') or r.get('Volume') or 0}
                    if ensure_good(bar):existing[t]=bar;incoming+=1
                except (ValueError,TypeError):continue
    result=save_merged(symbol,existing)
    result.update({'source':'Dukascopy xauusd BID H1 via dukascopy-node','parsed_bars':incoming,'files':len(files)})
    print('DUKASCOPY_IMPORT',json.dumps(result,ensure_ascii=False))
    return True

def train(symbol):
    csvpath,modelpath=PATHS[symbol]
    rows=read_csv(ROOT/csvpath)
    model,meta=train_xgb(rows,symbol)
    outpath=ROOT/modelpath
    outpath.parent.mkdir(parents=True,exist_ok=True)
    statuspath=outpath.with_suffix('.status.json')
    statuspath.write_text(json.dumps(meta,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    if model:
        outpath.write_text(json.dumps(model,ensure_ascii=False,separators=(',',':'))+'\n',encoding='utf-8')
        print('TRAINED_MODEL',symbol,meta.get('approved'),meta['test_accuracy_pct'],meta['test_majority_pct'])
    else:
        if outpath.exists():outpath.unlink() # Never leave older artifact when current input fails quality gate.
        print('MODEL_UNAVAILABLE',symbol,'; '.join(meta.get('reasons',[])))
    return meta

def range_dukascopy():
    existing=load_existing('XAUUSD'); today=datetime.now(UTC).date()
    if existing:
        start=datetime.fromtimestamp(max(existing),UTC).date()-timedelta(days=7)
    else:start=today-timedelta(days=430)
    print(start.isoformat(),today.isoformat())

def main():
    p=argparse.ArgumentParser()
    sub=p.add_subparsers(dest='cmd',required=True)
    c=sub.add_parser('collect-bitget');c.add_argument('--pages',type=int,default=180)
    i=sub.add_parser('import-dukascopy');i.add_argument('--glob',required=True)
    t=sub.add_parser('train');t.add_argument('--symbol',choices=['XAUUSD','XAUUSDT'],required=True)
    sub.add_parser('dukascopy-range')
    sub.add_parser('status')
    a=p.parse_args()
    if a.cmd=='collect-bitget':collect_bitget(max(1,min(250,a.pages)))
    if a.cmd=='import-dukascopy':import_dukascopy(a.glob)
    if a.cmd=='train':train(a.symbol)
    if a.cmd=='dukascopy-range':range_dukascopy()
    if a.cmd=='status':
        for symbol in PATHS:
            file=ROOT/PATHS[symbol][0];model=ROOT/PATHS[symbol][1]
            rows=read_csv(file);valid,errors=clean_bars(rows)
            print(json.dumps({'symbol':symbol,'valid_hourly':len(valid),'rejected':errors,
                              'completed_session_pairs':len(session_dataset(valid)['rows']),
                              'model_exists':model.exists()},ensure_ascii=False))

if __name__=='__main__':main()
