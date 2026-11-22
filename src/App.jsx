import React, { useEffect, useRef, useState } from 'react'
import {
  Activity, AreaChart, BarChart3, Bell, Bot, ChevronDown, Clock3,
  Gauge, Globe2, Landmark, LayoutDashboard, Menu, MessageSquare,
  Newspaper, Settings, ShieldCheck, SlidersHorizontal, Wallet,
  X, Zap,
} from 'lucide-react'
import { createChart, CandlestickSeries, LineSeries } from 'lightweight-charts'

const nav = [
  { id: 'overview', label: 'Kokpit', icon: LayoutDashboard },
  { id: 'chart', label: 'Grafik', icon: AreaChart },
  { id: 'flow', label: 'Order Flow', icon: Activity },
  { id: 'quant', label: 'Quant AI', icon: Gauge },
  { id: 'news', label: 'Haber / Takvim', icon: Newspaper },
  { id: 'dom', label: 'Emir Defteri', icon: BarChart3 },
]

const fmt = (value, digits = 2) =>
  value === null || value === undefined || !Number.isFinite(Number(value))
    ? '—'
    : Number(value).toLocaleString('tr-TR', { maximumFractionDigits: digits })

const short = value => {
  const n = Number(value)
  if (!Number.isFinite(n)) return '—'
  if (Math.abs(n) >= 1e9) return `${fmt(n / 1e9)} Mr`
  if (Math.abs(n) >= 1e6) return `${fmt(n / 1e6)} Mn`
  if (Math.abs(n) >= 1e3) return `${fmt(n / 1e3)} B`
  return fmt(n)
}

async function getJSON(path, options) {
  const response = await fetch(path, { cache: 'no-store', ...options })
  if (!response.ok) throw new Error(`${response.status} ${response.statusText}`)
  return response.json()
}

function Header({ symbol, setSymbol, tf, setTf, health }) {
  return (
    <header className="topbar">
      <div className="brand">
        <div className="brandMark">TM</div>
        <div>
          <strong>TİMİ GOLD</strong>
          <span>Markets Terminal</span>
        </div>
      </div>
      <div className="marketSwitch">
        <button className={symbol === 'XAUUSDT' ? 'active' : ''} onClick={() => setSymbol('XAUUSDT')}>XAUUSDT</button>
        <button className={symbol === 'XAUUSD' ? 'active' : ''} onClick={() => setSymbol('XAUUSD')}>XAUUSD</button>
      </div>
      <div className="timeframes">
        {['1m', '5m', '15m', '1H', '4H', '1D'].map(item =>
          <button key={item} className={tf === item ? 'active' : ''} onClick={() => setTf(item)}>{item}</button>
        )}
      </div>
      <div className="headerActions">
        <div className="liveStatus"><span className={health?.live_external_verified ? 'dot live' : 'dot'} />{health?.live_external_verified ? 'CANLI' : 'VERİ KONTROLÜ'}</div>
        <button className="iconButton" aria-label="Bildirimler"><Bell size={17} /></button>
        <button className="avatar" aria-label="Kullanıcı">SD</button>
      </div>
    </header>
  )
}

function Sidebar({ active, setActive, mobileOpen, setMobileOpen }) {
  return (
    <aside className={`sidebar ${mobileOpen ? 'open' : ''}`}>
      <button className="mobileClose" onClick={() => setMobileOpen(false)}><X size={18} /></button>
      <nav>
        {nav.map(({ id, label, icon: Icon }) =>
          <button key={id} type="button" className={active === id ? 'active' : ''} aria-current={active === id ? 'page' : undefined} onClick={() => { setActive(id); setMobileOpen(false); window.history.replaceState(null, '', `#${id}`) }}>
            <Icon size={18} /><span>{label}</span>
          </button>
        )}
      </nav>
      <div className="sidebarFooter">
        <button><Settings size={18} /><span>Ayarlar</span></button>
        <div className="workspaceStatus"><ShieldCheck size={16} /><div><strong>Koruma aktif</strong><span>Emir kapalı</span></div></div>
      </div>
    </aside>
  )
}

function MetricCard({ label, value, change, tone = 'neutral', note }) {
  return (
    <article className={`metricCard ${tone}`}>
      <div className="metricLabel">{label}</div>
      <strong>{value}</strong>
      {change !== undefined && <span className={`metricChange ${tone}`}>{change}</span>}
      {note && <small>{note}</small>}
    </article>
  )
}

