export type StartupStatus = {
  configured: boolean
  authorized: boolean
  state: string
  client_session_exists: boolean
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
