"""GOLD SCALP V6 - read-only XAUUSDT closed 1m historical source archive.
Bitget USDT-FUTURES and Binance USD-M must never be mixed. No trade API.
Run on GitHub Actions; compressed archives are Git tracked.
"""
from __future__ import annotations
import argparse, csv, gzip, hashlib, io, json, math, os, re, time, zipfile
from datetime import datetime, date, timedelta, timezone
from pathlib import Path
from urllib.parse import urlencode
from urllib.request import urlopen, Request
from urllib.error import HTTPError, URLError

UTC = timezone.utc
ROOT = Path(__file__).resolve().parent
ARCHIVE = ROOT / 'datasets/gold_scalp_v6'
FIELD = ('t','o','h','l','c','v')
SYMBOL = 'XAUUSDT'
SOURCES = {'bitget': 'bitget_usdt_futures_trade_1m', 'binance':'binance_usdm_futures_trade_1m'}
BASE = 'https://data.binance.vision/data/futures/um'
MAX_ZIP = 24 * 1024 * 1024
MAX_RAW = 80 * 1024 * 1024
NOW = lambda: int(time.time())

def checked(row, now_s=None):
    try:
        now_s = NOW() if now_s is None else now_s
        t = int(row['t']); p = [float(row[x]) for x in 'ohlcv']
        o,h,l,c,v=p
        if not(t>0 and t%60 == 0 and t+60<=now_s and all(map(math.isfinite,p))
                and min(o,h,l,c)>0 and v>=0 and l<=o<=h and l<=c<=h): return None
        return {'t':t,'o':o,'h':h,'l':l,'c':c,'v':v}
    except (KeyError,ValueError,TypeError,OverflowError):return None

def read_history(source,now_s=None):
    path=ARCHIVE/f'{source}_xauusdt_1m.csv.gz'; rows={}
    if not path.exists():return rows
    with gzip.open(path,'rt',newline='',encoding='utf-8') as f:
        for raw in csv.DictReader(f):
            b=checked(raw,now_s)
            if b is not None:rows[b['t']]=b
    return rows

def write_history(source, rows, now_s=None, keep_days=100):
    """Atomic write; preserve distinct market source; bound Git file growth."""
    ARCHIVE.mkdir(parents=True,exist_ok=True)
    now_s=NOW() if now_s is None else now_s
    since=now_s-keep_days*86400
    valid={t:b for t,b in rows.items() if t>=since and checked(b,now_s) is not None}
    path=ARCHIVE/f'{source}_xauusdt_1m.csv.gz';tmp=path.with_suffix('.part')
    with gzip.open(tmp,'wt',newline='',encoding='utf-8',compresslevel=6) as f:
        writer=csv.DictWriter(f,fieldnames=FIELD);writer.writeheader()
        for t in sorted(valid):writer.writerow(valid[t])
    os.replace(tmp,path)
    return {'source_key':source,'source_id':SOURCES[source],'symbol':SYMBOL,
            'bars':len(valid),'first_utc':datetime.fromtimestamp(min(valid),UTC).isoformat() if valid else None,
            'last_utc':datetime.fromtimestamp(max(valid),UTC).isoformat() if valid else None,
            'sha256_gzip':hashlib.sha256(path.read_bytes()).hexdigest(),
            'bytes_gzip':path.stat().st_size}

def get_bytes(url,max_bytes=MAX_ZIP,tries=2):
    if not (url.startswith(BASE+'/') or url.startswith('https://api.bitget.com/api/v3/market/history-candles?')):
        raise ValueError('Unapproved data host')
    last=None
    for attempt in range(tries):
        try:
            req=Request(url,headers={'User-Agent':'GoldScalpResearchV6/1.0','Accept':'*/*'})
            with urlopen(req,timeout=22) as f:
                length=f.headers.get('Content-Length')
                if length and int(length)>max_bytes:raise ValueError('File exceeds size limit')
                b=f.read(max_bytes+1)
                if len(b)>max_bytes:raise ValueError('File exceeds size limit')
                return b
        except HTTPError as e:
            if e.code==404:return None
            if e.code in (401,403,451):raise RuntimeError(f'Source unavailable HTTP {e.code}') from e
            last=e
        except (URLError,OSError,TimeoutError) as e:last=e
        if attempt+1<tries:time.sleep(1.4*(attempt+1))
    raise RuntimeError(f'Download failed: {type(last).__name__}')

