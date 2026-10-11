/** Time-range presets of the list pages ("son 24 saat", ...), as URL values. */
export const RANGES = ['24h', '7d', '30d', 'all'] as const
export type Range = (typeof RANGES)[number]

const HOURS: Record<Exclude<Range, 'all'>, number> = { '24h': 24, '7d': 7 * 24, '30d': 30 * 24 }

export function parseRange(value: string | null, fallback: Range): Range {
  return RANGES.find((range) => range === value) ?? fallback
}

/** ISO start of the range (``from`` query parameter), or undefined for "all". */
export function rangeStart(range: Range, now = new Date()): string | undefined {
  if (range === 'all') return undefined
  const start = new Date(now.getTime() - HOURS[range] * 3600_000)
  start.setSeconds(0, 0) // a stable query key within the minute
  return start.toISOString()
}
