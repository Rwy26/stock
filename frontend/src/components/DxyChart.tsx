import { useEffect, useRef } from 'react'
import type { IChartApi, ISeriesApi } from 'lightweight-charts'
import { fetchJson } from '../lib/api'

type LWC = typeof import('lightweight-charts')

type OhlcRow = { time: string; open: number; high: number; low: number; close: number }
type DxyData = { asOf: string | null; ohlcv: OhlcRow[] }

export function DxyChart() {
  const hostRef  = useRef<HTMLDivElement>(null)
  const chartRef = useRef<IChartApi | null>(null)
  const seriesRef = useRef<ISeriesApi<'Candlestick'> | null>(null)
  const lwcRef   = useRef<LWC | null>(null)

  useEffect(() => {
    const host = hostRef.current
    if (!host || chartRef.current) return

    let cancelled = false
    ;(async () => {
      try {
        if (!lwcRef.current) lwcRef.current = await import('lightweight-charts')
        if (cancelled || !lwcRef.current) return
        const lwc = lwcRef.current

        const chart = lwc.createChart(host, {
          autoSize: true,
          height: 200,
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

        const candles = chart.addSeries(lwc.CandlestickSeries, {
          upColor:        '#34d399',
          downColor:      '#f87171',
          borderUpColor:  '#34d399',
          borderDownColor:'#f87171',
          wickUpColor:    '#6ee7b7',
          wickDownColor:  '#fca5a5',
        })

        chartRef.current  = chart
        seriesRef.current = candles
      } catch {
        // silent
      }
    })()
    return () => { cancelled = true }
  }, [])

  useEffect(() => {
    let cancelled = false

    const load = () => {
      fetchJson<DxyData>('/api/macro/dxy')
        .then((d) => {
          if (cancelled || !seriesRef.current) return
          seriesRef.current.setData(d.ohlcv.filter(r => r.close != null))
          chartRef.current?.timeScale().fitContent()
        })
        .catch(() => { /* silent */ })
    }

    load()
    const id = window.setInterval(load, 5 * 60 * 1000)
    return () => { cancelled = true; window.clearInterval(id) }
  }, [])

  return <div ref={hostRef} style={{ height: 200 }} />
}
