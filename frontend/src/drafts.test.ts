import { describe, expect, it } from 'vitest'

import { parseDraftMap, updateDraftMap } from './drafts'

describe('chat drafts', () => {
  it('rejects malformed and non-string stored values', () => {
    expect(parseDraftMap('{broken')).toEqual({})
    expect(parseDraftMap(JSON.stringify({ 7: 'valid', 8: 12 }))).toEqual({ 7: 'valid' })
  })

  it('updates one chat without mutating other drafts', () => {
    const current = { 7: 'first' }
    const next = updateDraftMap(current, 9, 'second')

    expect(current).toEqual({ 7: 'first' })
    expect(next).toEqual({ 7: 'first', 9: 'second' })
  })

  it('removes empty drafts', () => {
    expect(updateDraftMap({ 7: 'first', 9: 'second' }, 7, '')).toEqual({ 9: 'second' })
  })
})
