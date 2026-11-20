"""Render-safe read-only V6 report reader. No numpy, training, private keys, orders."""
from pathlib import Path
import json

def read_research(root,symbol="XAUUSDT"):
    result={'status':'NO_REPORT','version':'6.0.0','no_orders':True,
            'live_signal':False,'trade_decision':'BEKLE'}
    if symbol!='XAUUSDT':return {**result,'status':'SYMBOL_NOT_SUPPORTED','symbol':symbol}
    p=Path(root)/'models/gold_scalp_v6_research.json'
    if not p.is_file():return result
    try:
        raw=json.loads(p.read_text(encoding='utf-8'))
        if raw.get('version')!='6.0.0' or raw.get('run_policy')!='RESEARCH_ONLY_NO_LIVE_SIGNAL_NO_ORDERS':
            return {**result,'status':'SCHEMA_MISMATCH'}
        src=raw.get('sources')
        if not isinstance(src,dict):return {**result,'status':'BAD_SOURCES'}
        keys=('binance','bitget')
        safe={k:src[k] for k in keys if k in src and isinstance(src[k],dict)}
        return {**result,'status':'RESEARCH_READY','generated_utc':raw.get('generated_utc'),
                'source_count':len(safe),'costs':raw.get('commission_assumptions_bps',{}),
                'sources':safe,'notes':raw.get('notes',[])}
    except (ValueError,OSError,TypeError) as e:
        return {**result,'status':'READ_ERROR','reason':str(e)[:120]}
