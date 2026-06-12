type StatusChipProps = {
  on?: boolean
  children: React.ReactNode
}

export function StatusChip({ on, children }: StatusChipProps) {
  const cls = on === true ? 'chip on' : on === false ? 'chip off' : 'chip'
  return <span className={cls}>{children}</span>
}
