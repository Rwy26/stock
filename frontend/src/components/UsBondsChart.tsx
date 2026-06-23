import { useEffect, useRef } from 'react'
import type { IChartApi, ISeriesApi } from 'lightweight-charts'
import { fetchSnapshot } from '../lib/api'

type LWC = typeof import('lightweight-charts')

type OhlcRow   = { time: string; open: number; high: number; low: number; close: number }
type ValueRow  = { time: string; value: number }
type BbRow     = { time: string; upper: number; middle: number; lower: number }

type UsBondsData = {
  asOf: string | null
  tnx: OhlcRow[]
  tyx: ValueRow[]
  dominance: ValueRow[]
  bb: BbRow[]
  rsi: ValueRow[]
}

const CHART_OPTS = (height: number) => ({
  autoSize: true,
  height,
  layout: {
    background: { color: 'transparent' },
    textColor: 'rgba(255,255,255,0.78)',
    fontSize: 11,
  },
  grid: {
    vertLines: { color: 'rgba(255,255,255,0.07)' },
    horzLines: { color: 'rgba(255,255,255,0.07)' },
  },
  timeScale: { borderColor: 'rgba(255,255,255,0.15)', timeVisible: true },
  rightPriceScale: { borderColor: 'rgba(255,255,255,0.15)' },
  crosshair: {
    vertLine: { color: 'rgba(255,255,255,0.18)' },
    horzLine: { color: 'rgba(255,255,255,0.18)' },
  },
})

