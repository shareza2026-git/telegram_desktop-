import { useEffect, useMemo, useRef, useState, type FormEvent } from 'react'

type Dialog = {
  chat_id: number
  title: string
  dialog_type: string
  username?: string | null
  unread_count: number
  pinned: boolean
  archived: boolean
}

type ChatInfo = {
  chat_id: number
  title: string
  dialog_type: string
  username?: string | null
  participants_count?: number | null
  status?: string | null
  is_bot: boolean
  verified: boolean
  scam: boolean
  fake: boolean
  photo_available: boolean
}

type MediaInfo = {
  kind: 'photo' | 'video' | 'audio' | 'file' | 'other'
  name?: string | null
  size?: number | null
  mime_type?: string | null
  playable: boolean
  downloadable: boolean
}

type Message = {
  chat_id: number
  message_id: number
  text: string
  date: string
  sender_id?: number | null
  sender_name?: string | null
  outgoing: boolean
  edited: boolean
  reply_to_message_id?: number | null
  media?: MediaInfo | null
  deleted: boolean
}

type Status = {
  configured: boolean
  connected: boolean
  authorized: boolean
  state: string
  display_name?: string | null
  active_route?: string | null
  source_session_available: boolean
  client_session_exists: boolean
  last_error?: string | null
}

type AuthResponse = {
  code_sent: boolean
  requires_2fa: boolean
  authorized: boolean
}

type AuthStep = 'phone' | 'code' | 'password'
type FolderKey = 'all' | 'private' | 'groups' | 'channels' | 'archived'
type MediaState = 'loading' | 'ready' | 'downloading' | 'done' | 'error'

const HISTORY_PAGE_SIZE = 80
const backendBase = (import.meta.env.VITE_BACKEND_URL || 'http://127.0.0.1:8110').replace(/\/$/, '')
const socketBase = backendBase.replace(/^http/, 'ws')
const mediaLabels: Record<MediaInfo['kind'], string> = {
  photo: 'تصویر',
  video: 'ویدئو',
  audio: 'صدا',
  file: 'فایل',
  other: 'رسانه'
}

async function api<T>(path: string, options?: RequestInit): Promise<T> {
  const response = await fetch(backendBase + path, {
    ...options,
    headers: { 'Content-Type': 'application/json', ...(options?.headers || {}) }
  })
  if (response.ok) return response.json() as Promise<T>

  const body = await response.text()
  let message = body || 'درخواست انجام نشد.'
  try {
    const parsed = JSON.parse(body) as { detail?: string }
    if (parsed.detail) message = parsed.detail
  } catch {
    // Keep the plain response body when the backend did not return JSON.
  }
  throw new Error(message)
}

function formatTime(value: string) {
  return new Intl.DateTimeFormat('fa-IR', { hour: '2-digit', minute: '2-digit' }).format(new Date(value))
}

function formatBytes(value: number | null | undefined) {
  if (value == null || value < 0) return 'اندازه نامشخص'
  if (value < 1024) return value + ' B'

  const units = ['KB', 'MB', 'GB']
  let amount = value
  let index = -1
  while (amount >= 1024 && index < units.length - 1) {
    amount /= 1024
    index += 1
  }
  const digits = amount >= 10 || index === 0 ? 0 : 1
  return amount.toFixed(digits) + ' ' + units[index]
}

function mediaKindLabel(kind: MediaInfo['kind']) {
  return mediaLabels[kind]
}

function statusLabel(value: string) {
  const labels: Record<string, string> = {
    UNCONFIGURED: 'تنظیمات ناقص',
    IMPORT_READY: 'آماده انتقال سشن',
    CONNECTING: 'در حال اتصال',
    CONNECTED: 'متصل',
    AUTH_REQUIRED: 'نیاز به ورود',
    PROXY_ERROR: 'خطای مسیر اتصال',
    STOPPED: 'متوقف'
  }
  return labels[value] || value
}

function errorMessage(error: unknown, fallback: string) {
  return error instanceof Error && error.message ? error.message : fallback
}

function dialogTypeLabel(value: string) {
  const labels: Record<string, string> = {
    user: 'گفت‌وگوی شخصی',
    group: 'گروه',
    supergroup: 'سوپرگروه',
    channel: 'کانال'
  }
  return labels[value] || value
}

function presenceLabel(value: string | null | undefined) {
  const labels: Record<string, string> = {
    online: 'آنلاین',
    offline: 'آفلاین',
    recently: 'اخیراً آنلاین',
    last_week: 'آخرین بازدید این هفته',
    last_month: 'آخرین بازدید این ماه'
  }
  return value ? labels[value] || value : ''
}

function avatarUrl(chatId: number) {
  return backendBase + '/api/telegram/chats/' + encodeURIComponent(String(chatId)) + '/photo'
}

function ChatAvatar({ chatId, title, className = '' }: { chatId: number; title: string; className?: string }) {
  const [failed, setFailed] = useState(false)

  useEffect(() => {
    setFailed(false)
  }, [chatId])

  return (
    <span className={'avatar ' + className}>
      <span className="avatar-fallback">{title.slice(0, 1)}</span>
      {!failed && (
        <img
          src={avatarUrl(chatId)}
          alt=""
          loading="lazy"
          onError={() => setFailed(true)}
        />
      )}
    </span>
  )
}