function GoldChart({ candles, symbol, tf, zones }) {
  const host = useRef(null)
  const chart = useRef(null)
  useEffect(() => {
    if (!host.current) return
    let instance = null
    let observer = null
    try {
      instance = createChart(host.current, {
        width: host.current.clientWidth,
        height: host.current.clientHeight,
        layout: { background: { color: '#0b1017' }, textColor: '#7d8998', fontFamily: 'Inter, sans-serif' },
        grid: { vertLines: { color: '#171e27' }, horzLines: { color: '#171e27' } },
        rightPriceScale: { borderColor: '#202936' },
        timeScale: { borderColor: '#202936', timeVisible: tf !== '1D', secondsVisible: false },
        crosshair: { vertLine: { color: '#9b8a61', labelBackgroundColor: '#4a4332' }, horzLine: { color: '#9b8a61' } },
        localization: { locale: 'tr-TR', priceFormatter: value => fmt(value, 2) },
      })
      chart.current = instance
      const series = instance.addSeries(CandlestickSeries, {
        upColor: '#4ecba2', downColor: '#df6a78',
        borderUpColor: '#4ecba2', borderDownColor: '#df6a78',
        wickUpColor: '#4ecba2', wickDownColor: '#df6a78',
      })
      const data = (candles || []).filter(x => x.t && x.c > 0).map(x => ({
        time: x.t, open: x.o, high: x.h, low: x.l, close: x.c,
      }))
      if (data.length) series.setData(data)
      for (const [price, title, color] of [
        [zones?.stop_zone?.preferred, 'STOP', '#df6a78'],
        [zones?.entry_zone?.preferred, 'GİRİŞ', '#c9ad73'],
        [zones?.target_zone?.preferred, 'HEDEF', '#4ecba2'],
      ]) {
        if (Number.isFinite(Number(price))) {
          series.createPriceLine({ price: Number(price), color, lineWidth: 1, lineStyle: 2, axisLabelVisible: true, title })
        }
      }
      instance.timeScale().fitContent()
      observer = new ResizeObserver(entries => {
        if (!chart.current || chart.current !== instance) return
        const { width, height } = entries[0].contentRect
        if (width > 0 && height > 0) instance.applyOptions({ width, height })
      })
      observer.observe(host.current)
    } catch (error) {
      console.error('Gold chart initialization failed', error)
    }
    return () => {
      observer?.disconnect()
      chart.current = null
      if (instance) {
        try { instance.remove() } catch (_) {}
      }
    }
  }, [candles, tf, zones])
  return <div className="chartHost" ref={host} />
}

