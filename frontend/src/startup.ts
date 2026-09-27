export type StartupStatus = {
  configured: boolean
  authorized: boolean
  state: string
  client_session_exists: boolean
  session_auth_key_present?: boolean
}

// A local cache is usable while reconnecting; it never grants network authorization.
export function canShowCachedWorkspace(status: StartupStatus | null, dialogCount: number): boolean {
  return Boolean(status?.configured && status.client_session_exists &&
    status.session_auth_key_present && dialogCount > 0 &&
    ['STARTING', 'CONNECTING', 'PROXY_ERROR'].includes(status.state))
}

export function shouldHoldAuthScreen(status: StartupStatus | null): boolean {
  if (!status) return true
  return Boolean(
    status.configured &&
    status.client_session_exists &&
    !status.authorized &&
    (status.state === 'STARTING' || status.state === 'CONNECTING')
  )
}
