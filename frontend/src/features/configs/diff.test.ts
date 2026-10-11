import { describe, expect, it } from 'vitest'

import { parseUnifiedDiff, sideBySide } from './diff'
import { tokenize } from './ios'
import { splitRedacted } from './redaction'

const DIFF = `--- dist1 @ 2026-10-10T02:30:00Z
+++ dist1 @ 2026-10-10T12:00:31Z
@@ -70,7 +70,7 @@
 !
 interface GigabitEthernet1/0/2
  description to access2 Gi1/1/1
- switchport trunk allowed vlan 10,20,30,98-99
+ switchport trunk allowed vlan 10,30,98-99
  switchport mode trunk
 !
 interface Vlan99
@@ -101,3 +101,4 @@
 !
-username admin privilege 15 secret 9 <redacted>
+username admin privilege 15 secret 9 <redacted>
+username jdoe privilege 15 secret 9 <redacted>
 !
`

describe('unified diff parsing', () => {
  it('reads labels, hunks and line numbers', () => {
    const diff = parseUnifiedDiff(DIFF)
    expect(diff.fromLabel).toBe('dist1 @ 2026-10-10T02:30:00Z')
    expect(diff.toLabel).toBe('dist1 @ 2026-10-10T12:00:31Z')
    expect(diff.hunks).toHaveLength(2)
    const [first] = diff.hunks
    expect(first?.lines.map((line) => line.type)).toEqual([
      'context',
      'context',
      'context',
      'del',
      'add',
      'context',
      'context',
      'context',
    ])
    expect(first?.lines[3]).toEqual({
      type: 'del',
      text: ' switchport trunk allowed vlan 10,20,30,98-99',
      oldNumber: 73,
      newNumber: null,
    })
    expect(first?.lines[4]?.newNumber).toBe(73)
    expect(first?.lines[5]).toMatchObject({ oldNumber: 74, newNumber: 74 })
  })

  it('pairs removals with the additions after them, side by side', () => {
    const [, second] = parseUnifiedDiff(DIFF).hunks
    if (!second) throw new Error('no second hunk')
    const rows = sideBySide(second)
    expect(rows.map((row) => [row.left?.type ?? null, row.right?.type ?? null])).toEqual([
      ['context', 'context'],
      ['del', 'add'],
      [null, 'add'],
      ['context', 'context'],
    ])
  })

  it('has no hunks for identical versions', () => {
    expect(parseUnifiedDiff('').hunks).toEqual([])
  })
})

describe('IOS highlighting', () => {
  it('keeps every character and marks the parts', () => {
    const line = ' switchport trunk allowed vlan 10,30 <redacted>'
    const tokens = tokenize(line)
    expect(tokens.map((token) => token.text).join('')).toBe(line)
    expect(tokens.find((token) => token.kind === 'command')?.text).toBe('switchport')
    expect(tokens.find((token) => token.kind === 'secret')?.text).toBe('<redacted>')
  })

  it('knows sections, negations, interfaces, addresses and comments', () => {
    expect(tokenize('interface GigabitEthernet1/0/2').map((token) => token.kind)).toEqual([
      'section',
      'plain',
      'interface',
    ])
    expect(tokenize(' no shutdown').map((token) => token.kind)).toEqual([
      'plain',
      'negation',
      'plain',
      'command',
    ])
    expect(tokenize(' ip address 10.255.0.11 255.255.255.224')[5]).toEqual({
      kind: 'address',
      text: '10.255.0.11',
    })
    expect(tokenize('! Last configuration change')).toEqual([
      { kind: 'comment', text: '! Last configuration change' },
    ])
  })

  it('splits text around both redaction markers', () => {
    expect(splitRedacted('a <redacted> b <certificate redacted>')).toEqual([
      { text: 'a ', redacted: false },
      { text: '<redacted>', redacted: 'secret' },
      { text: ' b ', redacted: false },
      { text: '<certificate redacted>', redacted: 'cert' },
    ])
  })
})