function Overview({ snapshot, candle, decision, candles, symbol, tf }) {
  const price = snapshot?.price?.last
  const flow = snapshot?.flow
  const buy = flow?.buy_notional60 || 0
  const sell = flow?.sell_notional60 || 0
  const total = buy + sell
  const buyPct = total ? buy / total * 100 : 50
  const sellPct = total ? sell / total * 100 : 50
  return (
    <div className="pageOverview">
      <div className="pageHeading">
        <div><span>Piyasa Kokpiti</span><h1>{symbol} <em>{tf}</em></h1></div>
        <div className="headingActions"><button><SlidersHorizontal size={15} /> Düzenle</button><button className="primary"><Zap size={15} /> Piyasa Özeti</button></div>
      </div>
      <div className="metricGrid">
        <MetricCard label="Son fiyat" value={fmt(price)} change={`${snapshot?.price?.change24_pct >= 0 ? '+' : ''}${fmt(snapshot?.price?.change24_pct)}%`} tone={snapshot?.price?.change24_pct >= 0 ? 'positive' : 'negative'} note="24 saat" />
        <MetricCard label="XAUUSD Spot" value={fmt(snapshot?.spot?.last)} change={snapshot?.spot_status || 'Spot bekleniyor'} tone="gold" />
        <MetricCard label="Alış / Satış Baskısı" value={`${fmt(buyPct, 1)}%`} change={`${fmt(sellPct, 1)}% Satış`} tone="positive" note="Son 60 saniye" />
        <MetricCard label="Birleşik karar" value={decision?.direction || 'BEKLE'} change={`${fmt((decision?.probability_up || 0.5) * 100, 1)}% yön olasılığı`} tone={decision?.direction === 'LONG' ? 'positive' : decision?.direction === 'SHORT' ? 'negative' : 'neutral'} />
      </div>
      <div className="terminalGrid">
        <section className="panel chartPanel">
          <div className="panelHeader"><div><span className="eyebrow">FİYAT GRAFİĞİ</span><h2>{symbol} / USD</h2></div><div className="chartLegend"><span><i className="buyDot" />Alış</span><span><i className="sellDot" />Satış</span></div></div>
          <GoldChart candles={candles} symbol={symbol} tf={tf} zones={decision} />
        </section>
        <section className="panel decisionPanel">
          <div className="panelHeader"><div><span className="eyebrow">BİRLEŞİK KARAR</span><h2>{decision?.direction || 'BEKLE'}</h2></div><span className={`decisionBadge ${decision?.direction?.toLowerCase()}`}>{decision?.model_approved ? 'ML doğrulamalı' : 'Gölge mod'}</span></div>
          <div className="decisionGauge">
            <div className="gaugeArc" style={{ '--score': `${(decision?.probability_up || 0.5) * 100}%` }}><strong>{fmt((decision?.probability_up || 0.5) * 100, 0)}%</strong><span>LONG olasılığı</span></div>
          </div>
          <div className="zoneGrid">
            <div><span>Giriş bölgesi</span><strong>{decision?.entry_zone ? `${fmt(decision.entry_zone.low)}–${fmt(decision.entry_zone.high)}` : '—'}</strong></div>
            <div><span>Stop</span><strong className="negativeText">{decision?.stop_zone ? fmt(decision.stop_zone.preferred) : '—'}</strong></div>
            <div><span>Hedef</span><strong className="positiveText">{decision?.target_zone ? fmt(decision.target_zone.preferred) : '—'}</strong></div>
            <div><span>Risk / Getiri</span><strong>1 : {fmt(decision?.risk_reward_ratio)}</strong></div>
          </div>
          <div className="historicalStrip"><span>Geriye dönük başarı</span><strong>%{fmt(decision?.historical_analysis?.win_rate_pct)}</strong><small>{decision?.historical_analysis?.sample_positions || 0} pozisyon</small></div>
        </section>
      </div>
      <div className="secondaryGrid">
        <section className="panel"><div className="panelHeader"><div><span className="eyebrow">VERİ AKIŞI</span><h2>Order Flow</h2></div><Activity size={16} /></div><div className="flowBars"><div><span>Alış</span><b>{fmt(buyPct, 1)}%</b><i><em style={{ width: `${buyPct}%` }} /></i></div><div><span>Satış</span><b>{fmt(sellPct, 1)}%</b><i><em className="sell" style={{ width: `${sellPct}%` }} /></i></div></div></section>
        <section className="panel"><div className="panelHeader"><div><span className="eyebrow">PİYASA REJİMİ</span><h2>{snapshot?.notes ? 'Aktif veri' : 'Bekleniyor'}</h2></div><Landmark size={16} /></div><div className="miniRows"><div><span>RSI 14</span><strong>{fmt(candle?.latest?.rsi14, 1)}</strong></div><div><span>ATR 14</span><strong>{fmt(candle?.latest?.atr14, 2)}</strong></div><div><span>ADX 14</span><strong>{fmt(candle?.latest?.adx14, 1)}</strong></div></div></section>
      </div>
    </div>
  )
}

function NewsCalendar() {
  const [news, setNews] = useState([])
  const [calendar, setCalendar] = useState([])
  const [macro, setMacro] = useState({})
  const [loading, setLoading] = useState(true)
  useEffect(() => {
    Promise.allSettled([getJSON('/api/news'), getJSON('/api/economic-calendar'), getJSON('/api/macro')]).then(([n, c, m]) => {
      setNews(n.status === 'fulfilled' ? n.value.items || [] : [])
      setCalendar(c.status === 'fulfilled' ? c.value.events || c.value.items || [] : [])
      setMacro(m.status === 'fulfilled' ? m.value.data || {} : {})
      setLoading(false)
    })
  }, [])
  return (
    <div className="pageInner">
      <div className="pageHeading"><div><span>Bilgi Akışı</span><h1>Haberler & Ekonomi Takvimi</h1></div><button className="primary" onClick={() => location.reload()}><Clock3 size={15} /> Yenile</button></div>
      <div className="newsLayout">
        <section className="panel newsFeed"><div className="panelHeader"><div><span className="eyebrow">CANLI HABER AKIŞI</span><h2>Altın ve Makro Haberler</h2></div><Globe2 size={16} /></div>
          {loading ? <div className="emptyState">Kaynaklar taranıyor…</div> : news.length ? news.map((item, index) =>
            <a className="newsItem" href={item.url} target="_blank" rel="noreferrer" key={`${item.url}-${index}`}><div className={`newsType ${index % 3 === 0 ? 'high' : ''}`}>{item.source || 'Haber'}</div><div><h3>{item.title}</h3><p>{item.domain || 'Kaynak'} · {item.time || 'Güncel'}</p></div><span>↗</span></a>
          ) : <div className="emptyState">Şu anda doğrulanmış haber alınamadı. Kaynaklar tekrar taranıyor.</div>}
        </section>
        <aside className="newsSide">
          <section className="panel"><div className="panelHeader"><div><span className="eyebrow">EKONOMİ TAKVİMİ</span><h2>Bugün & Önümüzdeki Veriler</h2></div></div>
            {loading ? <div className="emptyState">Takvim hazırlanıyor…</div> : calendar.length ? calendar.map((item, index) =>
              <div className="calendarItem" key={index}><time>{item.time || item.date || 'Zaman yok'}</time><div><b>{item.title || item.event}</b><span>{item.country || item.currency || 'Ekonomi'} · {item.impact || 'Belirtilmedi'}</span></div></div>
            ) : <div className="emptyState">Doğrulanmış takvim olayı bulunamadı.</div>}
          </section>
          <section className="panel"><div className="panelHeader"><div><span className="eyebrow">FRED MAKRO</span><h2>ABD Faiz & Dolar</h2></div></div><div className="macroGrid">
            {Object.entries(macro).map(([key, item]) => <div className="macroItem" key={key}><span>{item.label}</span><strong>{fmt(item.last, 3)}</strong><small>{item.date}</small></div>)}
          </div></section>
        </aside>
      </div>
    </div>
  )
}

