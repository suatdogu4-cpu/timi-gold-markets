"""GOLD ML v3: Binance futures historical H1 + durable Git snapshot + 3-model audit.
No private keys and no trading endpoints. Store each source in its own file.
"""
from __future__ import annotations
import argparse
from datetime import datetime,timezone
import csv
import gzip
import hashlib
import io
import json
from pathlib import Path
import sys
import time
from urllib.error import HTTPError,URLError
from urllib.request import Request,urlopen
from urllib.parse import urlencode

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from gold_ml_v3 import SOURCES,FEAT_VERSION,compare_models,valid_bars
UTC=timezone.utc
DATA={
    'bitget_xauusdt':ROOT/'data/bitget_xauusdt_h1.csv',
    'binance_xauusdt':ROOT/'data/binance_xauusdt_h1.csv',
    'dukascopy_xauusd':ROOT/'data/dukascopy_xauusd_h1.csv',
}
ARCHIVE=ROOT/'datasets'/'gold_ml'
MODEL_REPORT=ROOT/'models'/'gold_ml_v3_comparison.json'
SOURCE_STATUS=ROOT/'models'/'gold_ml_v3_source_health.json'


def csv_rows(path):
    if not path.exists():return []
    with path.open('r',encoding='utf-8',newline='') as f:return list(csv.DictReader(f))


def csv_dump(rows):
    f=io.StringIO(newline='');writer=csv.DictWriter(f,fieldnames=['t','o','h','l','c','v'],lineterminator='\n')
    writer.writeheader()
    for r in rows:writer.writerow({k:r[k] for k in ['t','o','h','l','c','v']})
    return f.getvalue().encode('utf-8')


def save_csv(path,rows):
    rows=valid_bars(rows)
    path.parent.mkdir(parents=True,exist_ok=True)
    path.write_bytes(csv_dump(rows))
    return rows


def restore_archives():
    count={}
    for key,path in DATA.items():
        snapshot=ARCHIVE/f'{key}_h1.csv.gz'
        if not snapshot.exists():continue
        try:
            raw=gzip.decompress(snapshot.read_bytes())
            if len(raw)>24*1024*1024:raise ValueError('Oversized history archive')
            parsed=list(csv.DictReader(io.StringIO(raw.decode('utf-8'))))
            closed=valid_bars(parsed)
            if not closed:raise ValueError('Archive has no valid closed hourly data')
            previous=valid_bars(csv_rows(path)) if path.exists() else []
            joined={v['t']:v for v in closed}
            joined.update({v['t']:v for v in previous})
            saved=save_csv(path,list(joined.values()))
            count[key]={'archive':len(closed),'current':len(saved)}
        except (OSError,ValueError,UnicodeError,EOFError) as e:
            raise RuntimeError(f'Corrupt durable archive {key}: {str(e)[:120]}') from e
    print('DURABLE_ARCHIVE_RESTORE',json.dumps(count,ensure_ascii=False))
    return count


def _get_json(url, tries=3):
    failure=None
    for i in range(tries):
        try:
            with urlopen(Request(url,headers={'User-Agent':'GoldScalpPro-Research/3.0'}),timeout=25) as resp:
                return json.load(resp)
        except (HTTPError,URLError,TimeoutError,ValueError,OSError) as e:
            failure=e
            if i+1<tries:time.sleep(2**i)
    raise RuntimeError('Binance public API unavailable '+str(failure)[:200])


def collect_binance(pages=16):
    """Download only Binance USD-M XAUUSDT perpetual trade klines; never spot PAXG/XAUT.
    Does not fabricate or borrow bars from Bitget if Binance geo-blocks the runner.
    """
    path=DATA['binance_xauusdt'];now=int(time.time())
    existing={b['t']:b for b in valid_bars(csv_rows(path),now)}
    last=max(existing) if existing else None
    stop=last-7*86400 if last else 0
    end_ms=now*1000
    seen=None;reqs=0;reason='max_pages'
    for _ in range(max(1,min(pages,50))):
        params=urlencode({'symbol':'XAUUSDT','interval':'1h','endTime':end_ms,'limit':1000})
        try:
            response=_get_json('https://fapi.binance.com/fapi/v1/klines?'+params)
        except RuntimeError as exc:
            # Official Binance public Vision files only; stop on archive 403/451.
            # No proxies, other exchanges, synthetic candles or model overclaims.
            from tools.binance_vision_archive import collect_official_archive
            return collect_official_archive(path, ROOT, rest_error=str(exc))
        if isinstance(response,dict):
            raise RuntimeError('Binance endpoint rejected contract: '+str(response.get('msg') or response)[:150])
        reqs+=1
        if not response:reason='no_more_candles';break
        batch={}
        for row in response:
            try:
                ts=int(row[0])//1000
                b={'t':ts,'o':float(row[1]),'h':float(row[2]),'l':float(row[3]),
                   'c':float(row[4]),'v':float(row[5])}
                if ts+3600<=now and ts*1000<end_ms:batch[ts]=b
            except (IndexError,ValueError,TypeError):continue
        valid=valid_bars(list(batch.values()),now)
        if not valid:reason='no_valid_closed_candles';break
        oldest=valid[0]['t']
        if seen is not None and oldest>=seen:reason='pagination_not_descending';break
        seen=oldest
        for b in valid:existing[b['t']]=b
        if stop and oldest<=stop:reason='caught_up_to_archive';break
        end_ms=oldest*1000-1
        time.sleep(.12)
    saved=save_csv(path,list(existing.values()))
    result={'source':'binance_usdm_trade_h1','symbol':'XAUUSDT','h1_saved':len(saved),
        'requests':reqs,'reason':reason,
        'earliest':datetime.fromtimestamp(saved[0]['t'],UTC).isoformat() if saved else None,
        'latest':datetime.fromtimestamp(saved[-1]['t'],UTC).isoformat() if saved else None}
    from tools.binance_vision_archive import record_rest_success
    record_rest_success(ROOT,result)
    print('BINANCE_HISTORY',json.dumps(result,ensure_ascii=False))
    return result