def parse_binance_zip(blob,expected_name,now_s):
    with zipfile.ZipFile(io.BytesIO(blob)) as z:
        members=[f for f in z.infolist() if f.filename.endswith('.csv')]
        expected_csv=expected_name.replace('.zip','.csv')
        if len(members)!=1 or Path(members[0].filename).name!=expected_csv or members[0].file_size>MAX_RAW:
            raise ValueError('Unexpected archive CSV manifest')
        csv_bytes=z.read(members[0])
        if len(csv_bytes)>MAX_RAW:raise ValueError('Expanded archive too large')
    out={}
    for row in csv.reader(io.StringIO(csv_bytes.decode('utf-8-sig'))):
        if len(row)<6:continue
        try:
            raw_t=int(row[0]);t=raw_t//1000000 if raw_t>=10**14 else raw_t//1000 if raw_t>=10**11 else raw_t
            b=checked({'t':t,'o':row[1],'h':row[2],'l':row[3],'c':row[4],'v':row[5]},now_s)
            if b:out[t]=b
        except (ValueError,IndexError,OverflowError):continue
    return out

def checksum_verified_zip(url,now_s):
    raw_checksum=get_bytes(url+'.CHECKSUM',10000)
    if raw_checksum is None:return None,'CHECKSUM_NOT_PUBLISHED'
    fname=url.rsplit('/',1)[-1];expected=None
    for line in raw_checksum.decode('utf-8-sig').splitlines():
        parts=line.strip().split()
        if len(parts)>=2 and parts[-1].lstrip('*')==fname and re.fullmatch('[a-fA-F0-9]{64}',parts[0]):
            expected=parts[0].lower();break
    if not expected:raise ValueError('Checksum file malformed')
    blob=get_bytes(url)
    if blob is None:return None,'ZIP_NOT_PUBLISHED'
    if hashlib.sha256(blob).hexdigest()!=expected:raise ValueError('SHA256 checksum mismatch')
    return parse_binance_zip(blob,fname,now_s),'VERIFIED'

def month_first(d):return date(d.year,d.month,1)
def next_month(d):return date(d.year+(d.month==12),d.month%12+1,1)

def binance_packages(now, lookback_days=60):
    today=now.date();since=max(date(2026,1,5),today-timedelta(days=lookback_days))
    m=month_first(since);this_month=month_first(today)
    result=[]
    while m<this_month:
        url=f'{BASE}/monthly/klines/{SYMBOL}/1m/{SYMBOL}-1m-{m:%Y-%m}.zip'
        result.append((m.isoformat()[:7],url));m=next_month(m)
    d=max(since,this_month)
    while d<today:
        url=f'{BASE}/daily/klines/{SYMBOL}/1m/{SYMBOL}-1m-{d:%Y-%m-%d}.zip'
        result.append((d.isoformat(),url));d+=timedelta(days=1)
    return result

def collect_binance(lookback_days=60,now=None):
    now=now or datetime.now(UTC);now_s=int(now.timestamp())
    existing=read_history('binance',now_s);stats={'packages_seen':0,'verified':0,'unpublished':0,'errors':[]}
    for label,url in binance_packages(now,lookback_days):
        try:
            batch,status=checksum_verified_zip(url,now_s);stats['packages_seen']+=1
            if batch is None:stats['unpublished']+=1;continue
            # overlapping daily/monthly data must agree; never silently rewrite OHLC.
            overlap=[t for t,b in batch.items() if t in existing and any(
                abs(existing[t][k]-b[k])>max(1e-8,abs(b[k])*1e-8) for k in 'ohlc')]
            if overlap:
                stats['errors'].append(f'{label}:OHLC_CONFLICT:{len(overlap)}');continue
            existing.update(batch);stats['verified']+=1
        except (RuntimeError,ValueError,zipfile.BadZipFile,UnicodeError) as e:
            stats['errors'].append(f'{label}:{str(e)[:85]}')
            if 'HTTP 451' in str(e) or 'HTTP 403' in str(e):break
    saved=write_history('binance',existing,now_s)
    return {**saved,**stats,'status':('OK' if stats['verified'] and not stats['errors'] else 'PARTIAL' if saved['bars'] else 'UNAVAILABLE')}

def query_bitget(start_s,end_s):
    q=urlencode({'category':'USDT-FUTURES','symbol':SYMBOL,'interval':'1m','type':'market',
                 'startTime':str(start_s*1000),'endTime':str(end_s*1000),'limit':'100'})
    blob=get_bytes('https://api.bitget.com/api/v3/market/history-candles?'+q,max_bytes=256_000,tries=3)
    if blob is None:raise RuntimeError('Bitget history missing')
    payload=json.loads(blob)
    if str(payload.get('code'))!='00000':raise RuntimeError('Bitget returned '+str(payload.get('code')))
    if not isinstance(payload.get('data'),list):raise ValueError('Bad Bitget response')
    return payload['data']

