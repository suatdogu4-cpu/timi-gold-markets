"""Read-only official Binance USD-M XAUUSDT H1 *trade* kline archive fallback.

Does not use proxies, VPNs, exchange keys, other symbols, spot, mark-price,
index-price, or Bitget candles. A 403/451 from the official archive is final.
Only verified, closed, on-hour rows enter Binance's dedicated CSV.
"""
from __future__ import annotations

import csv
from datetime import date, datetime, timedelta, timezone
import hashlib
import io
import json
import math
from pathlib import Path
import re
import time
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen
import zipfile

UTC = timezone.utc
BASE = 'https://data.binance.vision/data/futures/um'
SYMBOL = 'XAUUSDT'
INTERVAL = '1h'
FIRST_DAY = date(2026, 1, 5)  # Binance official TradFi listing day
MAX_ZIP_BYTES = 16 * 1024 * 1024
MAX_CSV_BYTES = 24 * 1024 * 1024
COLUMNS = ('t', 'o', 'h', 'l', 'c', 'v')


class Unavailable(Exception):
    def __init__(self, code, detail=''):
        self.code = str(code)
        super().__init__(detail or str(code))


def fetch_official(url: str) -> bytes | None:
    """Returns None only for 404. Raises on access restrictions/other errors."""
    if not url.startswith(BASE + '/') or not (url.endswith('.zip') or url.endswith('.zip.CHECKSUM')):
        raise ValueError('Archive host/path not permitted')
    request = Request(url, headers={'User-Agent': 'GoldScalpPro-PublicResearch/4.0'})
    try:
        with urlopen(request, timeout=18) as response:
            length = response.headers.get('Content-Length')
            if length and int(length) > MAX_ZIP_BYTES:
                raise Unavailable('OVERSIZED', 'Archive larger than allowed')
            raw = response.read(MAX_ZIP_BYTES + 1)
            if len(raw) > MAX_ZIP_BYTES:
                raise Unavailable('OVERSIZED', 'Archive larger than allowed')
            return raw
    except HTTPError as exc:
        if exc.code == 404:
            return None
        raise Unavailable(exc.code, f'official archive returned HTTP {exc.code}') from exc
    except (URLError, TimeoutError, OSError) as exc:
        raise Unavailable('NETWORK', type(exc).__name__) from exc


def months_between(first: date, last: date):
    cur = date(first.year, first.month, 1)
    while cur <= last:
        yield cur
        cur = date(cur.year + (cur.month == 12), cur.month % 12 + 1, 1)


def packages(now: datetime):
    """All completed months from listing; this month's completed days only.

    The dataset has existed since Jan 2026, so initial backfill is bounded.
    Future years are capped to 18 completed months for controlled daily jobs.
    """
    today = now.date()
    if today <= FIRST_DAY:
        return []
    current_month = date(today.year, today.month, 1)
    monthly = [m for m in months_between(FIRST_DAY, current_month - timedelta(days=1))]
    monthly = monthly[-18:]
    prefix = f'{BASE}/monthly/klines/{SYMBOL}/{INTERVAL}/'
    out = [('monthly', m.isoformat()[:7], prefix + f'{SYMBOL}-{INTERVAL}-{m:%Y-%m}.zip') for m in monthly]
    d = max(current_month, FIRST_DAY)
    last_day = today - timedelta(days=1)  # today is not complete
    prefix = f'{BASE}/daily/klines/{SYMBOL}/{INTERVAL}/'
    while d <= last_day and len(out) < 65:
        out.append(('daily', d.isoformat(), prefix + f'{SYMBOL}-{INTERVAL}-{d:%Y-%m-%d}.zip'))
        d += timedelta(days=1)
    return out


