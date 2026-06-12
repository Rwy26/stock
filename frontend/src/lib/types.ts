import type { ExclusionInfo } from './exclusion'

// ─── Portfolio ────────────────────────────────────────────────────────────────

export type PortfolioPosition = {
  name: string
  code: string
  qty: number
  avgBuy: number
  current: number
  buyDate: string
}

export type PortfolioResponse = {
  asOf: string
  cash?: number | null
  positions: PortfolioPosition[]
}

// ─── Stock search / watchlist ─────────────────────────────────────────────────

export type StockRow = {
  name: string
  code: string
  price: number
  changeRate: number
  score: number
}

export type SearchResponse = {
  items: StockRow[]
  cautions?: ExclusionInfo[]
  cautionMessage?: string
}

/** /api/watchlist을 "코드 목록만 필요한" 컨텍스트에서 사용하는 최소 응답 타입 */
export type WatchlistCodesResponse = {
  items: Array<{ code: string }>
}