def collect_bitget(max_pages=480,lookback_days=45,now_s=None):
    now_s=NOW() if now_s is None else now_s
    saved=read_history('bitget',now_s);limit=now_s-lookback_days*86400
    # Backward incremental paging: if an older gap exists, each daily run extends it.
    newest=max(saved) if saved else 0;oldest=min(saved) if saved else 0
    # Always refresh newest minutes first, even while historical backfill remains.
    pages=0;added=0;error=None;no_progress=0
    if newest:
        recent_end=now_s
        for _ in range(min(8,max_pages//3)):
            if recent_end<=newest-3600:break
            recent_start=max(newest-7200,recent_end-101*60)
            try:recent_raw=query_bitget(recent_start,recent_end)
            except (RuntimeError,URLError,ValueError) as e:error=str(e)[:180];break
            pages+=1;times=[]
            for item in recent_raw:
                try:
                    t=int(item[0])//1000
                    b=checked({'t':t,'o':item[1],'h':item[2],'l':item[3],'c':item[4],'v':item[5]},now_s)
                    if b and recent_start-60<=t<recent_end:
                        if t not in saved:added+=1
                        saved[t]=b;times.append(t)
                except (ValueError,IndexError,TypeError):continue
            if not times:break
            recent_end=min(times)-1
            time.sleep(.12)
    if newest and oldest>limit:
        end_s=oldest-1
        mode='backfill'
    elif newest:
        end_s=now_s;mode='refresh'
    else:
        end_s=now_s;mode='initial'
    while pages<max_pages and end_s>limit:
        start_s=max(limit,end_s-101*60)
        try:raw=query_bitget(start_s,end_s)
        except (RuntimeError,URLError,ValueError) as e:error=str(e)[:180];break
        pages+=1
        chunk={}
        for item in raw:
            try:
                t=int(item[0])//1000
                b=checked({'t':t,'o':item[1],'h':item[2],'l':item[3],'c':item[4],'v':item[5]},now_s)
                if b and start_s-60<=t<end_s:chunk[t]=b
            except (IndexError,ValueError,TypeError):continue
        if not chunk:break
        first=min(chunk)
        if first>=end_s:no_progress+=1;break
        for t,b in chunk.items():
            if t not in saved:added+=1;saved[t]=b
        end_s=first-1
        if mode=='refresh' and newest and first<=newest-2*86400:break
        time.sleep(.16)
    result=write_history('bitget',saved,now_s)
    return {**result,'status':'PARTIAL' if error else 'OK' if pages else 'NO_MORE_BARS',
            'pages':pages,'added':added,'mode':mode,'error':error}

def inspect(source,now_s=None):
    bars=read_history(source,now_s);st=sorted(bars)
    gaps=sum((b-a)//60-1 for a,b in zip(st,st[1:]) if b-a>60)
    return {'bars':len(st),'missing_minutes_between_extremes':gaps,
            'first':datetime.fromtimestamp(st[0],UTC).isoformat() if st else None,
            'last':datetime.fromtimestamp(st[-1],UTC).isoformat() if st else None}

def main():
    p=argparse.ArgumentParser();p.add_argument('command',choices=('collect','audit'))
    p.add_argument('--pages',type=int,default=480);p.add_argument('--days',type=int,default=60)
    a=p.parse_args();out={'generated_at_utc':datetime.now(UTC).isoformat(),'market':'XAUUSDT',
                            'no_orders':True,'sources':{}}
    if a.command=='collect':
        try:out['sources']['binance']=collect_binance(lookback_days=min(100,max(7,a.days)))
        except Exception as e:out['sources']['binance']={'status':'ERROR','error':str(e)[:180]}
        try:out['sources']['bitget']=collect_bitget(max_pages=min(1400,max(1,a.pages)),lookback_days=min(100,max(7,a.days)))
        except Exception as e:out['sources']['bitget']={'status':'ERROR','error':str(e)[:180]}
    for name in SOURCES:out['sources'].setdefault(name,{}).update(inspect(name))
    ARCHIVE.mkdir(parents=True,exist_ok=True)
    (ARCHIVE/'manifest.json').write_text(json.dumps(out,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    print('GOLD_V6_SOURCE_AUDIT',json.dumps(out,ensure_ascii=False))
    # The first job must not claim success with zero historical rows.
    if all(info['bars']==0 for info in out['sources'].values()):raise SystemExit('No verified 1m history in either source')

if __name__=='__main__':main()
