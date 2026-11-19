"""ALTIN QUANT sidecar for GOLD SCALP PRO v2.

Read-only research and shadow evaluation. No trading routes or position executions.
Preserves the v1 quant.py implementation as-is. All facts are built from historical
closed bars + tagged, time-validated XAUUSDT Bitget market observations.
"""
from __future__ import annotations

import math
import random
import statistics
from datetime import datetime, timezone
from typing import Any

from quant import TF_MIN, indicators, smc, num, safe, true_ranges, wilder
from altin_strategies import evaluate_strategies

SCHEMA_VERSION = '2.0.0'
WEIGHTS = {
    'regime': 10, 'structure': 17, 'mtf': 15, 'flow': 20,
    'derivatives': 10, 'macro': 8, 'statistics': 10, 'setup': 10,
}
REGIME_LABELS = {
    'UP': 'YÜKSELİŞ TRENDİ', 'DOWN': 'DÜŞÜŞ TRENDİ', 'RANGE': 'YATAY / RANGE',
    'SQUEEZE': 'SIKIŞMA', 'SHOCK': 'VOLATİLİTE ŞOKU', 'UNCERTAIN': 'BELİRSİZ',
}


def _pct_rank(vals, item):
    if item is None or not vals:
        return None
    return safe(100 * sum(v <= item for v in vals) / len(vals), 1)


def _direction(ix):
    x = ix.get('latest', ix) or {}
    c, e20, e50, r = (x.get(k) for k in ('close', 'ema20', 'ema50', 'rsi14'))
    if any(v is None for v in (c, e20, e50, r)):
        return 'VERİ YOK'
    if c > e20 > e50 and r >= 50:
        return 'LONG'
    if c < e20 < e50 and r <= 50:
        return 'SHORT'
    return 'KARIŞIK'


def regime_analysis(bars):
    """Ex-post regime on the latest *closed* bar; no future candles."""
    if len(bars) < 210:
        return {'status': 'insufficient', 'label': 'VERİ EKSİK', 'reason': '210 kapalı mum gerekli'}
    ix = indicators(bars)['latest']
    cls = [num(b['c']) for b in bars]
    hi = [num(b['h']) for b in bars]
    lo = [num(b['l']) for b in bars]
    atrs = wilder(true_ranges(hi, lo, cls), 14)
    recent_atr_pct = [100*a/c for a, c in zip(atrs[-160:], cls[-160:]) if a is not None and c > 0]
    atr_pctile = _pct_rank(recent_atr_pct[:-1], recent_atr_pct[-1]) if len(recent_atr_pct) > 50 else None
    # Compare current BB width to prior 100 strictly historical 20-bar windows.
    widths = []
    for j in range(max(19, len(cls)-120), len(cls)):
        window = cls[j-19:j+1]
        mean = statistics.mean(window)
        widths.append(400*statistics.pstdev(window)/mean if mean else 0)
    width_rank = _pct_rank(widths[:-1], widths[-1]) if len(widths) > 50 else None
    adx = ix.get('adx14') or 0
    up = ix.get('close', 0) > (ix.get('ema20') or math.inf) > (ix.get('ema50') or math.inf)
    down = ix.get('close', 0) < (ix.get('ema20') or -math.inf) < (ix.get('ema50') or -math.inf)
    if atr_pctile is not None and atr_pctile >= 96 and (adx >= 30 or width_rank is not None and width_rank >= 90):
        code = 'SHOCK'
    elif width_rank is not None and width_rank <= 12 and adx < 27:
        code = 'SQUEEZE'
    elif adx >= 19 and up:
        code = 'UP'
    elif adx >= 19 and down:
        code = 'DOWN'
    elif adx < 19 and width_rank is not None and 12 < width_rank < 90:
        code = 'RANGE'
    else:
        code = 'UNCERTAIN'
    return {'status': 'ready', 'code': code, 'label': REGIME_LABELS[code],
            'adx14': safe(ix.get('adx14')), 'atr_pctile': atr_pctile,
            'bb_width_pctile': width_rank, 'ema20': ix.get('ema20'),
            'ema50': ix.get('ema50'), 'last_closed': bars[-1]['t'],
            'note': 'İndikatör tabanlı rejim sınıflandırması; optimizasyon/ileri test gerektirir.'}