function QuantView({ decision }) {
  const hist = decision?.historical_analysis || {}
  const strategy = decision?.strategy_learning?.best_strategy
  return (
    <div className="pageInner">
      <div className="pageHeading"><div><span>Analitik Motor</span><h1>Quant AI & ALTIN QUANT</h1></div><button className="primary"><Gauge size={15} /> Motorları çalıştır</button></div>
      <div className="metricGrid">
        <MetricCard label="Birleşik yön" value={decision?.direction || 'BEKLE'} tone={decision?.direction === 'LONG' ? 'positive' : 'neutral'} />
        <MetricCard label="Geriye dönük başarı" value={`%${fmt(hist.win_rate_pct)}`} tone={hist.win_rate_pct >= 50 ? 'positive' : 'negative'} note={`${hist.sample_positions || 0} pozisyon`} />
        <MetricCard label="Profit factor" value={fmt(hist.profit_factor, 2)} tone={hist.profit_factor >= 1 ? 'positive' : 'negative'} />
        <MetricCard label="Beklenen getiri" value={`%${fmt(hist.expectancy_pct, 3)}`} tone={hist.expectancy_pct >= 0 ? 'positive' : 'negative'} />
      </div>
      <div className="quantGrid">
        <section className="panel"><div className="panelHeader"><div><span className="eyebrow">7 QUANT MOTORU</span><h2>Motor skorları</h2></div></div><div className="engineList">
          {['Quantalytics','Gold Prediction','MCM 2022','GS Quant','NautilusTrader','Riskfolio-Lib','Soloshun'].map((item, index) => <div key={item}><span>{String(index + 1).padStart(2, '0')}</span><strong>{item}</strong><em>{index < 2 ? 'Yön / veri' : 'Risk / bağlam'}</em><b>{index < 2 ? 'ARAŞTIRMA' : 'DOĞRULAMA'}</b></div>)}
        </div></section>
        <section className="panel"><div className="panelHeader"><div><span className="eyebrow">EN İYİ ÖĞRENİLEN STRATEJİ</span><h2>{strategy?.label || 'Veri bekleniyor'}</h2></div></div><div className="strategyBlock"><div><span>İleri dönem PnL</span><strong className={strategy?.forward_pnl >= 0 ? 'positiveText' : 'negativeText'}>{fmt(strategy?.forward_pnl, 2)}</strong></div><div><span>İşlem sayısı</span><strong>{strategy?.forward_trades || 0}</strong></div><div><span>Kazanma oranı</span><strong>%{fmt(strategy?.forward_win_rate_pct)}</strong></div></div></section>
      </div>
    </div>
  )
}