export function UsBondsChart() {
  const mainRef = useRef<HTMLDivElement>(null)
  const subRef  = useRef<HTMLDivElement>(null)

  const mainChartRef = useRef<IChartApi | null>(null)
  const subChartRef  = useRef<IChartApi | null>(null)
  const lwcRef       = useRef<LWC | null>(null)

  // series refs
  const tnxRef    = useRef<ISeriesApi<'Candlestick'> | null>(null)
  const tyxRef    = useRef<ISeriesApi<'Line'> | null>(null)
  const domRef    = useRef<ISeriesApi<'Area'> | null>(null)
  const bbUpRef   = useRef<ISeriesApi<'Line'> | null>(null)
  const bbMidRef  = useRef<ISeriesApi<'Line'> | null>(null)
  const bbLoRef   = useRef<ISeriesApi<'Line'> | null>(null)
  const rsiRef    = useRef<ISeriesApi<'Line'> | null>(null)
  const rsi70Ref  = useRef<ISeriesApi<'Line'> | null>(null)
  const rsi30Ref  = useRef<ISeriesApi<'Line'> | null>(null)

  // init charts once
  useEffect(() => {
    const main = mainRef.current
    const sub  = subRef.current
    if (!main || !sub) return
    if (mainChartRef.current) return

    let cancelled = false
    ;(async () => {
      try {
        if (!lwcRef.current) lwcRef.current = await import('lightweight-charts')
        if (cancelled || !lwcRef.current) return
        const lwc = lwcRef.current

        // ── Main chart ──────────────────────────────────────────────────
        const mc = lwc.createChart(main, CHART_OPTS(210))
        mainChartRef.current = mc

        // 10년물 캔들 (파란 계열)
        const tnxS = mc.addSeries(lwc.CandlestickSeries, {
          upColor:        '#60a5fa',
          downColor:      '#818cf8',
          borderUpColor:  '#60a5fa',
          borderDownColor:'#818cf8',
          wickUpColor:    '#93c5fd',
          wickDownColor:  '#a5b4fc',
          priceScaleId:   'right',
        })
        tnxRef.current = tnxS

        // 30년물 라인 (주황 계열)
        const tyxS = mc.addSeries(lwc.LineSeries, {
          color:        '#fb923c',
          lineWidth:    2,
          priceScaleId: 'right',
        })
        tyxRef.current = tyxS

        // 도미넌스 영역 (초록, 왼쪽 스케일)
        const domS = mc.addSeries(lwc.AreaSeries, {
          topColor:     'rgba(52,211,153,0.25)',
          bottomColor:  'rgba(52,211,153,0.02)',
          lineColor:    'rgba(52,211,153,0.8)',
          lineWidth:    1,
          priceScaleId: 'left',
        })
        domRef.current = domS
        mc.priceScale('left').applyOptions({ visible: true, borderColor: 'rgba(255,255,255,0.15)' })

        // ── Sub chart ───────────────────────────────────────────────────
        const sc = lwc.createChart(sub, CHART_OPTS(130))
        subChartRef.current = sc

        // 볼린저 상단 (연한 하늘)
        const bbUpS = sc.addSeries(lwc.LineSeries, {
          color: 'rgba(147,197,253,0.6)', lineWidth: 1,
          lineStyle: 2,  // dashed
          priceScaleId: 'right',
        })
        bbUpRef.current = bbUpS

        // 볼린저 중간 SMA (흰색)
        const bbMidS = sc.addSeries(lwc.LineSeries, {
          color: 'rgba(255,255,255,0.55)', lineWidth: 1,
          priceScaleId: 'right',
        })
        bbMidRef.current = bbMidS

        // 볼린저 하단
        const bbLoS = sc.addSeries(lwc.LineSeries, {
          color: 'rgba(147,197,253,0.6)', lineWidth: 1,
          lineStyle: 2,
          priceScaleId: 'right',
        })
        bbLoRef.current = bbLoS

        // RSI 라인 (보라)
        const rsiS = sc.addSeries(lwc.LineSeries, {
          color: '#c084fc', lineWidth: 2,
          priceScaleId: 'left',
        })
        rsiRef.current = rsiS

        // RSI 기준선 70 (빨강 점선)
        const r70 = sc.addSeries(lwc.LineSeries, {
          color: 'rgba(248,113,113,0.6)', lineWidth: 1, lineStyle: 2,
          priceScaleId: 'left', crosshairMarkerVisible: false, lastValueVisible: false,
        })
        rsi70Ref.current = r70

        // RSI 기준선 30 (파랑 점선)
        const r30 = sc.addSeries(lwc.LineSeries, {
          color: 'rgba(96,165,250,0.6)', lineWidth: 1, lineStyle: 2,
          priceScaleId: 'left', crosshairMarkerVisible: false, lastValueVisible: false,
        })
        rsi30Ref.current = r30

        sc.priceScale('left').applyOptions({
          visible: true,
          borderColor: 'rgba(255,255,255,0.15)',
          scaleMargins: { top: 0.05, bottom: 0.05 },
        })
        sc.priceScale('right').applyOptions({
          scaleMargins: { top: 0.05, bottom: 0.05 },
        })

        // ── Sync time scales ────────────────────────────────────────────
        mc.timeScale().subscribeVisibleLogicalRangeChange((range) => {
          if (range && subChartRef.current)
            subChartRef.current.timeScale().setVisibleLogicalRange(range)
        })
        sc.timeScale().subscribeVisibleLogicalRangeChange((range) => {
          if (range && mainChartRef.current)
            mainChartRef.current.timeScale().setVisibleLogicalRange(range)
        })

      } catch {
        // silent – chart area stays as placeholder
      }
    })()
    return () => { cancelled = true }
  }, [])

  // fetch & populate data
  useEffect(() => {
    let cancelled = false

    const load = () => {
      fetchSnapshot<UsBondsData>('dashboard-macro-us-bonds.json', '/api/macro/us-bonds')
        .then((d) => {
          if (cancelled) return
          if (!tnxRef.current || !tyxRef.current || !domRef.current) return

          tnxRef.current.setData(d.tnx.filter(r => r.close != null))
          tyxRef.current.setData(d.tyx.filter(r => r.value != null))
          domRef.current.setData(d.dominance.filter(r => r.value != null))

          if (bbUpRef.current && bbMidRef.current && bbLoRef.current) {
            bbUpRef.current.setData(d.bb.filter(r => r.upper != null).map(r => ({ time: r.time, value: r.upper })))
            bbMidRef.current.setData(d.bb.filter(r => r.middle != null).map(r => ({ time: r.time, value: r.middle })))
            bbLoRef.current.setData(d.bb.filter(r => r.lower != null).map(r => ({ time: r.time, value: r.lower })))
          }

          if (rsiRef.current && d.rsi.length) {
            rsiRef.current.setData(d.rsi.filter(r => r.value != null))
            // 기준선: RSI 범위 전체에 70 / 30 수평선
            const times = d.rsi.map(r => r.time)
            if (rsi70Ref.current)
              rsi70Ref.current.setData(times.map(t => ({ time: t, value: 70 })))
            if (rsi30Ref.current)
              rsi30Ref.current.setData(times.map(t => ({ time: t, value: 30 })))
          }

          mainChartRef.current?.timeScale().fitContent()
          subChartRef.current?.timeScale().fitContent()
        })
        .catch(() => { /* silent */ })
    }

    load()
    const id = window.setInterval(load, 30 * 60 * 1000)  // 30분 갱신 (정적 스냅샷 차등 폴링)
    return () => { cancelled = true; window.clearInterval(id) }
  }, [])

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 2 }}>
      {/* legend */}
      <div style={{ display: 'flex', gap: 14, fontSize: '0.72rem', color: 'rgba(255,255,255,0.6)', padding: '0 4px 4px' }}>
        <span><span style={{ color: '#60a5fa', fontWeight: 700 }}>■</span> 10Y 캔들</span>
        <span><span style={{ color: '#fb923c', fontWeight: 700 }}>─</span> 30Y 라인</span>
        <span><span style={{ color: '#34d399', fontWeight: 700 }}>▬</span> 도미넌스(좌)</span>
        <span style={{ marginLeft: 'auto', color: 'rgba(255,255,255,0.4)' }}>하단: BB(20,2) + RSI(14)</span>
      </div>
      <div ref={mainRef} style={{ height: 210 }} />
      <div ref={subRef}  style={{ height: 130 }} />
    </div>
  )
}