def mtf_analysis(tf_bars):
    rows = []
    for tf in ('4H', '1H', '15m', '5m', '1m'):
        b = tf_bars.get(tf) or []
        if len(b) < 210:
            rows.append({'tf': tf, 'direction': 'VERİ YOK', 'bars': len(b), 'reason': '210 kapalı mum gerekli'})
        else:
            ix = indicators(b)['latest']
            rows.append({'tf': tf, 'direction': _direction(ix), 'bars': len(b),
                         'closed_time': b[-1]['t'], 'rsi14': ix.get('rsi14')})
    direction = {x['tf']: x['direction'] for x in rows}
    high = [direction[k] for k in ('4H', '1H', '15m')]
    if any(v == 'VERİ YOK' for v in high):
        context = 'VERİ YOK'
    elif high[1] == high[2] and high[1] in ('LONG', 'SHORT') and high[0] != ('SHORT' if high[1] == 'LONG' else 'LONG'):
        context = high[1]
    else:
        context = 'KARIŞIK'
    return {'rows': rows, 'context': context,
            'trigger': direction['1m'], 'setup': direction['5m'],
            'note': '4H/1H bağlam · 15m yön filtresi · 5m kurulum · 1m giriş izlemesi.'}


def flow_analysis(bids, asks, trades, current_ms, feed_valid):
    """Rolling trade notional and live book, Bitget-only; no global-gold claim."""
    recent = [t for t in trades if 0 <= current_ms - int(t.get('t', 0)) <= 300_000
              and num(t.get('p')) > 0 and num(t.get('v')) > 0
              and t.get('side') in ('buy', 'sell')]
    windows = {}
    for secs in (15, 30, 60, 300):
        xs = [t for t in recent if current_ms-int(t['t']) <= secs*1000]
        buy = sum(num(t['p'])*num(t['v']) for t in xs if t['side'] == 'buy')
        sell = sum(num(t['p'])*num(t['v']) for t in xs if t['side'] == 'sell')
        windows[str(secs)] = {'count': len(xs), 'buy_usdt': safe(buy, 2),
                              'sell_usdt': safe(sell, 2), 'delta_usdt': safe(buy-sell, 2),
                              'aggressor': safe((buy-sell)/(buy+sell), 4) if buy+sell else None}
    levels = {}
    for depth in (5, 10, 20):
        b = sum(p*q for p, q in bids[:depth])
        a = sum(p*q for p, q in asks[:depth])
        levels[str(depth)] = {'bid_usdt': safe(b, 2), 'ask_usdt': safe(a, 2),
                              'imbalance': safe((b-a)/(b+a), 4) if b+a else None}
    best_bid = bids[0][0] if bids else None
    best_ask = asks[0][0] if asks else None
    spread = safe(1e4*(best_ask-best_bid)/best_ask, 2) if best_ask and best_bid else None
    ready = (feed_valid.get('ticker') and feed_valid.get('book') and feed_valid.get('trades')
             and windows['60']['count'] >= 5 and spread is not None)
    return {'status': 'ready' if ready else 'unavailable', 'windows': windows, 'depth': levels,
            'spread_bps': spread, 'valid': bool(ready),
            'note': 'Gerçekleşmiş Bitget taker akışından pencere bazlı delta; tam geçmiş CVD ve dünya altın hacmi değildir. Emir duvarı kalıcılığı veri geçmişi kaydedilmeden ölçülemez.'}