function Assistant({ open, setOpen }) {
  const [question, setQuestion] = useState('')
  const [messages, setMessages] = useState([{ role: 'assistant', text: 'Grafik, haber, yön, risk veya 7 Quant motoru hakkında sorabilirsiniz.' }])
  async function ask(event) {
    event.preventDefault()
    if (!question.trim()) return
    const text = question.trim()
    setMessages(items => [...items, { role: 'user', text }])
    setQuestion('')
    try {
      const result = await getJSON('/api/assistant', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ question: text, symbol: 'XAUUSDT', tf: '5m' }) })
      setMessages(items => [...items, { role: 'assistant', text: result.answer }])
    } catch {
      setMessages(items => [...items, { role: 'assistant', text: 'Asistan şu anda piyasa verilerine bağlanamadı.' }])
    }
  }
  return (
    <aside className={`assistant ${open ? 'open' : ''}`}>
      <div className="assistantHeader"><div><span>GOLD CONTEXT AI</span><strong>Piyasa Asistanı</strong></div><button onClick={() => setOpen(false)}><X size={17} /></button></div>
      <div className="assistantMessages">{messages.map((message, index) => <div className={message.role} key={index}>{message.text}</div>)}</div>
      <form onSubmit={ask}><input value={question} onChange={event => setQuestion(event.target.value)} placeholder="Grafik ve piyasa durumu nedir?" /><button><MessageSquare size={16} /></button></form>
    </aside>
  )
}

export default function App() {
  const hashView = typeof window !== 'undefined' ? window.location.hash.replace('#', '') : ''
  const [active, setActive] = useState(nav.some(item => item.id === hashView) ? hashView : 'overview')
  const [symbol, setSymbol] = useState('XAUUSDT')
  const [tf, setTf] = useState('5m')
  const [snapshot, setSnapshot] = useState(null)
  const [candle, setCandle] = useState(null)
  const [candles, setCandles] = useState([])
  const [decision, setDecision] = useState(null)
  const [health, setHealth] = useState(null)
  const [mobileOpen, setMobileOpen] = useState(false)
  const [assistantOpen, setAssistantOpen] = useState(false)

  useEffect(() => {
    const syncHash = () => {
      const next = window.location.hash.replace('#', '')
      if (nav.some(item => item.id === next)) setActive(next)
    }
    const closeOnEscape = event => {
      if (event.key === 'Escape') {
        setMobileOpen(false)
        setAssistantOpen(false)
      }
    }
    window.addEventListener('hashchange', syncHash)
    window.addEventListener('keydown', closeOnEscape)
    return () => {
      window.removeEventListener('hashchange', syncHash)
      window.removeEventListener('keydown', closeOnEscape)
    }
  }, [])

  useEffect(() => {
    let cancelled = false
    async function load() {
      try {
        const [snap, candlesResult, analysis, unified, healthResult] = await Promise.all([
          getJSON('/api/snapshot'),
          getJSON(`/api/candles?symbol=${symbol}&tf=${tf}&limit=350`),
          getJSON(`/api/analysis?symbol=${symbol}&tf=${tf}`),
          getJSON(`/api/unified-decision?symbol=${symbol}&tf=${tf}`),
          getJSON('/api/health'),
        ])
        if (cancelled) return
        setSnapshot(snap); setCandles(candlesResult.bars || []); setCandle(analysis); setDecision(unified); setHealth(healthResult)
      } catch (error) {
        console.warn(error)
      }
    }
    load()
    const timer = setInterval(load, 30000)
    return () => { cancelled = true; clearInterval(timer) }
  }, [symbol, tf])

  return (
    <div className="appShell">
      <button className="menuButton" onClick={() => setMobileOpen(true)}><Menu size={19} /></button>
      <Sidebar active={active} setActive={setActive} mobileOpen={mobileOpen} setMobileOpen={setMobileOpen} />
      <main>
        <Header symbol={symbol} setSymbol={setSymbol} tf={tf} setTf={setTf} health={health} />
        {active === 'overview' && <Overview snapshot={snapshot} candle={candle} decision={decision} candles={candles} symbol={symbol} tf={tf} />}
        {active === 'chart' && <Overview snapshot={snapshot} candle={candle} decision={decision} candles={candles} symbol={symbol} tf={tf} />}
        {active === 'flow' && <Overview snapshot={snapshot} candle={candle} decision={decision} candles={candles} symbol={symbol} tf={tf} />}
        {active === 'dom' && <Overview snapshot={snapshot} candle={candle} decision={decision} candles={candles} symbol={symbol} tf={tf} />}
        {active === 'quant' && <QuantView decision={decision} />}
        {active === 'news' && <NewsCalendar />}
      </main>
      <button className="assistantFab" onClick={() => setAssistantOpen(true)}><Bot size={18} /><span>AI Asistan</span></button>
      <Assistant open={assistantOpen} setOpen={setAssistantOpen} />
    </div>
  )
}
