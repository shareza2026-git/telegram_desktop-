import { describe, expect, it } from 'vitest'

import { shouldHoldAuthScreen } from './startup'

describe('startup authentication screen', () => {
  it('keeps the loading screen while an existing session reconnects', () => {
    expect(shouldHoldAuthScreen({
      configured: true,
      authorized: false,
      state: 'CONNECTING',
      client_session_exists: true
    })).toBe(true)
  })

  it('shows login after reconnect confirms authorization is required', () => {
    expect(shouldHoldAuthScreen({
      configured: true,
      authorized: false,
      state: 'AUTH_REQUIRED',
      client_session_exists: true
    })).toBe(false)
  })

  it('does not hide first-run setup', () => {
    expect(shouldHoldAuthScreen({
      configured: false,
      authorized: false,
      state: 'UNCONFIGURED',
      client_session_exists: false
    })).toBe(false)
  })
})