function App() {
  const [status, setStatus] = useState<Status | null>(null)
  const [dialogs, setDialogs] = useState<Dialog[]>([])
  const [selected, setSelected] = useState<Dialog | null>(null)
  const [chatInfo, setChatInfo] = useState<ChatInfo | null>(null)
  const [messages, setMessages] = useState<Message[]>([])
  const [query, setQuery] = useState('')
  const [draft, setDraft] = useState('')
  const [error, setError] = useState('')
  const [importing, setImporting] = useState(false)
  const [authStep, setAuthStep] = useState<AuthStep>('phone')
  const [phone, setPhone] = useState('')
  const [code, setCode] = useState('')
  const [password, setPassword] = useState('')
  const [authBusy, setAuthBusy] = useState(false)
  const [authNotice, setAuthNotice] = useState('')
  const [activeFolder, setActiveFolder] = useState<FolderKey>('all')
  const [loadingOlder, setLoadingOlder] = useState(false)
  const [hasOlder, setHasOlder] = useState(false)
  const [mediaStates, setMediaStates] = useState<Record<string, MediaState>>({})
  const [replyingTo, setReplyingTo] = useState<Message | null>(null)
  const [editing, setEditing] = useState<Message | null>(null)
  const [composerBusy, setComposerBusy] = useState(false)
  const [uploadBusy, setUploadBusy] = useState(false)
  const [uploadName, setUploadName] = useState('')
  const fileInputRef = useRef<HTMLInputElement>(null)
  const selectedChatIdRef = useRef<number | null>(null)
  const [messageActionBusy, setMessageActionBusy] = useState<string | null>(null)
  const [messageSearchOpen, setMessageSearchOpen] = useState(false)
  const [messageQuery, setMessageQuery] = useState('')
  const [searchResults, setSearchResults] = useState<Message[]>([])
  const [searchBusy, setSearchBusy] = useState(false)
  const [searchPerformed, setSearchPerformed] = useState(false)
  const [forwarding, setForwarding] = useState<Message | null>(null)
  const [forwardQuery, setForwardQuery] = useState('')
  const [forwardTargetBusy, setForwardTargetBusy] = useState<number | null>(null)

  const visibleDialogs = useMemo(() => {
    let values = dialogs
    if (activeFolder === 'private') values = values.filter(item => item.dialog_type === 'user' && !item.archived)
    if (activeFolder === 'groups') values = values.filter(item => (item.dialog_type === 'group' || item.dialog_type === 'supergroup') && !item.archived)
    if (activeFolder === 'channels') values = values.filter(item => item.dialog_type === 'channel' && !item.archived)
    if (activeFolder === 'archived') values = values.filter(item => item.archived)
    if (activeFolder === 'all') values = values.filter(item => !item.archived)

    const value = query.trim().toLocaleLowerCase()
    if (!value) return values
    return values.filter(item => item.title.toLocaleLowerCase().includes(value))
  }, [activeFolder, dialogs, query])

  useEffect(() => {
    selectedChatIdRef.current = selected?.chat_id || null
  }, [selected?.chat_id])

  const forwardDialogs = useMemo(() => {
    const value = forwardQuery.trim().toLocaleLowerCase()
    if (!value) return dialogs
    return dialogs.filter(item => (
      item.title.toLocaleLowerCase().includes(value)
      || Boolean(item.username?.toLocaleLowerCase().includes(value))
    ))
  }, [dialogs, forwardQuery])

  useEffect(() => {
    api<Status>('/api/telegram/status').then(setStatus).catch(error => setError(errorMessage(error, 'اتصال به هسته تلگرام برقرار نشد.')))
    api<Dialog[]>('/api/telegram/dialogs').then(setDialogs).catch(() => undefined)

    const socket = new WebSocket(socketBase + '/ws/telegram')
    socket.onmessage = event => {
      const packet = JSON.parse(event.data) as { type: string; data: Status | Message }
      if (packet.type === 'READY') setStatus(packet.data as Status)
      if (packet.type === 'MESSAGE_NEW' || packet.type === 'MESSAGE_EDITED') {
        const message = packet.data as Message
        if (selected?.chat_id === message.chat_id) {
          setMessages(current => {
            const without = current.filter(item => item.message_id !== message.message_id)
            return [...without, message].sort((a, b) => a.message_id - b.message_id)
          })
        }
      }
      if (packet.type === 'MESSAGE_DELETED') {
        const deleted = packet.data as { chat_id: number; message_id: number }
        if (selected?.chat_id === deleted.chat_id) {
          setMessages(current => current.map(item => item.message_id === deleted.message_id ? { ...item, deleted: true, text: '' } : item))
        }
      }
    }
    return () => socket.close()
  }, [selected?.chat_id])

  useEffect(() => {
    if (!selected) {
      setMessages([])
      setHasOlder(false)
      setChatInfo(null)
      setReplyingTo(null)
      setEditing(null)
      setDraft('')
      setMessageSearchOpen(false)
      setMessageQuery('')
      setSearchResults([])
      setSearchPerformed(false)
      setForwarding(null)
      setForwardQuery('')
      return
    }
    setMessages([])
    setHasOlder(false)
    setChatInfo(null)
    setReplyingTo(null)
    setEditing(null)
    setDraft('')
    setMessageSearchOpen(false)
    setMessageQuery('')
    setSearchResults([])
    setSearchPerformed(false)
    setForwarding(null)
    setForwardQuery('')
    api<ChatInfo>('/api/telegram/chats/' + selected.chat_id)
      .then(setChatInfo)
      .catch(() => setChatInfo(null))

    api<Message[]>('/api/telegram/chats/' + selected.chat_id + '/messages?limit=' + HISTORY_PAGE_SIZE)
      .then(items => {
        setMessages(items)
        setHasOlder(items.length === HISTORY_PAGE_SIZE)
      })
      .catch(error => setError(errorMessage(error, 'تاریخچه این گفتگو دریافت نشد.')))

    api<{ chat_id: number; read: boolean }>('/api/telegram/chats/' + selected.chat_id + '/read', { method: 'POST' })
      .then(() => {
        setDialogs(current => current.map(item => item.chat_id === selected.chat_id ? { ...item, unread_count: 0 } : item))
        setSelected(current => current && current.chat_id === selected.chat_id ? { ...current, unread_count: 0 } : current)
      })
      .catch(() => undefined)
  }, [selected?.chat_id])

  async function refreshDialogs() {
    try {
      setDialogs(await api<Dialog[]>('/api/telegram/dialogs'))
    } catch (caught) {
      setError(errorMessage(caught, 'به‌روزرسانی گفتگوها انجام نشد.'))
    }
  }

  async function loadOlder() {
    if (!selected || loadingOlder || !hasOlder || !messages.length) return
    setLoadingOlder(true)
    const oldestId = messages[0].message_id
    try {
      const older = await api<Message[]>(
        '/api/telegram/chats/' + selected.chat_id + '/messages?limit=' + HISTORY_PAGE_SIZE + '&offset_id=' + oldestId
      )
      setMessages(current => {
        const known = new Set(current.map(item => item.message_id))
        return [...older.filter(item => !known.has(item.message_id)), ...current]
      })
      setHasOlder(older.length === HISTORY_PAGE_SIZE)
    } catch (caught) {
      setError(errorMessage(caught, 'پیام‌های قدیمی‌تر دریافت نشد.'))
    } finally {
      setLoadingOlder(false)
    }
  }

  async function refreshAuthorizedState() {
    const nextStatus = await api<Status>('/api/telegram/status')
    setStatus(nextStatus)
    if (nextStatus.authorized) setDialogs(await api<Dialog[]>('/api/telegram/dialogs'))
  }

  async function importSession() {
    setImporting(true)
    setError('')
    try {
      const nextStatus = await api<Status>('/api/telegram/session/import', { method: 'POST' })
      setStatus(nextStatus)
      if (nextStatus.authorized) setDialogs(await api<Dialog[]>('/api/telegram/dialogs'))
    } catch (caught) {
      setError(errorMessage(caught, 'انتقال سشن انجام نشد؛ تنظیمات مسیر یا فایل منبع را بررسی کنید.'))
    } finally {
      setImporting(false)
    }
  }

  async function sendCode(event: FormEvent) {
    event.preventDefault()
    const value = phone.trim()
    if (!value) {
      setError('شماره تلفن را وارد کنید.')
      return
    }
    setAuthBusy(true)
    setError('')
    setAuthNotice('')
    try {
      await api<AuthResponse>('/api/telegram/auth/send-code', {
        method: 'POST',
        body: JSON.stringify({ phone: value })
      })
      setAuthStep('code')
      setAuthNotice('کد تأیید به تلگرام شما ارسال شد.')
    } catch (caught) {
      setError(errorMessage(caught, 'ارسال کد تأیید انجام نشد.'))
    } finally {
      setAuthBusy(false)
    }
  }

  async function verifyCode(event: FormEvent) {
    event.preventDefault()
    if (!code.trim()) {
      setError('کد تأیید را وارد کنید.')
      return
    }
    setAuthBusy(true)
    setError('')
    try {
      const result = await api<AuthResponse>('/api/telegram/auth/verify-code', {
        method: 'POST',
        body: JSON.stringify({ code: code.trim() })
      })
      if (result.requires_2fa) {
        setAuthStep('password')
        setAuthNotice('رمز دومرحله‌ای حساب را وارد کنید.')
      } else {
        await refreshAuthorizedState()
      }
    } catch (caught) {
      setError(errorMessage(caught, 'تأیید کد انجام نشد.'))
    } finally {
      setAuthBusy(false)
    }
  }

  async function verifyPassword(event: FormEvent) {
    event.preventDefault()
    if (!password) {
      setError('رمز دومرحله‌ای را وارد کنید.')
      return
    }
    setAuthBusy(true)
    setError('')
    try {
      await api<AuthResponse>('/api/telegram/auth/verify-password', {
        method: 'POST',
        body: JSON.stringify({ password })
      })
      await refreshAuthorizedState()
    } catch (caught) {
      setError(errorMessage(caught, 'تأیید رمز دومرحله‌ای انجام نشد.'))
    } finally {
      setAuthBusy(false)
    }
  }

  function resetAuth() {
    setAuthStep('phone')
    setCode('')
    setPassword('')
    setAuthNotice('')
    setError('')
  }

  function mediaKey(message: Message) {
    return message.chat_id + ':' + message.message_id
  }

  function mediaUrl(message: Message, download = false) {
    const path = backendBase + '/api/telegram/chats/' + encodeURIComponent(String(message.chat_id)) + '/messages/' + encodeURIComponent(String(message.message_id)) + '/media'
    return download ? path + '?download=true' : path
  }

  function mediaState(message: Message): MediaState {
    return mediaStates[mediaKey(message)] || (message.media?.kind === 'photo' ? 'loading' : 'ready')
  }

  function setMessageMediaState(message: Message, value: MediaState) {
    setMediaStates(current => ({ ...current, [mediaKey(message)]: value }))
  }

  function mediaDownloadName(message: Message) {
    const preferred = message.media?.name?.trim() || mediaKindLabel(message.media?.kind || 'other') + '-' + message.message_id
    const cleaned = preferred.replace(/[\\/:*?"<>|]+/g, '_')
    return cleaned || 'media-' + message.message_id
  }

  async function downloadMedia(message: Message) {
    if (!message.media || message.media.downloadable === false) return
    setMessageMediaState(message, 'downloading')
    try {
      const response = await fetch(mediaUrl(message, true))
      if (!response.ok) {
        const body = await response.text()
        let detail = body || 'دانلود رسانه انجام نشد.'
        try {
          const parsed = JSON.parse(body) as { detail?: string }
          if (parsed.detail) detail = parsed.detail
        } catch {
          // Keep the plain response body when the backend did not return JSON.
        }
        throw new Error(detail)
      }

      const blob = await response.blob()
      const objectUrl = URL.createObjectURL(blob)
      const anchor = document.createElement('a')
      anchor.href = objectUrl
      anchor.download = mediaDownloadName(message)
      document.body.appendChild(anchor)
      anchor.click()
      anchor.remove()
      window.setTimeout(() => URL.revokeObjectURL(objectUrl), 1000)
      setMessageMediaState(message, 'done')
    } catch (caught) {
      setMessageMediaState(message, 'error')
      setError(errorMessage(caught, 'دانلود رسانه انجام نشد.'))
    }
  }

  function mediaButtonLabel(state: MediaState) {
    if (state === 'downloading') return 'در حال دانلود…'
    if (state === 'done') return 'دانلود شد'
    if (state === 'error') return 'تلاش دوباره'
    return 'دانلود'
  }

  function renderMedia(message: Message) {
    if (!message.media || message.deleted) return null
    const state = mediaState(message)
    const label = mediaKindLabel(message.media.kind)

    if (message.media.kind === 'photo') {
      return (
        <div className="media-photo-card">
          <img
            className="message-photo"
            src={mediaUrl(message)}
            alt={message.media.name || 'تصویر پیام'}
            loading="lazy"
            onLoad={() => setMessageMediaState(message, 'ready')}
            onError={() => setMessageMediaState(message, 'error')}
          />
          <div className="media-toolbar">
            <div className="media-copy">
              <strong>{message.media.name || label}</strong>
              <small>{formatBytes(message.media.size)}</small>
            </div>
            <button className="download-button" type="button" onClick={() => downloadMedia(message)} disabled={state === 'downloading'}>
              {mediaButtonLabel(state)}
            </button>
          </div>
          {state === 'error' && <small className="media-status error">نمایش یا دریافت رسانه انجام نشد.</small>}
        </div>
      )
    }

    return (
      <div className="media-card">
        <span className="media-icon">{message.media.kind === 'audio' ? '♫' : message.media.kind === 'video' ? '▣' : '□'}</span>
        <div className="media-copy">
          <strong>{message.media.name || label}</strong>
          <small>{label} · {formatBytes(message.media.size)}</small>
          {message.media.kind === 'audio' || message.media.kind === 'video'
            ? <small className="media-status">پخش در این فاز فعال نیست.</small>
            : null}
        </div>
        <button className="download-button" type="button" onClick={() => downloadMedia(message)} disabled={state === 'downloading'}>
          {mediaButtonLabel(state)}
        </button>
      </div>
    )
  }

  function toggleMessageSearch() {
    setMessageSearchOpen(current => {
      if (current) {
        setMessageQuery('')
        setSearchResults([])
        setSearchPerformed(false)
      }
      return !current
    })
  }

  async function searchMessages(event: FormEvent) {
    event.preventDefault()
    if (!selected || searchBusy) return
    const value = messageQuery.trim()
    if (value.length < 2) {
      setError('برای جست‌وجو حداقل دو حرف وارد کنید.')
      return
    }

    setSearchBusy(true)
    setSearchPerformed(false)
    try {
      const results = await api<Message[]>(
        '/api/telegram/chats/' + selected.chat_id + '/search?q=' + encodeURIComponent(value) + '&limit=50'
      )
      setSearchResults(results)
      setSearchPerformed(true)
    } catch (caught) {
      setError(errorMessage(caught, 'جست‌وجوی پیام انجام نشد.'))
    } finally {
      setSearchBusy(false)
    }
  }

  function openSearchResult(message: Message) {
    setMessages(current => {
      if (current.some(item => item.message_id === message.message_id)) return current
      return [...current, message].sort((a, b) => a.message_id - b.message_id)
    })
    window.setTimeout(() => jumpToMessage(message.message_id), 0)
  }

  function messageSnippet(message: Message | null) {
    if (!message) return 'پیام قبلی'
    const text = message.text.trim()
    if (text) return text.length > 110 ? text.slice(0, 110) + '…' : text
    if (message.media) return mediaKindLabel(message.media.kind)
    return 'پیام'
  }

  function beginReply(message: Message) {
    setEditing(null)
    setReplyingTo(message)
  }

  function beginForward(message: Message) {
    setForwardQuery('')
    setForwarding(message)
  }

  async function forwardMessageTo(dialog: Dialog) {
    if (!forwarding || forwardTargetBusy !== null) return
    setForwardTargetBusy(dialog.chat_id)
    try {
      const message = await api<Message>(
        '/api/telegram/chats/' + forwarding.chat_id + '/messages/' + forwarding.message_id + '/forward',
        {
          method: 'POST',
          body: JSON.stringify({ target_chat_id: dialog.chat_id })
        }
      )
      if (selected?.chat_id === dialog.chat_id) {
        setMessages(current => [
          ...current.filter(item => item.message_id !== message.message_id),
          message
        ].sort((a, b) => a.message_id - b.message_id))
      }
      setForwarding(null)
      setForwardQuery('')
    } catch (caught) {
      setError(errorMessage(caught, 'فوروارد پیام انجام نشد.'))
    } finally {
      setForwardTargetBusy(null)
    }
  }

  function beginEdit(message: Message) {
    setReplyingTo(null)
    setEditing(message)
    setDraft(message.text)
  }

  function cancelComposerContext() {
    const wasEditing = editing !== null
    setReplyingTo(null)
    setEditing(null)
    if (wasEditing) setDraft('')
  }

  function jumpToMessage(messageId: number) {
    if (!selected) return
    const element = document.getElementById('message-' + selected.chat_id + '-' + messageId)
    if (!element) return
    element.scrollIntoView({ behavior: 'smooth', block: 'center' })
    element.classList.add('message-focus')
    window.setTimeout(() => element.classList.remove('message-focus'), 1400)
  }

  function renderReplyReference(message: Message) {
    if (!message.reply_to_message_id) return null
    const source = messages.find(item => item.message_id === message.reply_to_message_id) || null
    const sender = source ? (source.outgoing ? 'شما' : source.sender_name || 'پیام') : 'پیام قبلی'
    return (
      <button
        className="reply-reference"
        type="button"
        onClick={() => jumpToMessage(message.reply_to_message_id as number)}
        disabled={!source}
      >
        <strong>{sender}</strong>
        <span>{messageSnippet(source)}</span>
      </button>
    )
  }

  async function deleteMessage(message: Message) {
    if (!selected || !message.outgoing || message.deleted) return
    if (!window.confirm('این پیام برای همه حذف شود؟')) return

    const actionKey = 'delete:' + mediaKey(message)
    setMessageActionBusy(actionKey)
    try {
      await api<{ chat_id: number; message_id: number; deleted: boolean }>(
        '/api/telegram/chats/' + selected.chat_id + '/messages/' + message.message_id + '/delete',
        { method: 'POST' }
      )
      setMessages(current => current.map(item => item.message_id === message.message_id
        ? { ...item, deleted: true, text: '' }
        : item
      ))
      if (editing?.message_id === message.message_id) cancelComposerContext()
    } catch (caught) {
      setError(errorMessage(caught, 'حذف پیام انجام نشد.'))
    } finally {
      setMessageActionBusy(null)
    }
  }

  async function uploadFile(file: File) {
    if (!selected || uploadBusy || editing) return
    if (file.size > 2 * 1024 * 1024 * 1024) {
      setError('حجم فایل نمی‌تواند بیشتر از ۲ گیگابایت باشد.')
      return
    }
    if (file.size === 0) {
      setError('فایل خالی قابل ارسال نیست.')
      return
    }

    const chatId = selected.chat_id
    const form = new FormData()
    form.append('file', file, file.name)
    if (draft.trim()) form.append('caption', draft.trim())
    if (replyingTo) form.append('reply_to_message_id', String(replyingTo.message_id))

    setUploadBusy(true)
    setUploadName(file.name)
    setError('')
    try {
      const response = await fetch(backendBase + '/api/telegram/chats/' + chatId + '/files', {
        method: 'POST',
        body: form
      })
      if (!response.ok) {
        const body = await response.text()
        let detail = body || 'ارسال فایل انجام نشد.'
        try {
          const parsed = JSON.parse(body) as { detail?: string }
          if (parsed.detail) detail = parsed.detail
        } catch {
          // Keep the plain response body when the backend did not return JSON.
        }
        throw new Error(detail)
      }

      const message = await response.json() as Message
      if (selectedChatIdRef.current === chatId) {
        setMessages(current => [
          ...current.filter(item => item.message_id !== message.message_id),
          message
        ].sort((a, b) => a.message_id - b.message_id))
        setDraft('')
        setReplyingTo(null)
      }
    } catch (caught) {
      setError(errorMessage(caught, 'ارسال فایل انجام نشد.'))
    } finally {
      setUploadBusy(false)
      setUploadName('')
      if (fileInputRef.current) fileInputRef.current.value = ''
    }
  }

  async function sendMessage(event: FormEvent) {
    event.preventDefault()
    const text = draft.trim()
    if (!selected || !text || composerBusy) return

    setComposerBusy(true)
    try {
      if (editing) {
        const message = await api<Message>(
          '/api/telegram/chats/' + selected.chat_id + '/messages/' + editing.message_id + '/edit',
          {
            method: 'POST',
            body: JSON.stringify({ text })
          }
        )
        setMessages(current => current.map(item => item.message_id === message.message_id ? message : item))
        setEditing(null)
      } else {
        const message = await api<Message>('/api/telegram/chats/' + selected.chat_id + '/messages', {
          method: 'POST',
          body: JSON.stringify({
            text,
            reply_to_message_id: replyingTo?.message_id || null
          })
        })
        setMessages(current => [...current.filter(item => item.message_id !== message.message_id), message])
        setReplyingTo(null)
      }
      setDraft('')
    } catch (caught) {
      setError(errorMessage(caught, editing ? 'ویرایش پیام انجام نشد.' : 'ارسال پیام انجام نشد.'))
    } finally {
      setComposerBusy(false)
    }
  }

  if (!status) {
    return <div className="loading-screen">در حال راه‌اندازی تلگرام…</div>
  }

  if (!status.authorized) {
    return (
      <div className="auth-screen">
        <div className="auth-card">
          <div className="brand-mark">✈</div>
          <h1>Telegram Desktop</h1>
          <p>ورود به کلاینت مستقل</p>
          <span className="status-pill">{statusLabel(status.state)}</span>
          {status.last_error && <small className="auth-error">{status.last_error}</small>}

          {status.state === 'IMPORT_READY' && status.source_session_available && (
            <>
              <p className="muted">فایل منبع فقط خوانده می‌شود و یک فایل سشن مستقل برای این برنامه ساخته می‌شود.</p>
              <button className="primary-action" onClick={importSession} disabled={importing}>
                {importing ? 'در حال انتقال…' : 'انتقال کنترل‌شده از داشبورد'}
              </button>
              <div className="auth-divider"><span>یا ورود مستقل</span></div>
            </>
          )}

          {status.state === 'UNCONFIGURED' ? (
            <p className="muted">ابتدا API ID و API Hash را در فایل تنظیمات محلی وارد کنید.</p>
          ) : (
            <form className="auth-form" onSubmit={authStep === 'phone' ? sendCode : authStep === 'code' ? verifyCode : verifyPassword}>
              {authStep === 'phone' && (
                <>
                  <label className="auth-field">
                    <span>شماره تلفن</span>
                    <input value={phone} onChange={event => setPhone(event.target.value)} placeholder="+98..." autoComplete="tel" dir="ltr" />
                  </label>
                  <button className="primary-action auth-submit" type="submit" disabled={authBusy}>
                    {authBusy ? 'در حال ارسال…' : 'دریافت کد تأیید'}
                  </button>
                </>
              )}

              {authStep === 'code' && (
                <>
                  <p className="auth-notice">{authNotice || 'کد تأیید را وارد کنید.'}</p>
                  <label className="auth-field">
                    <span>کد تأیید</span>
                    <input value={code} onChange={event => setCode(event.target.value)} placeholder="12345" inputMode="numeric" autoComplete="one-time-code" dir="ltr" />
                  </label>
                  <button className="primary-action auth-submit" type="submit" disabled={authBusy}>
                    {authBusy ? 'در حال بررسی…' : 'تأیید و ورود'}
                  </button>
                  <button className="text-button" type="button" onClick={resetAuth}>تغییر شماره</button>
                </>
              )}

              {authStep === 'password' && (
                <>
                  <p className="auth-notice">{authNotice || 'رمز دومرحله‌ای را وارد کنید.'}</p>
                  <label className="auth-field">
                    <span>رمز دومرحله‌ای</span>
                    <input value={password} onChange={event => setPassword(event.target.value)} type="password" autoComplete="current-password" dir="ltr" />
                  </label>
                  <button className="primary-action auth-submit" type="submit" disabled={authBusy}>
                    {authBusy ? 'در حال بررسی…' : 'تأیید رمز و ورود'}
                  </button>
                  <button className="text-button" type="button" onClick={resetAuth}>شروع دوباره</button>
                </>
              )}
            </form>
          )}
        </div>
        {error && <button className="error-toast" onClick={() => setError('')}>{error}</button>}
      </div>
    )
  }

  return (
    <main className="telegram-shell">
      <aside className="chat-sidebar">
        <header className="sidebar-header">
          <div className="brand-title"><span className="brand-mark small">✈</span> Telegram</div>
          <button className="icon-button" aria-label="به‌روزرسانی گفتگوها" onClick={refreshDialogs}>↻</button>
          <button className="icon-button" aria-label="منو">☰</button>
        </header>
        <label className="search-box">
          <span>⌕</span>
          <input value={query} onChange={event => setQuery(event.target.value)} placeholder="جست‌وجو" />
        </label>
        <div className="folder-tabs">
          <button className={activeFolder === 'all' ? 'active' : ''} onClick={() => setActiveFolder('all')}>همه</button>
          <button className={activeFolder === 'private' ? 'active' : ''} onClick={() => setActiveFolder('private')}>شخصی</button>
          <button className={activeFolder === 'groups' ? 'active' : ''} onClick={() => setActiveFolder('groups')}>گروه‌ها</button>
          <button className={activeFolder === 'channels' ? 'active' : ''} onClick={() => setActiveFolder('channels')}>کانال‌ها</button>
          <button className={activeFolder === 'archived' ? 'active' : ''} onClick={() => setActiveFolder('archived')}>آرشیو</button>
        </div>
        <div className="dialog-list">
          {visibleDialogs.map(dialog => (
            <button className={'dialog-row ' + (selected?.chat_id === dialog.chat_id ? 'selected' : '')} key={dialog.chat_id} onClick={() => setSelected(dialog)}>
              <ChatAvatar chatId={dialog.chat_id} title={dialog.title} />
              <span className="dialog-copy"><strong>{dialog.title}</strong><small>{dialog.dialog_type}</small></span>
              {dialog.unread_count > 0 && <span className="unread">{dialog.unread_count}</span>}
            </button>
          ))}
          {!visibleDialogs.length && <div className="empty-list">گفت‌وگویی پیدا نشد</div>}
        </div>
      </aside>

      <section className="chat-panel">
        {selected ? (
          <>
            <header className="chat-header">
              <ChatAvatar chatId={selected.chat_id} title={selected.title} className="large" />
              <div>
                <strong>{selected.title}</strong>
                <small>{presenceLabel(chatInfo?.status) || dialogTypeLabel(chatInfo?.dialog_type || selected.dialog_type)}</small>
              </div>
              <div className="header-actions">
                <button className={'icon-button ' + (messageSearchOpen ? 'active' : '')} aria-label="جست‌وجوی پیام" onClick={toggleMessageSearch}>⌕</button>
                <button className="icon-button">⋮</button>
              </div>
            </header>
            {messageSearchOpen && (
              <section className="message-search-panel">
                <form className="message-search-form" onSubmit={searchMessages}>
                  <input
                    value={messageQuery}
                    onChange={event => {
                      setMessageQuery(event.target.value)
                      setSearchPerformed(false)
                    }}
                    placeholder="جست‌وجو در این گفتگو"
                    autoFocus
                  />
                  <button type="submit" disabled={searchBusy}>{searchBusy ? '…' : 'جست‌وجو'}</button>
                  <button type="button" aria-label="بستن جست‌وجو" onClick={toggleMessageSearch}>×</button>
                </form>
                {searchResults.length > 0 && (
                  <div className="message-search-results">
                    {searchResults.map(result => (
                      <button type="button" key={result.message_id} onClick={() => openSearchResult(result)}>
                        <strong>{result.outgoing ? 'شما' : result.sender_name || selected.title}</strong>
                        <span>{messageSnippet(result)}</span>
                        <small>{formatTime(result.date)}</small>
                      </button>
                    ))}
                  </div>
                )}
                {!searchBusy && searchPerformed && searchResults.length === 0 && (
                  <div className="search-empty">نتیجه‌ای پیدا نشد.</div>
                )}
              </section>
            )}
            <div className="message-list">
              {hasOlder && (
                <button className="older-button" onClick={loadOlder} disabled={loadingOlder}>
                  {loadingOlder ? 'در حال دریافت…' : 'پیام‌های قدیمی‌تر'}
                </button>
              )}
              {messages.map(message => (
                <article
                  id={'message-' + message.chat_id + '-' + message.message_id}
                  className={'message ' + (message.outgoing ? 'outgoing' : '') + (message.deleted ? ' deleted' : '')}
                  key={message.message_id}
                >
                  {!message.outgoing && message.sender_name && <strong className="sender-name">{message.sender_name}</strong>}
                  {renderReplyReference(message)}
                  {message.media && renderMedia(message)}
                  {message.deleted ? <span>پیام حذف شده است</span> : message.text && <span>{message.text}</span>}
                  {!message.deleted && (
                    <div className="message-actions">
                      <button type="button" onClick={() => beginReply(message)}>↩ پاسخ</button>
                      <button type="button" onClick={() => beginForward(message)}>↗ فوروارد</button>
                      {message.outgoing && message.text && <button type="button" onClick={() => beginEdit(message)}>✎ ویرایش</button>}
                      {message.outgoing && (
                        <button
                          type="button"
                          className="danger"
                          onClick={() => deleteMessage(message)}
                          disabled={messageActionBusy === 'delete:' + mediaKey(message)}
                        >
                          حذف
                        </button>
                      )}
                    </div>
                  )}
                  <small>{formatTime(message.date)}{message.edited ? ' · ویرایش‌شده' : ''}</small>
                </article>
              ))}
            </div>
            <div className="composer-shell">
              <input
                ref={fileInputRef}
                className="hidden-file-input"
                type="file"
                onChange={event => {
                  const file = event.target.files?.[0]
                  if (file) void uploadFile(file)
                }}
              />
              {uploadBusy && (
                <div className="upload-status">
                  <span className="upload-spinner">↥</span>
                  <div>
                    <strong>در حال ارسال فایل</strong>
                    <small>{uploadName}</small>
                  </div>
                </div>
              )}
              {(replyingTo || editing) && (
                <div className="composer-context">
                  <span className="composer-context-bar" />
                  <div className="composer-context-copy">
                    <strong>{editing ? 'ویرایش پیام' : 'پاسخ به ' + (replyingTo?.outgoing ? 'خودتان' : replyingTo?.sender_name || 'پیام')}</strong>
                    <small>{messageSnippet(editing || replyingTo)}</small>
                  </div>
                  <button className="icon-button" type="button" aria-label="بستن" onClick={cancelComposerContext}>×</button>
                </div>
              )}
              <form className="composer" onSubmit={sendMessage}>
                <button
                  type="button"
                  className="icon-button"
                  aria-label="ارسال عکس یا فایل"
                  onClick={() => fileInputRef.current?.click()}
                  disabled={uploadBusy || editing !== null}
                >
                  ＋
                </button>
                <input
                  value={draft}
                  onChange={event => setDraft(event.target.value)}
                  placeholder={editing ? 'ویرایش پیام...' : replyingTo ? 'کپشن یا پاسخ...' : 'پیام یا کپشن فایل...'}
                  disabled={uploadBusy}
                />
                <button className="send-button" type="submit" disabled={composerBusy || uploadBusy || !draft.trim()}>
                  {editing ? '✓' : '➤'}
                </button>
              </form>
            </div>
          </>
        ) : (
          <div className="empty-chat"><div className="brand-mark">✈</div><h2>یک گفتگو را انتخاب کنید</h2><p>پیام‌های تلگرام در اینجا نمایش داده می‌شوند.</p></div>
        )}
      </section>

      <aside className="info-panel">
        {selected ? (
          <>
            <ChatAvatar chatId={selected.chat_id} title={selected.title} className="huge" />
            <h2>{chatInfo?.title || selected.title}</h2>
            {chatInfo?.username && <p className="profile-username">@{chatInfo.username}</p>}
            <div className="info-badges">
              {chatInfo?.verified && <span>تأییدشده</span>}
              {chatInfo?.is_bot && <span>ربات</span>}
              {chatInfo?.scam && <span className="warning">کلاهبرداری</span>}
              {chatInfo?.fake && <span className="warning">جعلی</span>}
            </div>
            <hr />
            <div className="info-details">
              <div><span>نوع</span><strong>{dialogTypeLabel(chatInfo?.dialog_type || selected.dialog_type)}</strong></div>
              {chatInfo?.status && <div><span>وضعیت</span><strong>{presenceLabel(chatInfo.status)}</strong></div>}
              {chatInfo?.participants_count != null && (
                <div><span>اعضا</span><strong>{new Intl.NumberFormat('fa-IR').format(chatInfo.participants_count)}</strong></div>
              )}
              <div><span>شناسه</span><strong dir="ltr">{selected.chat_id}</strong></div>
            </div>
          </>
        ) : <div className="muted">اطلاعات گفتگو</div>}
      </aside>

      {forwarding && (
        <div className="forward-backdrop" onMouseDown={() => setForwarding(null)}>
          <section className="forward-modal" role="dialog" aria-modal="true" aria-label="انتخاب مقصد فوروارد" onMouseDown={event => event.stopPropagation()}>
            <header>
              <div>
                <strong>فوروارد پیام</strong>
                <small>{messageSnippet(forwarding)}</small>
              </div>
              <button className="icon-button" type="button" aria-label="بستن" onClick={() => setForwarding(null)}>×</button>
            </header>
            <input
              className="forward-search"
              value={forwardQuery}
              onChange={event => setForwardQuery(event.target.value)}
              placeholder="جست‌وجوی مقصد"
              autoFocus
            />
            <div className="forward-dialogs">
              {forwardDialogs.map(dialog => (
                <button
                  className="forward-dialog-row"
                  type="button"
                  key={dialog.chat_id}
                  onClick={() => forwardMessageTo(dialog)}
                  disabled={forwardTargetBusy !== null}
                >
                  <ChatAvatar chatId={dialog.chat_id} title={dialog.title} />
                  <span>
                    <strong>{dialog.title}</strong>
                    <small>{dialog.dialog_type}{dialog.username ? ' · @' + dialog.username : ''}</small>
                  </span>
                  {forwardTargetBusy === dialog.chat_id && <span className="forwarding-state">در حال ارسال…</span>}
                </button>
              ))}
              {!forwardDialogs.length && <div className="search-empty">مقصدی پیدا نشد.</div>}
            </div>
          </section>
        </div>
      )}

      {error && <button className="error-toast" onClick={() => setError('')}>{error}</button>}
    </main>
  )
}

export default App