def quant_diagnostics(bars):
    closes = [num(x['c']) for x in bars if num(x['c']) > 0]
    if len(closes) < 110:
        return {'status': 'insufficient', 'reason': '110 kapalı mum gerekli'}
    ret = [math.log(b/a) for a, b in zip(closes, closes[1:])]
    x = ret[-min(300, len(ret)):]
    mu, sd = statistics.mean(x), statistics.pstdev(x)
    if sd <= 0:
        return {'status': 'insufficient', 'reason': 'Değişmeyen fiyat serisi'}
    skew = sum(((v-mu)/sd)**3 for v in x)/len(x)
    excess = sum(((v-mu)/sd)**4 for v in x)/len(x)-3
    # Historical 95% VaR / ES: loss positive, losses ordered worst-first.
    losses = sorted([-r*100 for r in x], reverse=True)
    cutoff = max(1, math.ceil(len(losses)*.05))
    var = losses[cutoff-1]
    es = statistics.mean(losses[:cutoff])
    lag1 = statistics.mean((x[i]-mu)*(x[i-1]-mu) for i in range(1, len(x)))/(sd*sd)
    # Seeded block bootstrap (5-bar blocks) of sample means; independent of call timing.
    rnd = random.Random(20261118)
    block = min(5, max(2, len(x)//30))
    means = []
    for _ in range(250):
        sample = []
        while len(sample) < len(x):
            j = rnd.randrange(len(x)-block+1)
            sample.extend(x[j:j+block])
        means.append(statistics.mean(sample[:len(x)])*100)
    means.sort()
    return {'status': 'ready', 'samples': len(x), 'mean_log_return_pct': safe(mu*100, 5),
            'stdev_log_return_pct': safe(sd*100, 5),
            'historical_var95_pct': safe(var, 5), 'historical_es95_pct': safe(es, 5),
            'skewness': safe(skew, 3), 'excess_kurtosis': safe(excess, 3),
            'lag1_autocorrelation': safe(lag1, 4),
            'block_bootstrap_mean_ci95_pct': [safe(means[6], 5), safe(means[243], 5)],
            'note': 'Tarihsel tek-mum kayıp dağılımı; örneklem sınırlı, VaR/ES üst kayıp sınırı değildir. 250 tekrar, 5-bar hareketli blok bootstrap yaklaşık araştırmadır.'}


def build_quant_report(symbol, tf_bars, snap, legacy, current_ms):
    """Build a comparison report. Legacy decision remains untouched."""
    primary = tf_bars.get('5m') or tf_bars.get('1m') or []
    reg = regime_analysis(primary)
    mtf = mtf_analysis(tf_bars)
    # Current 5m close and contiguous MTF histories are required for a fresh signal.
    data_quality = {}
    for key, candles in tf_bars.items():
        step = TF_MIN[key]*60
        recent = candles[-50:]
        stale = not recent or ((current_ms//1000) - (recent[-1]['t']+step) > max(2*step, 90))
        holes = sum(1 for a,b in zip(recent,recent[1:]) if b['t']-a['t']!=step)
        data_quality[key] = {'fresh': not stale, 'gap_count_last_50': holes,
                             'last_closed_time': recent[-1]['t'] if recent else None,
                             'count': len(candles)}
    qstats = quant_diagnostics(primary)
    structure = smc(primary) if primary else {'events': []}
    valid = snap.get('valid') or {}
    flow = flow_analysis(snap.get('bids') or [], snap.get('asks') or [],
                         snap.get('raw_trades') or [], current_ms, valid) if symbol == 'XAUUSDT' else {
                         'status': 'unavailable', 'valid': False, 'reason': 'XAUUSD spot için merkezî işlem akışı bulunmuyor'}
    price_info = snap.get('price') if symbol == 'XAUUSDT' else snap.get('spot')
    price = num((price_info or {}).get('last'), None)
    bars_now = primary[-1] if primary else None
    ix = indicators(primary)['latest'] if len(primary) >= 200 else {}
    atr = ix.get('atr14')
    spread_bps = flow.get('spread_bps') if symbol == 'XAUUSDT' else None
    # Configurable research assumptions, not verified trader-specific exchange fees.
    fee_bps = 4.0
    slip_bps = 1.0
    round_trip_cost_bps = 2*(fee_bps+slip_bps) + (spread_bps or 0)
    deriv = {'status': 'unavailable', 'reason': 'Geçerli XAUUSDT funding/mark/OI bulunamadı'}
    if symbol == 'XAUUSDT' and valid.get('ticker'):
        p = price_info or {}
        if p.get('funding') is not None and p.get('oi') is not None and p.get('mark'):
            deriv = {'status': 'partial', 'funding': p['funding'], 'oi': p['oi'],
                     'mark': p['mark'], 'index': p.get('index'),
                     'oi_change': None, 'note': 'OI değişim geçmişi ve tasfiye akışı henüz yok; yön tayin edilmez.'}
    event_status = {'status': 'unavailable', 'reason': 'Doğrulanmış anlık ekonomik takvim ve olay sürprizi bağlı değil; FRED günlük veri bunun yerine geçmez.'}

    families = {}
    def add(name, long_fraction=None, short_fraction=None, detail='', status='available'):
        limit = WEIGHTS[name]
        if long_fraction is None or short_fraction is None:
            families[name] = {'status': 'unavailable', 'max': limit, 'long': None, 'short': None, 'detail': detail}
        else:
            families[name] = {'status': status, 'max': limit,
                'long': safe(limit*max(0, min(1, long_fraction)), 2),
                'short': safe(limit*max(0, min(1, short_fraction)), 2), 'detail': detail}

    code = reg.get('code')
    if code in ('UP', 'DOWN', 'RANGE', 'SQUEEZE', 'SHOCK'):
        ups = {'UP':(1,0), 'DOWN':(0,1), 'RANGE':(.3,.3), 'SQUEEZE':(.15,.15), 'SHOCK':(0,0)}
        add('regime', *ups[code], detail=reg['label'])
    else:
        add('regime', detail='Rejim henüz güvenilir biçimde sınıflandırılamadı')

    ev = [x for x in structure.get('events', []) if bars_now and x.get('t', 0)>=bars_now['t']-12*300]
    pos = any(x['type'] in ('BOS_UP','SWEEP_LOW','FVG_BULL') for x in ev)
    neg = any(x['type'] in ('BOS_DOWN','SWEEP_HIGH','FVG_BEAR') for x in ev)
    if structure.get('status') == 'ready':
        add('structure', .9 if pos and not neg else .3 if pos else .1,
            .9 if neg and not pos else .3 if neg else .1,
            detail='Son 12 kapalı 5m mumda tespit edilen BOS/FVG/sweep adayları')
    else:
        add('structure', detail='SMC için yeterli kapalı mum yok')

    context = mtf['context']
    if context in ('LONG', 'SHORT', 'KARIŞIK'):
        t = mtf['trigger']; set_up = mtf['setup']
        if context == 'LONG':
            lv = .7+.15*(set_up=='LONG')+.15*(t=='LONG')
            sv = .05
        elif context == 'SHORT':
            lv = .05
            sv = .7+.15*(set_up=='SHORT')+.15*(t=='SHORT')
        else:
            lv = sv = .1
        add('mtf', lv, sv, detail=f'HTF {context} · 5m {set_up} · 1m {t}')
    else:
        add('mtf', detail='4H/1H/15m kapanmış mum eksik')

    if flow.get('valid'):
        f60 = flow['windows']['60']['aggressor'] or 0
        f300 = flow['windows']['300']['aggressor'] or 0
        ob = flow['depth']['20']['imbalance'] or 0
        delta = .5*f60+.25*f300+.25*ob
        add('flow', min(1,max(0,delta*2.5)), min(1,max(0,-delta*2.5)),
            detail=f'60s taker {f60:+.2f} · 300s {f300:+.2f} · DOM20 {ob:+.2f}')
    else:
        add('flow', detail='Güncel Bitget trade + book + fiyat gerekli')

    # These inputs are contextual and NOT directional proof. Missing families remain null.
    add('derivatives', detail='OI/funding düzeyi tek başına long/short kanıtı değildir; OI trendi yok')
    add('macro', detail='Doğrulanmış ekonomik olay sürprizi veya güncel makro yön kaynağı yok')

    if qstats.get('status') == 'ready':
        autoc = qstats.get('lag1_autocorrelation') or 0
        momentum = qstats.get('mean_log_return_pct') or 0
        # Small and exploratory weight; avoid claiming predictive probability.
        strength = min(.55, abs(momentum)/(qstats.get('stdev_log_return_pct') or 1)*.7)
        add('statistics', strength if momentum>0 else 0, strength if momentum<0 else 0,
            detail=f'Log getiri μ={momentum:.4f}%, oto-kor={autoc:+.2f} (deneysel)')
    else:
        add('statistics', detail='Dağılım için yeterli veri yok')

    setup = {'status': 'unavailable', 'entry_ref': price, 'stop': None, 'take_profit': None,
             'fee_assumption_bps_each_side': fee_bps, 'slippage_assumption_bps_each_side': slip_bps,
             'spread_bps': spread_bps, 'roundtrip_est_bps': safe(round_trip_cost_bps, 2),
             'contract_multiplier_verified': False,
             'note': 'Fiyat/ATR/kontrat çarpanı/likidite doğrulanmadan gerçek miktar hesaplanmaz.'}
    if price and atr and atr>0 and bars_now:
        candidate_side = context if context in ('LONG', 'SHORT') else None
        side = 1 if candidate_side == 'LONG' else -1 if candidate_side == 'SHORT' else 0
        if side:
            stop = price - side*1.5*atr
            take = price + side*2.25*atr
            stop_distance_bps = 1e4*abs(price-stop)/price
            net_rr = ((abs(take-price)/price*1e4-round_trip_cost_bps) /
                      (stop_distance_bps+round_trip_cost_bps))
            setup.update(status='illustrative', direction=candidate_side, stop=safe(stop),
                         take_profit=safe(take), net_rr_est=safe(net_rr,3),
                         stop_bps=safe(stop_distance_bps,2),
                         note='ATR tabanlı araştırma senaryosu; fiyat girişi, dolum ve kontrat özellikleri doğrulanmadı.')
            if symbol == 'XAUUSDT' and flow.get('valid'):
                quality = .8 if net_rr >= 1.2 and spread_bps is not None and spread_bps <= 12 else .05
                add('setup',quality if side==1 else 0,quality if side==-1 else 0,
                    detail=f'Örnek maliyet sonrası net R/R {net_rr:.2f}; kontrat doğrulanmadı',status='illustrative')
            else:
                add('setup', detail='Spot için canlı spread veya piyasa akışı geçerli değil')
        else:
            add('setup', detail='Giriş yönü ve stop senaryosu belirlenemedi')
    else:
        add('setup', detail='Güncel fiyat veya ATR bulunamadı')

    coverage = sum(v['max'] for v in families.values() if v['long'] is not None)
    total_l = sum(v['long'] or 0 for v in families.values())
    total_s = sum(v['short'] or 0 for v in families.values())
    veto = []
    if symbol != 'XAUUSDT': veto.append('Spot işlem akışı/derinliği doğrulanmadı')
    if not valid.get('ticker') and symbol == 'XAUUSDT': veto.append('Bitget fiyatı güncel değil')
    if not flow.get('valid') and symbol == 'XAUUSDT': veto.append('Canlı order flow doğrulanmadı')
    if context == 'VERİ YOK': veto.append('MTF geçmişi eksik')
    for critical_tf in ('1m','5m','15m','1H'):
        quality = data_quality.get(critical_tf, {})
        if not quality.get('fresh'): veto.append(f'{critical_tf} kapalı mum bayat/eksik')
        if quality.get('gap_count_last_50'): veto.append(f'{critical_tf} mum aralığında boşluk var')
    if code in ('SHOCK','UNCERTAIN') or not code: veto.append('Şok/belirsiz piyasa rejimi')
    if spread_bps is None and symbol == 'XAUUSDT': veto.append('Spread ölçülemiyor')
    elif spread_bps is not None and spread_bps > 20: veto.append('Geniş spread >20 bps')
    if coverage < 80: veto.append(f'Yönsel ölçüm kapsamı yetersiz: {coverage}/100')
    # This application has no verified calendar, portfolio journal, risk account, or
    # exchange contract multiplier; it must NEVER mark a real trade as safe to enter.
    veto.append('Haber takvimi/hesap limiti/kontrat özellikleri tam doğrulanmadı')
    leader = 'LONG' if total_l>total_s else 'SHORT'
    top = max(total_l,total_s)
    gap = abs(total_l-total_s)
    theoretical = ('İŞLEM YOK' if top < 68 or gap < 15 else
                   'İZLE / UYARI' if top < 78 else f'{leader} ADAYI')
    result = 'İŞLEM YOK' if veto else theoretical
    base = (legacy or {}).get('decision','BEKLE')
    agreement = ('BELİRSİZ' if base == 'BEKLE' else
                 'AYNI YÖN' if theoretical == f'{base} ADAYI' else
                 'FARKLI / ONAY YOK')
    return {'version':SCHEMA_VERSION, 'mode':'SHADOW_ONLY', 'symbol':symbol,
            'algorithm_tf':'5m', 'sample_time_ms':current_ms,
            'regime':reg, 'mtf':mtf, 'timeframe_quality':data_quality, 'strategies':evaluate_strategies(primary,reg,mtf,flow), 'orderflow':flow, 'derivatives':deriv,
            'macro_events':event_status, 'statistics':qstats, 'setup':setup,
            'smc':{'events':ev[-10:], 'note':'Aday yapı sinyalleri; garantili kurumsal akış değildir'},
            'score':{'max_points':100, 'coverage_points':coverage,
                     'long_points':safe(total_l,2), 'short_points':safe(total_s,2),
                     'families':families, 'thresholds':{'watch':68,'candidate':78,'lead':15},
                     'theoretical':theoretical, 'final':result,'veto':veto,
                     'note':'Puanlar kazanma olasılığı değildir; eksik aileler otomatik sıfıra çevrilmez.'},
            'legacy':{'decision':base,'long':(legacy or {}).get('long'),
                      'short':(legacy or {}).get('short'), 'veto':(legacy or {}).get('veto',[])},
            'comparison':agreement, 'real_orders_enabled':False,
            'warnings':['ALTIN QUANT yalnız gözlem modundadır. v1 karar motorunu değiştirmez.',
                        'Seans duyarlılığı, makro takvim, işlem günlüğü ve doğrulanmış dolum modeli henüz entegre değil.',
                        'Fiyat/spread/derinlik yalnızca seçilen borsanın veri kapsamını temsil eder.']}