def parse_h1_zip(data: bytes, filename: str, now_s: int):
    try:
        with zipfile.ZipFile(io.BytesIO(data)) as z:
            items = [m for m in z.infolist() if m.filename.endswith('.csv')]
            if len(items) != 1 or items[0].file_size > MAX_CSV_BYTES:
                raise Unavailable('BAD_ZIP', 'Unexpected number/size of CSV files')
            if items[0].filename.split('/')[-1] != filename.replace('.zip', '.csv'):
                raise Unavailable('BAD_ZIP', 'Unexpected CSV filename')
            raw = z.read(items[0], pwd=None)
            if len(raw) > MAX_CSV_BYTES:
                raise Unavailable('BAD_ZIP', 'CSV too large')
    except (zipfile.BadZipFile, RuntimeError, UnicodeError, OSError) as exc:
        raise Unavailable('BAD_ZIP', type(exc).__name__) from exc
    try:
        decoded=raw.decode('utf-8-sig')
    except UnicodeDecodeError as exc:
        raise Unavailable('BAD_ZIP', 'Invalid CSV encoding') from exc
    candles = {}
    for line in csv.reader(io.StringIO(decoded)):
        if len(line) < 6:
            continue
        try:
            t_raw = int(line[0].strip())
            if t_raw > 10**14:  # microseconds (defensive)
                t = t_raw // 1_000_000
            elif t_raw > 10**11:  # Binance futures normally milliseconds
                t = t_raw // 1000
            else:
                t = t_raw
            o, h, l, c, v = (float(line[i]) for i in range(1, 6))
            if (t < 1767571200 or t % 3600 != 0 or t + 3600 > now_s or
                not all(map(math.isfinite, (o, h, l, c, v))) or
                min(o, h, l, c) <= 0 or v < 0 or
                not (l <= o <= h and l <= c <= h)):
                continue
            candles[t] = dict(t=t, o=o, h=h, l=l, c=c, v=v)
        except (ValueError, OverflowError, TypeError):
            continue  # explicit CSV headers and malformed rows are not fabricated
    return list(candles.values())


def _validated_zip(url, now_s: int):
    checksum_text = fetch_official(url + '.CHECKSUM')
    if checksum_text is None:
        return None, 'NO_CHECKSUM'
    name = url.rsplit('/', 1)[-1]
    hashes = re.findall(rb'(?m)^\s*([a-fA-F0-9]{64})\s+\*?([^\r\n]+?)\s*$', checksum_text)
    expected = None
    for digest, item_name in hashes:
        if item_name.decode('utf-8', 'replace').strip() == name:
            expected = digest.decode().lower()
            break
    if not expected:
        raise Unavailable('BAD_CHECKSUM', 'Checksum file missing expected zip name')
    zip_blob = fetch_official(url)
    if zip_blob is None:
        return None, 'ZIP_404'
    if hashlib.sha256(zip_blob).hexdigest() != expected:
        raise Unavailable('BAD_CHECKSUM', 'SHA-256 mismatch')
    candles = parse_h1_zip(zip_blob, name, now_s)
    return candles, ('VERIFIED' if candles else 'NO_VALID_CANDLES')


def _read_existing(path: Path, now_s: int):
    if not path.exists():
        return {}
    with path.open(encoding='utf-8', newline='') as f:
        items = list(csv.DictReader(f))
    by_t = {}
    for r in items:
        try:
            t = int(r['t'])
            o, h, l, c, v = (float(r[k]) for k in ('o', 'h', 'l', 'c', 'v'))
            if (t % 3600 == 0 and t + 3600 <= now_s and
                min(o, h, l, c) > 0 and v >= 0 and all(map(math.isfinite, (o,h,l,c,v))) and
                l <= o <= h and l <= c <= h):
                by_t[t] = dict(t=t, o=o, h=h, l=l, c=c, v=v)
        except (ValueError, KeyError, TypeError):
            continue
    return by_t


def _write_csv(path: Path, bars):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open('w', encoding='utf-8', newline='') as f:
        writer = csv.DictWriter(f, fieldnames=COLUMNS)
        writer.writeheader()
        writer.writerows(sorted(bars, key=lambda x:x['t']))


