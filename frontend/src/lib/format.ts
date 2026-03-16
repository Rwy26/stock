export function formatNumber(value: number): string {
  return new Intl.NumberFormat('ko-KR').format(value)
}

export function formatKRW(value: number): string {
  return `₩${formatNumber(value)}`
}

export function formatPercent(value: number, fractionDigits = 2): string {
  const sign = value > 0 ? '+' : value < 0 ? '' : ''
  return `${sign}${value.toFixed(fractionDigits)}%`
}
