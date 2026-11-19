"""Read-only example risk controls. NEVER estimates liquidations or places orders."""
from __future__ import annotations
from quant import safe

POLICY={'risk_per_trade_pct':0.25,'max_daily_loss_pct':1.0,
        'max_weekly_loss_pct':3.0,'max_drawdown_pct':5.0,
        'max_consecutive_losses':3}


def calculate_risk(equity, daily_loss, weekly_loss, consecutive_losses,
                   drawdown_pct, entry=None, stop=None,
                   multiplier=None, fee_bps=4.0, slippage_bps=1.0):
    """All monetary inputs are user-supplied; no brokerage/account data is connected.
    Losses are positive USD amounts. Equity is current account equity. Multiplier is
    optional, user-supplied, not verified against any exchange contract specification.
    """
    if equity <= 0 or any(x < 0 for x in (daily_loss,weekly_loss,consecutive_losses,drawdown_pct)):
        raise ValueError('Negatif risk girdisi veya sıfır sermaye olamaz')
    risk_budget=equity*POLICY['risk_per_trade_pct']/100
    daily_remaining=max(0,equity*POLICY['max_daily_loss_pct']/100-daily_loss)
    weekly_remaining=max(0,equity*POLICY['max_weekly_loss_pct']/100-weekly_loss)
    veto=[]
    if daily_remaining < risk_budget:veto.append('Günlük kalan risk bütçesi tek işlem bütçesinden düşük')
    if weekly_remaining < risk_budget:veto.append('Haftalık kalan risk bütçesi tek işlem bütçesinden düşük')
    if consecutive_losses >= POLICY['max_consecutive_losses']:veto.append('3 ardışık zarar limiti')
    if drawdown_pct >= POLICY['max_drawdown_pct']:veto.append('Azami tepe-sermaye düşüş limiti')
    size = None
    reason = 'Kontrat çarpanı/lot adımı doğrulanmadan gerçek miktar hesaplanmaz'
    if entry is not None and stop is not None:
        if entry<=0 or stop<=0 or entry==stop:
            veto.append('Giriş / stop geçersiz')
        elif multiplier is not None and multiplier > 0:
            # Instrument multiplier maps one exchange quantity unit to a number of ounces.
            stop_per_unit=abs(entry-stop)*multiplier
            roundtrip_friction_per_unit=entry*multiplier*(2*fee_bps+2*slippage_bps)/10000
            unit_risk=stop_per_unit+roundtrip_friction_per_unit
            size=safe(min(risk_budget,daily_remaining,weekly_remaining)/unit_risk,8) if unit_risk>0 else None
            reason='Yalnız teorik miktar. Kullanıcı çarpanı, borsa lot adımı, marjin ve fiyat kayması doğrulanmadı.'
    return {'mode':'MANUAL_HYPOTHETICAL_ONLY','policy':POLICY,
            'risk_budget_usd':safe(risk_budget,2),
            'daily_remaining_usd':safe(daily_remaining,2),
            'weekly_remaining_usd':safe(weekly_remaining,2),
            'veto':veto,'hypothetical_max_quantity':size,
            'quantity_note':reason,'auto_trade_eligible':False,
            'disclaimer':'Kullanıcının girdiği kayıplar doğrulanamaz; açık pozisyon, fonlama, tasfiye ve borsa minimum emir limitleri takip edilmez.'}
