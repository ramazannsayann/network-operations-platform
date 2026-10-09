/** Locale-aware formatting of times, speeds and VLAN lists. */

const UNITS: [Intl.RelativeTimeFormatUnit, number][] = [
  ['year', 365 * 24 * 3600],
  ['month', 30 * 24 * 3600],
  ['day', 24 * 3600],
  ['hour', 3600],
  ['minute', 60],
  ['second', 1],
]

/** "3 dk. önce" / "3 min. ago". */
export function relativeTime(value: string | Date, language: string, now = new Date()): string {
  const seconds = (new Date(value).getTime() - now.getTime()) / 1000
  const format = new Intl.RelativeTimeFormat(language, { numeric: 'auto', style: 'short' })
  for (const [unit, size] of UNITS) {
    if (Math.abs(seconds) >= size || unit === 'second') {
      return format.format(Math.round(seconds / size), unit)
    }
  }
  return format.format(0, 'second')
}

export function dateTime(value: string | Date, language: string): string {
  return new Intl.DateTimeFormat(language, { dateStyle: 'medium', timeStyle: 'medium' }).format(
    new Date(value),
  )
}

/** 1000 -> "1 Gb/s", 100 -> "100 Mb/s". */
export function speed(mbps: number | null | undefined): string | null {
  if (mbps === null || mbps === undefined) return null
  return mbps >= 1000 && mbps % 1000 === 0 ? `${mbps / 1000} Gb/s` : `${mbps} Mb/s`
}

/** [1, 2, 3, 10] -> "1-3,10" (IOS notation). */
export function vlanList(vlans: number[]): string {
  const sorted = [...new Set(vlans)].sort((a, b) => a - b)
  const parts: string[] = []
  let start = sorted[0]
  let previous = start
  for (const vlan of [...sorted.slice(1), undefined]) {
    if (vlan !== undefined && previous !== undefined && vlan === previous + 1) {
      previous = vlan
      continue
    }
    if (start !== undefined && previous !== undefined)
      parts.push(start === previous ? `${start}` : `${start}-${previous}`)
    start = vlan
    previous = vlan
  }
  return parts.join(',')
}