def archive_data():
    ARCHIVE.mkdir(parents=True,exist_ok=True)
    now=datetime.now(UTC).isoformat()
    reports={}
    for key,path in DATA.items():
        rows=valid_bars(csv_rows(path))
        if not rows:
            reports[key]={'status':'NO_VALID_DATA'};continue
        content=csv_dump(rows)
        # mtime=0 makes compression deterministic and avoids meaningless git diffs.
        target=ARCHIVE/f'{key}_h1.csv.gz'
        packed=gzip.compress(content,compresslevel=8,mtime=0)
        target.write_bytes(packed)
        reports[key]={'status':'SNAPSHOTTED','rows':len(rows),'sha256_uncompressed':hashlib.sha256(content).hexdigest(),
            'bytes_compressed':len(packed),'first_h1_utc':datetime.fromtimestamp(rows[0]['t'],UTC).isoformat(),
            'last_h1_utc':datetime.fromtimestamp(rows[-1]['t'],UTC).isoformat()}
    status={'version':FEAT_VERSION,'created_at_utc':now,
        'storage_type':'git_tracked_gzip_files_in_public_repository',
        'artifacts_only_backup':False,'files':reports,
        'notice':'Permanence requires a successful git commit and independent offsite backup; public OHLC only.'}
    (ARCHIVE/'manifest.json').write_text(json.dumps(status,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    print('DURABLE_ARCHIVE_SNAPSHOT',json.dumps(reports,ensure_ascii=False))
    return status


def train_comparison():
    all_reports={};errors={}
    for key in SOURCES:
        bars=csv_rows(DATA[key])
        try:
            r=compare_models(bars,key)
            all_reports[key]=r
            chosen=r.get('selected_by_validation')
            print('MODEL_COMPARISON',json.dumps({'source':key,'sessions':r['samples'],
                'selected':chosen,'retrospective_gate':r['approved'],
                'holdout':r['models'].get(chosen,{}).get('final_holdout'),
                'live_prediction':False},ensure_ascii=False))
        except Exception as e:
            all_reports[key]={'source_key':key,'version':FEAT_VERSION,'status':'ERROR',
                'reason':f'{type(e).__name__}: {str(e)[:150]}',
                'approved':False,'live_prediction_enabled':False,'consensus_vote':False}
            errors[key]=all_reports[key]['reason']
    try:
        source_health=json.loads(SOURCE_STATUS.read_text(encoding='utf-8')) if SOURCE_STATUS.exists() else {}
        if not isinstance(source_health,dict):source_health={}
    except (OSError,ValueError):source_health={}
    manifest=ARCHIVE/'manifest.json'
    storage=json.loads(manifest.read_text(encoding='utf-8')) if manifest.exists() else {'storage_type':'NOT_YET_ARCHIVED'}
    report={'version':FEAT_VERSION,'generated_at_utc':datetime.now(UTC).isoformat(),
        'sources':all_reports,'storage':storage,'source_health':source_health,'errors':errors,'no_trade':True,'no_live_prediction':True}
    MODEL_REPORT.parent.mkdir(parents=True,exist_ok=True)
    MODEL_REPORT.write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    print('REPORT_WRITTEN',str(MODEL_REPORT),'sources',len(all_reports),'errors',len(errors))
    if len(errors)==len(SOURCES):raise RuntimeError('All model comparisons failed')
    return report


def main():
    p=argparse.ArgumentParser()
    sub=p.add_subparsers(dest='cmd',required=True)
    sub.add_parser('restore')
    sub.add_parser('archive')
    c=sub.add_parser('collect-binance');c.add_argument('--pages',type=int,default=16)
    sub.add_parser('compare')
    sub.add_parser('status')
    a=p.parse_args()
    if a.cmd=='restore':restore_archives()
    if a.cmd=='archive':archive_data()
    if a.cmd=='collect-binance':collect_binance(a.pages)
    if a.cmd=='compare':train_comparison()
    if a.cmd=='status':
        for k,pth in DATA.items():
            r=valid_bars(csv_rows(pth))
            print('SOURCE_STATUS',json.dumps({'source':k,'valid_closed_h1':len(r)},ensure_ascii=False))

if __name__=='__main__':main()
