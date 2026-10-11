/** Parsing the API's unified diff (GET /configs/diff) for the unified and split views. */

export type DiffLineType = 'context' | 'add' | 'del'

export interface DiffLine {
  type: DiffLineType
  text: string
  oldNumber: number | null
  newNumber: number | null
}

export interface Hunk {
  header: string
  lines: DiffLine[]
}

export interface ParsedDiff {
  fromLabel: string | null
  toLabel: string | null
  hunks: Hunk[]
}

const HUNK = /^@@ -(\d+)(?:,\d+)? \+(\d+)(?:,\d+)? @@/

export function parseUnifiedDiff(text: string): ParsedDiff {
  const parsed: ParsedDiff = { fromLabel: null, toLabel: null, hunks: [] }
  let hunk: Hunk | null = null
  let oldNumber = 0
  let newNumber = 0
  for (const line of text.split('\n')) {
    if (hunk === null && line.startsWith('--- ')) {
      parsed.fromLabel = line.slice(4)
      continue
    }
    if (hunk === null && line.startsWith('+++ ')) {
      parsed.toLabel = line.slice(4)
      continue
    }
    const header = HUNK.exec(line)
    if (header) {
      hunk = { header: line, lines: [] }
      parsed.hunks.push(hunk)
      oldNumber = Number(header[1])
      newNumber = Number(header[2])
      continue
    }
    if (hunk === null || line === '') continue
    const marker = line[0]
    const content = line.slice(1)
    if (marker === '+') {
      hunk.lines.push({ type: 'add', text: content, oldNumber: null, newNumber: newNumber++ })
    } else if (marker === '-') {
      hunk.lines.push({ type: 'del', text: content, oldNumber: oldNumber++, newNumber: null })
    } else if (marker === ' ') {
      hunk.lines.push({
        type: 'context',
        text: content,
        oldNumber: oldNumber++,
        newNumber: newNumber++,
      })
    }
  }
  return parsed
}

export interface SideRow {
  left: DiffLine | null
  right: DiffLine | null
}

/** Side by side: context on both sides; a run of removals next to the additions after it. */
export function sideBySide(hunk: Hunk): SideRow[] {
  const rows: SideRow[] = []
  let removed: DiffLine[] = []
  let added: DiffLine[] = []
  const flush = () => {
    for (let i = 0; i < Math.max(removed.length, added.length); i++) {
      rows.push({ left: removed[i] ?? null, right: added[i] ?? null })
    }
    removed = []
    added = []
  }
  for (const line of hunk.lines) {
    if (line.type === 'del') {
      if (added.length) flush()
      removed.push(line)
    } else if (line.type === 'add') {
      added.push(line)
    } else {
      flush()
      rows.push({ left: line, right: line })
    }
  }
  flush()
  return rows
}
