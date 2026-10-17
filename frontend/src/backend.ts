import { invoke } from '@tauri-apps/api/core'

// Each app folder runs its own backend on its own port (set at startup).
export let backendBase = (import.meta.env.VITE_BACKEND_URL || 'http://127.0.0.1:8110').replace(/\/$/, '')
export let socketBase = backendBase.replace(/^http/, 'ws')

export function configureBackend(port: number) {
  backendBase = 'http://127.0.0.1:' + port
  socketBase = 'ws://127.0.0.1:' + port
}

// Per-launch secret from the Tauri shell. The backend rejects every request
// without it, so other programs and websites cannot drive the account.
let token = ''
const tokenReady: Promise<string> = (async () => {
  if (!('__TAURI_INTERNALS__' in window)) return ''
  try {
    token = await invoke<string>('backend_token')
  } catch {
    token = ''
  }
  return token
})()

export function backendReady() {
  return tokenReady
}

/** URL for <img>/<video>/<audio>/WebSocket, which cannot send headers. */
export function authedUrl(url: string) {
  if (!token) return url
  return url + (url.includes('?') ? '&' : '?') + 'token=' + encodeURIComponent(token)
}

export function backendUrl(path: string) {
  return authedUrl(backendBase + path)
}

export async function backendFetch(path: string, options?: RequestInit) {
  await tokenReady
  const headers = new Headers(options?.headers)
  if (token) headers.set('X-Desktop-Token', token)
  return fetch(backendBase + path, { ...options, headers })
}

async function failure(response: Response, fallback: string) {
  const body = await response.text()
  let message = body || fallback
  try {
    const parsed = JSON.parse(body) as { detail?: unknown }
    if (typeof parsed.detail === 'string' && parsed.detail) message = parsed.detail
  } catch {
    // Keep the plain response body when the backend did not return JSON.
  }
  return new Error(message)
}

export async function api<T>(path: string, options?: RequestInit): Promise<T> {
  const headers = new Headers(options?.headers)
  if (!(options?.body instanceof FormData)) headers.set('Content-Type', 'application/json')
  let response: Response
  try {
    response = await backendFetch(path, { ...options, headers })
  } catch {
    // The browser hides the real reason; the backend is down or restarting.
    throw new Error('ارتباط با سرویس محلی برنامه برقرار نشد؛ چند لحظه بعد دوباره تلاش کنید.')
  }
  if (response.ok) return response.json() as Promise<T>
  throw await failure(response, 'درخواست انجام نشد.')
}

export async function apiBlob(path: string, fallback: string) {
  const response = await backendFetch(path)
  if (response.ok) return response.blob()
  throw await failure(response, fallback)
}

export function chatPath(chatId: number) {
  return '/api/telegram/chats/' + encodeURIComponent(String(chatId))
}

export function avatarUrl(chatId: number) {
  return backendUrl(chatPath(chatId) + '/photo')
}

export function mediaUrl(chatId: number, messageId: number, options: { thumb?: boolean; download?: boolean } = {}) {
  const query = options.thumb ? '?thumb=true' : options.download ? '?download=true' : ''
  return backendUrl(chatPath(chatId) + '/messages/' + encodeURIComponent(String(messageId)) + '/media' + query)
}
