/**
 * Minimal IOS configuration highlighting: comments, commands, "no", interface names,
 * addresses and redaction markers. A tokenizer, not a parser: every character of a line
 * ends up in exactly one token, so the text reads (and copies) unchanged.
 */
import { CERTIFICATE_REDACTED, REDACTED } from './redaction'

export type TokenKind =
  | 'plain'
  | 'comment'
  | 'section'
  | 'command'
  | 'negation'
  | 'interface'
  | 'address'
  | 'secret'
  | 'cert'

export interface Token {
  kind: TokenKind
  text: string
}

const INTERFACE =
  /^(?:(?:Fast|(?:Two|Five|Ten|TwentyFive|Forty|Hundred)?Gigabit)Ethernet|TwentyFiveGigE|HundredGigE|Ethernet|Port-channel|Vlan|Loopback|Tunnel|Gi|Te|Fa|Po|Lo)\d+(?:[/.:]\d+)*$/
const ADDRESS = /^\d{1,3}(?:\.\d{1,3}){3}(?:\/\d{1,2})?$/
const WORDS = /(<redacted>|<certificate redacted>|\s+)/

export function tokenize(line: string): Token[] {
  const indent = /^\s*/.exec(line)?.[0] ?? ''
  const body = line.slice(indent.length)
  const tokens: Token[] = indent ? [{ kind: 'plain', text: indent }] : []
  if (body.startsWith('!')) return [...tokens, { kind: 'comment', text: body }]
  let expectCommand = true
  for (const part of body.split(WORDS)) {
    if (part === '') continue
    if (part === REDACTED) tokens.push({ kind: 'secret', text: part })
    else if (part === CERTIFICATE_REDACTED) tokens.push({ kind: 'cert', text: part })
    else if (/^\s+$/.test(part)) tokens.push({ kind: 'plain', text: part })
    else if (expectCommand && part === 'no') tokens.push({ kind: 'negation', text: part })
    else if (expectCommand) {
      tokens.push({ kind: indent ? 'command' : 'section', text: part })
      expectCommand = false
    } else if (INTERFACE.test(part)) tokens.push({ kind: 'interface', text: part })
    else if (ADDRESS.test(part)) tokens.push({ kind: 'address', text: part })
    else tokens.push({ kind: 'plain', text: part })
  }
  return tokens
}
