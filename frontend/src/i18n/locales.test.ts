import { describe, expect, it } from 'vitest'

import en from './locales/en.json'
import tr from './locales/tr.json'

function keys(tree: object, prefix = ''): string[] {
  return Object.entries(tree).flatMap(([key, value]) =>
    typeof value === 'object' && value !== null
      ? keys(value as object, `${prefix}${key}.`)
      : [`${prefix}${key}`],
  )
}

describe('translations', () => {
  it('have the same keys in Turkish and English', () => {
    expect(keys(tr).sort()).toEqual(keys(en).sort())
  })

  it('have no empty strings', () => {
    for (const tree of [tr, en]) {
      const empty = keys(tree).filter((key) => {
        const value = key
          .split('.')
          .reduce<unknown>((node, part) => (node as Record<string, unknown>)[part], tree)
        return value === ''
      })
      expect(empty).toEqual([])
    }
  })
})
