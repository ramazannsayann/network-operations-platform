/**
 * The markers the API puts where a secret was (backend: netops/configmgmt/redact.py,
 * ADR-0007). The UI never sees a secret; it only shows where one is.
 */
export const REDACTED = '<redacted>'
export const CERTIFICATE_REDACTED = '<certificate redacted>'

const MARKERS = /(<redacted>|<certificate redacted>)/

export type Piece =
  { text: string; redacted: false } | { text: string; redacted: 'secret' | 'cert' }

/** "snmp-server community <redacted> RO" -> plain, marker, plain. */
export function splitRedacted(text: string): Piece[] {
  return text
    .split(MARKERS)
    .filter((part) => part !== '')
    .map((part) =>
      part === REDACTED
        ? { text: part, redacted: 'secret' }
        : part === CERTIFICATE_REDACTED
          ? { text: part, redacted: 'cert' }
          : { text: part, redacted: false },
    )
}