def _write_health(root: Path, report: dict):
    file = root / 'models/gold_ml_v3_source_health.json'
    try:
        current = json.loads(file.read_text(encoding='utf-8')) if file.exists() else {}
        if not isinstance(current, dict):
            current = {}
    except (ValueError, OSError):
        current = {}
    current['binance_xauusdt'] = report
    file.parent.mkdir(parents=True, exist_ok=True)
    file.write_text(json.dumps(current, indent=2, ensure_ascii=False) + '\n', encoding='utf-8')


def record_rest_success(root: Path, result: dict):
    _write_health(root, {'status':'REST_OK', 'source':'binance_usdm_trade_h1',
                         'valid_closed_h1':result.get('h1_saved',0),
                         'updated_at_utc':datetime.now(UTC).isoformat()})


def collect_official_archive(path: Path, root: Path, rest_error: str = '', now: datetime | None = None):
    """First REST API failures can fall back to Binance's own archive, not a proxy.

    Absent official archives are reported as absent, never synthesized or
    replaced with another exchange's data. HTTP 451 from archive aborts probes.
    """
    now = now or datetime.now(UTC)
    now_s = int(now.timestamp())
    saved = _read_existing(path, now_s)
    inspected, found, missing, checksum_skipped = 0, 0, 0, 0
    archive_errors, restricted = [], False
    for kind, label, url in packages(now):
        try:
            batch, state = _validated_zip(url, now_s)
            inspected += 1
            if batch is None:
                if state == 'NO_CHECKSUM':
                    checksum_skipped += 1
                else:
                    missing += 1
                continue
            if state != 'VERIFIED':
                archive_errors.append(f'{kind}:{label}:{state}')
                continue
            found += 1
            for row in batch:
                t = row['t']
                if t in saved and any(abs(saved[t][k]-row[k]) > max(1e-8,abs(row[k])*1e-8)
                                      for k in ('o','h','l','c')):
                    # A trade candle revision requires inspection; don't silently rewrite.
                    archive_errors.append(f'{kind}:{label}:OHLC_CONFLICT_AT_{t}')
                    continue
                saved[t] = row
        except Unavailable as exc:
            archive_errors.append(f'{kind}:{label}:{exc.code}')
            if exc.code in ('403','451'):
                restricted = True
                break
            if exc.code in ('NETWORK','429','500','502','503','504'):
                break
            # Integrity errors are not imported, remaining files may be valid.
    saved_list = sorted(saved.values(), key=lambda x:x['t'])
    if saved_list:
        _write_csv(path, saved_list)
    status = ('ARCHIVE_RESTRICTED' if restricted else
              'ARCHIVE_PARTIAL' if (found and archive_errors) else
              'ARCHIVE_VERIFIED' if found else
              'PREVIOUS_DATA_ONLY' if saved_list else 'NO_OFFICIAL_ARCHIVE_DATA')
    result = {'status':status,'source':'binance_usdm_trade_h1', 'symbol':SYMBOL,
              'h1_saved':len(saved_list),'packages_examined':inspected,
              'packages_verified':found,'packages_missing':missing,
              'packages_without_checksum':checksum_skipped,
              'rest_error':str(rest_error)[:140],
              'errors':archive_errors[:20],
              'earliest':datetime.fromtimestamp(saved_list[0]['t'],UTC).isoformat() if saved_list else None,
              'latest':datetime.fromtimestamp(saved_list[-1]['t'],UTC).isoformat() if saved_list else None,
              'updated_at_utc':now.isoformat(),
              'orders_enabled':False, 'live_prediction':False,
              'note':'Official Binance USD-M trade klines only; no Bitget/OANDA mixing.'}
    _write_health(root, result)
    print('BINANCE_OFFICIAL_ARCHIVE', json.dumps(result, ensure_ascii=False))
    return result
