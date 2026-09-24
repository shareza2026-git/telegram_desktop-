import { describe, expect, it } from 'vitest'

import { DEFAULT_PREFERENCES, parsePreferences, resolvedTheme } from './preferences'

describe('client preferences', () => {
  it('uses safe defaults for missing or invalid local data', () => {
    expect(parsePreferences(null)).toEqual(DEFAULT_PREFERENCES)
    expect(parsePreferences('{broken')).toEqual(DEFAULT_PREFERENCES)
  })

  it('keeps supported values and rejects an unknown theme', () => {
    expect(parsePreferences(JSON.stringify({ theme: 'light', compact: true, autoLoadPhotos: false }))).toEqual({
      theme: 'light', compact: true, autoLoadPhotos: false
    })
    expect(parsePreferences(JSON.stringify({ theme: 'neon', compact: true }))).toEqual({
      theme: 'system', compact: true, autoLoadPhotos: true
    })
  })

  it('resolves the system theme without storing platform details', () => {
    expect(resolvedTheme('system', true)).toBe('light')
    expect(resolvedTheme('system', false)).toBe('dark')
    expect(resolvedTheme('dark', true)).toBe('dark')
  })
})
