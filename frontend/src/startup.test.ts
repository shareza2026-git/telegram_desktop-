import { describe, expect, it } from 'vitest'

import { shouldHoldAuthScreen, canShowCachedWorkspace } from './startup'

describe('startup authentication screen', () => {
  it('shows stored dialogs during reconnect without granting authorization', () => {
    const status = {configured: true, authorized: false, state: 'CONNECTING',
      client_session_exists: true, session_auth_key_present: true}
    expect(canShowCachedWorkspace(status, 3)).toBe(true)
    expect(canShowCachedWorkspace(status, 0)).toBe(false)
    expect(canShowCachedWorkspace({...status, session_auth_key_present: false}, 3)).toBe(false)
    expect(canShowCachedWorkspace({...status, state: 'AUTH_REQUIRED'}, 3)).toBe(false)
    expect(status.authorized).toBe(false)
  })
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
