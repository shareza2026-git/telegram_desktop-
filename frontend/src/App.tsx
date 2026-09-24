import { Fragment, useEffect, useMemo, useRef, useState, type FormEvent, type MouseEvent as ReactMouseEvent } from 'react'

import { DRAFT_STORAGE_KEY, parseDraftMap, updateDraftMap } from './drafts'

type Dialog = {
  chat_id: number
  title: string
  dialog_type: string
  username?: string | null
  unread_count: number
  pinned: boolean
  archived: boolean
  muted: boolean
}

type DialogPatch = {
  chat_id: number
  pinned?: boolean
  archived?: boolean
  muted?: boolean
}

type MessageContextMenu = {
  message: Message
  x: number
  y: number
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

type ReactionSummary = {
  emoji: string
  count: number
  chosen: boolean
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
  reactions: ReactionSummary[]
  read: boolean
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

type ChatAction = {
  chat_id: number
  user_id?: number | null
  user_name?: string | null
  action: 'typing' | 'uploading' | 'recording' | 'cancel'
  active: boolean
  expires_at?: number
}

type ReadReceipt = {
  chat_id: number
  max_id: number
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
const QUICK_REACTIONS = ['👍', '❤️', '😂', '😮', '😢', '🔥']
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

function messageDayKey(value: string) {
  const date = new Date(value)
  return [date.getFullYear(), date.getMonth(), date.getDate()].join('-')
}

function formatMessageDate(value: string) {
  return new Intl.DateTimeFormat('fa-IR', {
    year: 'numeric',
    month: 'long',
    day: 'numeric'
  }).format(new Date(value))
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

function chatActionLabel(value: ChatAction['action']) {
  const labels: Record<ChatAction['action'], string> = {
    typing: 'در حال نوشتن…',
    uploading: 'در حال ارسال فایل…',
    recording: 'در حال ضبط…',
    cancel: ''
  }
  return labels[value]
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
  const [pinnedMessage, setPinnedMessage] = useState<Message | null>(null)
  const [unreadBoundaryId, setUnreadBoundaryId] = useState<number | null>(null)
  const [showJumpToBottom, setShowJumpToBottom] = useState(false)
  const [newBelowCount, setNewBelowCount] = useState(0)
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
  const composerFormRef = useRef<HTMLFormElement>(null)
  const messageListRef = useRef<HTMLDivElement>(null)
  const stickToBottomRef = useRef(true)
  const selectedChatIdRef = useRef<number | null>(null)
  const [messageActionBusy, setMessageActionBusy] = useState<string | null>(null)
  const [reactionPickerFor, setReactionPickerFor] = useState<number | null>(null)
  const [reactionBusy, setReactionBusy] = useState<string | null>(null)
  const [selectedChatAction, setSelectedChatAction] = useState<ChatAction | null>(null)
  const typingTimerRef = useRef<number | null>(null)
  const typingSentRef = useRef<{ chatId: number; active: boolean; at: number } | null>(null)
  const [messageSearchOpen, setMessageSearchOpen] = useState(false)
  const [messageQuery, setMessageQuery] = useState('')
  const [searchResults, setSearchResults] = useState<Message[]>([])
  const [searchBusy, setSearchBusy] = useState(false)
  const [searchPerformed, setSearchPerformed] = useState(false)
  const [forwarding, setForwarding] = useState<Message[] | null>(null)
  const [forwardQuery, setForwardQuery] = useState('')
  const [forwardTargetBusy, setForwardTargetBusy] = useState<number | null>(null)
  const [notificationsEnabled, setNotificationsEnabled] = useState(() => (
    typeof Notification !== 'undefined'
    && Notification.permission === 'granted'
    && window.localStorage.getItem('telegram-notifications') === '1'
  ))
  const [chatMenuOpen, setChatMenuOpen] = useState(false)
  const [dialogActionBusy, setDialogActionBusy] = useState<string | null>(null)
  const [messageContextMenu, setMessageContextMenu] = useState<MessageContextMenu | null>(null)
  const [selectedMessageIds, setSelectedMessageIds] = useState<Set<number>>(() => new Set())
  const [bulkBusy, setBulkBusy] = useState<'delete' | 'forward' | null>(null)
  const dialogsRef = useRef<Dialog[]>([])
  const notificationsEnabledRef = useRef(notificationsEnabled)
  const draftsRef = useRef(parseDraftMap(window.localStorage.getItem(DRAFT_STORAGE_KEY)))
  const draftSwitchRef = useRef<number | null>(null)
  const draftBeforeEditRef = useRef('')

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

  const totalUnread = useMemo(
    () => dialogs.reduce((total, dialog) => total + dialog.unread_count, 0),
    [dialogs]
  )

  const selectedMessages = useMemo(
    () => messages.filter(message => selectedMessageIds.has(message.message_id)),
    [messages, selectedMessageIds]
  )

  useEffect(() => {
    selectedChatIdRef.current = selected?.chat_id || null
    setChatMenuOpen(false)
  }, [selected?.chat_id])

  useEffect(() => {
    dialogsRef.current = dialogs
  }, [dialogs])

  useEffect(() => {
    notificationsEnabledRef.current = notificationsEnabled
  }, [notificationsEnabled])

  useEffect(() => {
    document.title = totalUnread > 0
      ? '(' + new Intl.NumberFormat('fa-IR').format(totalUnread) + ') Telegram'
      : 'Telegram Desktop'
    const badgeNavigator = navigator as Navigator & {
      setAppBadge?: (count?: number) => Promise<void>
      clearAppBadge?: () => Promise<void>
    }
    const operation = totalUnread > 0
      ? badgeNavigator.setAppBadge?.(totalUnread)
      : badgeNavigator.clearAppBadge?.()
    operation?.catch(() => undefined)
  }, [totalUnread])

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
      const packet = JSON.parse(event.data) as {
        type: string
        data: Status | Message | ChatAction | ReadReceipt | DialogPatch
      }
      if (packet.type === 'READY') setStatus(packet.data as Status)
      if (packet.type === 'MESSAGE_NEW' || packet.type === 'MESSAGE_EDITED') {
        const message = packet.data as Message
        if (packet.type === 'MESSAGE_NEW' && !message.outgoing) {
          const activeAndVisible = (
            selectedChatIdRef.current === message.chat_id
            && document.visibilityState === 'visible'
          )
          if (!activeAndVisible) {
            setDialogs(current => current.map(dialog => (
              dialog.chat_id === message.chat_id
                ? { ...dialog, unread_count: dialog.unread_count + 1 }
                : dialog
            )))
            showDesktopNotification(message)
          }
        }
        if (selected?.chat_id === message.chat_id) {
          const shouldFollow = message.outgoing || isNearBottom()
          setMessages(current => {
            const exists = current.some(item => item.message_id === message.message_id)
            if (packet.type === 'MESSAGE_NEW' && !message.outgoing && !shouldFollow && !exists) {
              setNewBelowCount(count => count + 1)
            }
            const without = current.filter(item => item.message_id !== message.message_id)
            return [...without, message].sort((a, b) => a.message_id - b.message_id)
          })
          if (shouldFollow) {
            window.requestAnimationFrame(() => scrollToBottom(message.outgoing ? 'smooth' : 'auto'))
          }
        }
      }
      if (packet.type === 'DIALOG_UPDATED') {
        applyDialogPatch(packet.data as DialogPatch)
      }
      if (packet.type === 'CHAT_ACTION') {
        const action = packet.data as ChatAction
        if (selected?.chat_id === action.chat_id) {
          if (!action.active || action.action === 'cancel') {
            setSelectedChatAction(null)
          } else {
            const expiresAt = Date.now() + 6000
            setSelectedChatAction({ ...action, expires_at: expiresAt })
            window.setTimeout(() => {
              setSelectedChatAction(current => (
                current && current.expires_at === expiresAt ? null : current
              ))
            }, 6100)
          }
        }
      }
      if (packet.type === 'MESSAGES_READ') {
        const receipt = packet.data as ReadReceipt
        if (selected?.chat_id === receipt.chat_id) {
          setMessages(current => current.map(item => (
            item.outgoing && item.message_id <= receipt.max_id
              ? { ...item, read: true }
              : item
          )))
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
      setPinnedMessage(null)
      setUnreadBoundaryId(null)
      setShowJumpToBottom(false)
      setNewBelowCount(0)
      stickToBottomRef.current = true
      setReplyingTo(null)
      setEditing(null)
      setDraft('')
      draftSwitchRef.current = null
      setMessageSearchOpen(false)
      setMessageQuery('')
      setSearchResults([])
      setSearchPerformed(false)
      setForwarding(null)
      setForwardQuery('')
      setBulkBusy(null)
      setReactionPickerFor(null)
      setMessageContextMenu(null)
      setSelectedMessageIds(new Set())
      setSelectedChatAction(null)
      return
    }
    const unreadCount = selected.unread_count
    setMessages([])
    setHasOlder(false)
    setChatInfo(null)
    setPinnedMessage(null)
    setUnreadBoundaryId(null)
    setShowJumpToBottom(false)
    setNewBelowCount(0)
    stickToBottomRef.current = true
    setReplyingTo(null)
    setEditing(null)
    setDraft(draftsRef.current[String(selected.chat_id)] || '')
    setMessageSearchOpen(false)
    setMessageQuery('')
    setSearchResults([])
    setSearchPerformed(false)
    setForwarding(null)
    setForwardQuery('')
    setBulkBusy(null)
    setReactionPickerFor(null)
    setMessageContextMenu(null)
    setSelectedMessageIds(new Set())
    setSelectedChatAction(null)
    api<ChatInfo>('/api/telegram/chats/' + selected.chat_id)
      .then(setChatInfo)
      .catch(() => setChatInfo(null))

    api<Message | null>('/api/telegram/chats/' + selected.chat_id + '/pinned')
      .then(setPinnedMessage)
      .catch(() => setPinnedMessage(null))

    api<Message[]>('/api/telegram/chats/' + selected.chat_id + '/messages?limit=' + HISTORY_PAGE_SIZE)
      .then(items => {
        setMessages(items)
        setHasOlder(items.length === HISTORY_PAGE_SIZE)
        const incoming = items.filter(item => !item.outgoing && !item.deleted)
        const unreadIndex = Math.max(0, incoming.length - unreadCount)
        setUnreadBoundaryId(unreadCount > 0 && incoming.length > 0 ? incoming[unreadIndex].message_id : null)
        window.requestAnimationFrame(() => scrollToBottom('auto'))
      })
      .catch(error => setError(errorMessage(error, 'تاریخچه این گفتگو دریافت نشد.')))

    api<{ chat_id: number; read: boolean }>('/api/telegram/chats/' + selected.chat_id + '/read', { method: 'POST' })
      .then(() => {
        setDialogs(current => current.map(item => item.chat_id === selected.chat_id ? { ...item, unread_count: 0 } : item))
        setSelected(current => current && current.chat_id === selected.chat_id ? { ...current, unread_count: 0 } : current)
      })
      .catch(() => undefined)
  }, [selected?.chat_id])

  useEffect(() => {
    if (!selected || editing) return
    if (draftSwitchRef.current === selected.chat_id) {
      draftSwitchRef.current = null
      return
    }
    draftsRef.current = updateDraftMap(draftsRef.current, selected.chat_id, draft)
    window.localStorage.setItem(DRAFT_STORAGE_KEY, JSON.stringify(draftsRef.current))
  }, [draft, selected?.chat_id, editing])

  useEffect(() => {
    function handleKeyboard(event: KeyboardEvent) {
      const target = event.target as HTMLElement | null
      const isTyping = target?.tagName === 'INPUT' || target?.tagName === 'TEXTAREA'

      if ((event.ctrlKey || event.metaKey) && event.key.toLowerCase() === 'f' && selected) {
        event.preventDefault()
        setMessageSearchOpen(true)
        return
      }

      if ((event.ctrlKey || event.metaKey) && event.key === 'Enter' && selected) {
        event.preventDefault()
        composerFormRef.current?.requestSubmit()
        return
      }

      if (event.key === 'Delete' && selectedMessageIds.size > 0 && !isTyping) {
        event.preventDefault()
        void deleteSelectedMessages()
        return
      }

      if (event.key !== 'Escape') return
      if (messageContextMenu) {
        setMessageContextMenu(null)
      } else if (forwarding) {
        closeForwarding()
      } else if (chatMenuOpen) {
        setChatMenuOpen(false)
      } else if (reactionPickerFor !== null) {
        setReactionPickerFor(null)
      } else if (selectedMessageIds.size > 0) {
        setSelectedMessageIds(new Set())
      } else if (messageSearchOpen) {
        setMessageSearchOpen(false)
      } else if (replyingTo || editing) {
        cancelComposerContext()
      }
    }

    window.addEventListener('keydown', handleKeyboard)
    return () => window.removeEventListener('keydown', handleKeyboard)
  }, [
    selected?.chat_id,
    selectedMessageIds,
    messageContextMenu,
    forwarding,
    chatMenuOpen,
    reactionPickerFor,
    messageSearchOpen,
    replyingTo,
    editing,
    draft,
    bulkBusy
  ])

  const newestMessageId = messages.length ? messages[messages.length - 1].message_id : null

  useEffect(() => {
    if (newestMessageId === null || !stickToBottomRef.current) return
    window.requestAnimationFrame(() => scrollToBottom('smooth'))
  }, [newestMessageId])

  useEffect(() => {
    if (typingTimerRef.current !== null) {
      window.clearTimeout(typingTimerRef.current)
      typingTimerRef.current = null
    }

    const chatId = selected?.chat_id
    const previous = typingSentRef.current
    const canType = Boolean(chatId && !editing && !uploadBusy)
    const hasText = canType && Boolean(draft.trim())

    if (previous?.active && (!hasText || previous.chatId !== chatId)) {
      void sendTypingStatus(previous.chatId, false)
      typingSentRef.current = null
    }

    if (!chatId || !hasText) return

    const now = Date.now()
    const current = typingSentRef.current
    if (!current || current.chatId !== chatId || now - current.at >= 3000) {
      void sendTypingStatus(chatId, true)
      typingSentRef.current = { chatId, active: true, at: now }
    }

    typingTimerRef.current = window.setTimeout(() => {
      const latest = typingSentRef.current
      if (latest?.active && latest.chatId === chatId) {
        void sendTypingStatus(chatId, false)
        typingSentRef.current = null
      }
      typingTimerRef.current = null
    }, 1800)

    return () => {
      if (typingTimerRef.current !== null) {
        window.clearTimeout(typingTimerRef.current)
        typingTimerRef.current = null
      }
    }
  }, [draft, selected?.chat_id, editing, uploadBusy])

  async function sendTypingStatus(chatId: number, active: boolean) {
    try {
      await api<{ chat_id: number; typing: boolean }>(
        '/api/telegram/chats/' + chatId + '/typing',
        {
          method: 'POST',
          body: JSON.stringify({ active })
        }
      )
    } catch {
      // Typing is an ephemeral hint and must never block composing or sending.
    }
  }

  function isNearBottom() {
    const viewport = messageListRef.current
    if (!viewport) return true
    return viewport.scrollHeight - viewport.scrollTop - viewport.clientHeight < 140
  }

  function scrollToBottom(behavior: ScrollBehavior = 'smooth') {
    const viewport = messageListRef.current
    if (!viewport) return
    viewport.scrollTo({ top: viewport.scrollHeight, behavior })
    stickToBottomRef.current = true
    setShowJumpToBottom(false)
    setNewBelowCount(0)
  }

  function handleMessageScroll() {
    setMessageContextMenu(null)
    const nearBottom = isNearBottom()
    stickToBottomRef.current = nearBottom
    setShowJumpToBottom(!nearBottom)
    if (nearBottom) setNewBelowCount(0)
  }

  function applyDialogPatch(patch: DialogPatch) {
    setDialogs(current => current.map(dialog => (
      dialog.chat_id === patch.chat_id ? { ...dialog, ...patch } : dialog
    )).sort((left, right) => Number(right.pinned) - Number(left.pinned)))
    setSelected(current => (
      current?.chat_id === patch.chat_id ? { ...current, ...patch } : current
    ))
  }

  function showDesktopNotification(message: Message) {
    if (
      !notificationsEnabledRef.current
      || typeof Notification === 'undefined'
      || Notification.permission !== 'granted'
    ) return
    const dialog = dialogsRef.current.find(item => item.chat_id === message.chat_id)
    if (dialog?.muted) return
    try {
      const notification = new Notification(dialog?.title || message.sender_name || 'Telegram', {
        body: messageSnippet(message),
        tag: 'telegram-chat-' + message.chat_id
      })
      notification.onclick = () => {
        window.focus()
        if (dialog) {
          const opened = { ...dialog, unread_count: 0 }
          openDialog(opened)
          setDialogs(current => current.map(item => (
            item.chat_id === dialog.chat_id ? { ...item, unread_count: 0 } : item
          )))
          void api<{ chat_id: number; read: boolean }>(
            '/api/telegram/chats/' + dialog.chat_id + '/read',
            { method: 'POST' }
          ).catch(() => undefined)
        }
        notification.close()
      }
    } catch {
      // Desktop notification support differs between WebView runtimes.
    }
  }

  async function toggleNotifications() {
    if (notificationsEnabled) {
      window.localStorage.setItem('telegram-notifications', '0')
      setNotificationsEnabled(false)
      return
    }
    if (typeof Notification === 'undefined') {
      setError('اعلان دسکتاپ در این محیط پشتیبانی نمی‌شود.')
      return
    }
    try {
      const permission = await Notification.requestPermission()
      const enabled = permission === 'granted'
      window.localStorage.setItem('telegram-notifications', enabled ? '1' : '0')
      setNotificationsEnabled(enabled)
      if (!enabled) setError('مجوز اعلان دسکتاپ صادر نشد.')
    } catch {
      setError('فعال‌کردن اعلان دسکتاپ در این محیط انجام نشد.')
    }
  }

  async function updateDialogState(
    action: 'pin' | 'archive' | 'mute',
    enabled: boolean
  ) {
    if (!selected || dialogActionBusy !== null) return
    setDialogActionBusy(action)
    setError('')
    try {
      const patch = await api<DialogPatch>(
        '/api/telegram/chats/' + selected.chat_id + '/' + action,
        {
          method: 'POST',
          body: JSON.stringify({ enabled })
        }
      )
      applyDialogPatch(patch)
      setChatMenuOpen(false)
    } catch (caught) {
      setError(errorMessage(caught, 'تنظیم گفتگو انجام نشد.'))
    } finally {
      setDialogActionBusy(null)
    }
  }

  function openDialog(dialog: Dialog) {
    const currentChatId = selectedChatIdRef.current
    if (currentChatId === dialog.chat_id) return
    if (currentChatId !== null && !editing) {
      draftsRef.current = updateDraftMap(draftsRef.current, currentChatId, draft)
      window.localStorage.setItem(DRAFT_STORAGE_KEY, JSON.stringify(draftsRef.current))
    }
    draftSwitchRef.current = dialog.chat_id
    setSelected(dialog)
  }

  function openMessageContextMenu(event: ReactMouseEvent, message: Message) {
    event.preventDefault()
    const menuWidth = 220
    const menuHeight = message.outgoing ? 300 : 245
    setMessageContextMenu({
      message,
      x: Math.max(8, Math.min(event.clientX, window.innerWidth - menuWidth - 8)),
      y: Math.max(8, Math.min(event.clientY, window.innerHeight - menuHeight - 8))
    })
  }

  function toggleMessageSelection(messageId: number) {
    setMessageContextMenu(null)
    setSelectedMessageIds(current => {
      const next = new Set(current)
      if (next.has(messageId)) next.delete(messageId)
      else next.add(messageId)
      return next
    })
  }

  async function copyMessages(values: Message[]) {
    const text = values
      .filter(message => !message.deleted && message.text.trim())
      .map(message => message.text.trim())
      .join('\n\n')
    if (!text) {
      setError('متنی برای کپی‌کردن وجود ندارد.')
      return
    }
    try {
      await navigator.clipboard.writeText(text)
      setMessageContextMenu(null)
    } catch {
      setError('کپی‌کردن متن پیام انجام نشد.')
    }
  }

  function closeForwarding() {
    setForwarding(null)
    setBulkBusy(null)
  }

  function beginForwardSelected() {
    if (!selectedMessages.length) return
    setForwardQuery('')
    setForwarding([...selectedMessages].sort((a, b) => a.message_id - b.message_id))
    setBulkBusy('forward')
  }

  async function deleteSelectedMessages() {
    if (!selected || !selectedMessages.length || bulkBusy !== null) return
    if (selectedMessages.some(message => !message.outgoing || message.deleted)) {
      setError('فقط پیام‌های ارسال‌شده توسط خودتان قابل حذف گروهی هستند.')
      return
    }
    if (!window.confirm(new Intl.NumberFormat('fa-IR').format(selectedMessages.length) + ' پیام برای همه حذف شود؟')) return

    setBulkBusy('delete')
    try {
      for (const message of selectedMessages) {
        await api<{ chat_id: number; message_id: number; deleted: boolean }>(
          '/api/telegram/chats/' + message.chat_id + '/messages/' + message.message_id + '/delete',
          { method: 'POST' }
        )
      }
      const deletedIds = new Set(selectedMessages.map(message => message.message_id))
      setMessages(current => current.map(message => (
        deletedIds.has(message.message_id)
          ? { ...message, deleted: true, text: '' }
          : message
      )))
      setSelectedMessageIds(new Set())
    } catch (caught) {
      setError(errorMessage(caught, 'حذف گروهی پیام‌ها کامل نشد.'))
    } finally {
      setBulkBusy(null)
    }
  }

  async function refreshDialogs() {
    try {
      setDialogs(await api<Dialog[]>('/api/telegram/dialogs'))
    } catch (caught) {
      setError(errorMessage(caught, 'به‌روزرسانی گفتگوها انجام نشد.'))
    }
  }

  async function loadOlder() {
    if (!selected || loadingOlder || !hasOlder || !messages.length) return
    const viewport = messageListRef.current
    const previousHeight = viewport?.scrollHeight || 0
    const previousTop = viewport?.scrollTop || 0
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
      window.requestAnimationFrame(() => {
        if (!viewport) return
        viewport.scrollTop = previousTop + viewport.scrollHeight - previousHeight
      })
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
    setMessageContextMenu(null)
    setEditing(null)
    setReplyingTo(message)
  }

  function beginForward(message: Message) {
    setMessageContextMenu(null)
    setForwardQuery('')
    setBulkBusy(null)
    setForwarding([message])
  }

  async function forwardMessageTo(dialog: Dialog) {
    if (!forwarding?.length || forwardTargetBusy !== null) return
    setForwardTargetBusy(dialog.chat_id)
    try {
      const forwarded: Message[] = []
      for (const source of forwarding) {
        forwarded.push(await api<Message>(
          '/api/telegram/chats/' + source.chat_id + '/messages/' + source.message_id + '/forward',
          {
            method: 'POST',
            body: JSON.stringify({ target_chat_id: dialog.chat_id })
          }
        ))
      }
      if (selected?.chat_id === dialog.chat_id) {
        setMessages(current => {
          const forwardedIds = new Set(forwarded.map(message => message.message_id))
          return [
            ...current.filter(message => !forwardedIds.has(message.message_id)),
            ...forwarded
          ].sort((a, b) => a.message_id - b.message_id)
        })
      }
      setForwarding(null)
      setForwardQuery('')
      setSelectedMessageIds(new Set())
      setBulkBusy(null)
    } catch (caught) {
      setError(errorMessage(caught, 'فوروارد پیام انجام نشد.'))
    } finally {
      setForwardTargetBusy(null)
      setBulkBusy(null)
    }
  }

  function beginEdit(message: Message) {
    draftBeforeEditRef.current = draft
    setReplyingTo(null)
    setEditing(message)
    setDraft(message.text)
  }

  function cancelComposerContext() {
    const wasEditing = editing !== null
    setReplyingTo(null)
    setEditing(null)
    if (wasEditing) setDraft(draftBeforeEditRef.current)
  }

  function jumpToMessage(messageId: number) {
    if (!selected) return
    const element = document.getElementById('message-' + selected.chat_id + '-' + messageId)
    if (!element) return
    element.scrollIntoView({ behavior: 'smooth', block: 'center' })
    element.classList.add('message-focus')
    window.setTimeout(() => element.classList.remove('message-focus'), 1400)
  }

  function openPinnedMessage() {
    if (!pinnedMessage) return
    setMessages(current => (
      current.some(item => item.message_id === pinnedMessage.message_id)
        ? current
        : [...current, pinnedMessage].sort((a, b) => a.message_id - b.message_id)
    ))
    window.requestAnimationFrame(() => jumpToMessage(pinnedMessage.message_id))
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

  async function setReaction(message: Message, emoji: string | null) {
    if (message.deleted || reactionBusy !== null) return
    const actionKey = mediaKey(message) + ':' + (emoji || 'remove')
    setReactionBusy(actionKey)
    setError('')
    try {
      const updated = await api<Message>(
        '/api/telegram/chats/' + message.chat_id + '/messages/' + message.message_id + '/reaction',
        {
          method: 'POST',
          body: JSON.stringify({ emoji })
        }
      )
      setMessages(current => current.map(item => item.message_id === updated.message_id ? updated : item))
      setReactionPickerFor(null)
    } catch (caught) {
      setError(errorMessage(caught, 'ثبت واکنش انجام نشد.'))
    } finally {
      setReactionBusy(null)
    }
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
        setDraft(draftBeforeEditRef.current)
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
        setDraft('')
      }
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
    <main className="telegram-shell" onMouseDown={() => setMessageContextMenu(null)}>
      <aside className="chat-sidebar">
        <header className="sidebar-header">
          <div className="brand-title">
            <span className="brand-mark small">✈</span>
            Telegram
            {totalUnread > 0 && <span className="global-unread">{new Intl.NumberFormat('fa-IR').format(totalUnread)}</span>}
          </div>
          <button
            className={'icon-button ' + (notificationsEnabled ? 'active' : '')}
            aria-label={notificationsEnabled ? 'غیرفعال‌کردن اعلان‌ها' : 'فعال‌کردن اعلان‌ها'}
            title={notificationsEnabled ? 'اعلان‌ها فعال است' : 'فعال‌کردن اعلان‌ها'}
            onClick={toggleNotifications}
          >
            {notificationsEnabled ? '🔔' : '♢'}
          </button>
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
            <button className={'dialog-row ' + (selected?.chat_id === dialog.chat_id ? 'selected' : '')} key={dialog.chat_id} onClick={() => openDialog(dialog)}>
              <ChatAvatar chatId={dialog.chat_id} title={dialog.title} />
              <span className="dialog-copy">
                <strong>{dialog.title}</strong>
                <small>
                  {dialog.pinned ? '⌖ ' : ''}
                  {dialog.muted ? '🔕 ' : ''}
                  {dialogTypeLabel(dialog.dialog_type)}
                </small>
              </span>
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
                {selectedChatAction ? (
                  <small className="chat-action-live">
                    {selected.dialog_type !== 'user' && selectedChatAction.user_name
                      ? selectedChatAction.user_name + ' · '
                      : ''}
                    {chatActionLabel(selectedChatAction.action)}
                  </small>
                ) : (
                  <small>
                    {selected.muted ? 'بی‌صدا · ' : ''}
                    {presenceLabel(chatInfo?.status) || dialogTypeLabel(chatInfo?.dialog_type || selected.dialog_type)}
                  </small>
                )}
              </div>
              <div className="header-actions">
                <button className={'icon-button ' + (messageSearchOpen ? 'active' : '')} aria-label="جست‌وجوی پیام" onClick={toggleMessageSearch}>⌕</button>
                <button
                  className={'icon-button ' + (chatMenuOpen ? 'active' : '')}
                  aria-label="تنظیمات گفتگو"
                  onClick={() => setChatMenuOpen(value => !value)}
                >
                  ⋮
                </button>
                {chatMenuOpen && (
                  <div className="chat-menu">
                    <button
                      type="button"
                      onClick={() => updateDialogState('pin', !selected.pinned)}
                      disabled={dialogActionBusy !== null}
                    >
                      <span>⌖</span>{selected.pinned ? 'برداشتن سنجاق گفتگو' : 'سنجاق‌کردن گفتگو'}
                    </button>
                    <button
                      type="button"
                      onClick={() => updateDialogState('mute', !selected.muted)}
                      disabled={dialogActionBusy !== null}
                    >
                      <span>🔕</span>{selected.muted ? 'فعال‌کردن اعلان گفتگو' : 'بی‌صداکردن گفتگو'}
                    </button>
                    <button
                      type="button"
                      onClick={() => updateDialogState('archive', !selected.archived)}
                      disabled={dialogActionBusy !== null}
                    >
                      <span>▣</span>{selected.archived ? 'خارج‌کردن از آرشیو' : 'انتقال به آرشیو'}
                    </button>
                  </div>
                )}
              </div>
            </header>
            {selectedMessageIds.size > 0 && (
              <div className="selection-toolbar">
                <strong>{new Intl.NumberFormat('fa-IR').format(selectedMessageIds.size)} پیام انتخاب شده</strong>
                <button type="button" onClick={() => copyMessages(selectedMessages)}>▣ کپی</button>
                <button type="button" onClick={beginForwardSelected} disabled={bulkBusy !== null}>↗ فوروارد</button>
                <button
                  type="button"
                  className="danger"
                  onClick={() => deleteSelectedMessages()}
                  disabled={bulkBusy !== null || selectedMessages.some(message => !message.outgoing || message.deleted)}
                  title={selectedMessages.some(message => !message.outgoing || message.deleted) ? 'حذف گروهی فقط برای پیام‌های خودتان است' : ''}
                >
                  حذف
                </button>
                <button className="selection-close" type="button" aria-label="لغو انتخاب" onClick={() => setSelectedMessageIds(new Set())}>×</button>
              </div>
            )}
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
            {pinnedMessage && (
              <button className="pinned-banner" type="button" onClick={openPinnedMessage}>
                <span className="pinned-mark">⌖</span>
                <span>
                  <strong>پیام سنجاق‌شده</strong>
                  <small>{messageSnippet(pinnedMessage)}</small>
                </span>
              </button>
            )}
            <div className="message-list" ref={messageListRef} onScroll={handleMessageScroll}>
              {hasOlder && (
                <button className="older-button" onClick={loadOlder} disabled={loadingOlder}>
                  {loadingOlder ? 'در حال دریافت…' : 'پیام‌های قدیمی‌تر'}
                </button>
              )}
              {messages.map((message, index) => (
                <Fragment key={message.message_id}>
                  {index === 0 || messageDayKey(messages[index - 1].date) !== messageDayKey(message.date) ? (
                    <div className="date-separator"><span>{formatMessageDate(message.date)}</span></div>
                  ) : null}
                  {unreadBoundaryId === message.message_id && (
                    <div className="unread-divider"><span>پیام‌های خوانده‌نشده</span></div>
                  )}
                <article
                  id={'message-' + message.chat_id + '-' + message.message_id}
                  className={
                    'message '
                    + (message.outgoing ? 'outgoing' : '')
                    + (message.deleted ? ' deleted' : '')
                    + (selectedMessageIds.has(message.message_id) ? ' selected-message' : '')
                  }
                  onContextMenu={event => openMessageContextMenu(event, message)}
                  onClick={event => {
                    if (
                      selectedMessageIds.size > 0
                      && !(event.target as HTMLElement).closest('button')
                    ) toggleMessageSelection(message.message_id)
                  }}
                >
                  {selectedMessageIds.size > 0 && (
                    <span className="message-selector" aria-hidden="true">
                      {selectedMessageIds.has(message.message_id) ? '✓' : ''}
                    </span>
                  )}
                  {!message.outgoing && message.sender_name && <strong className="sender-name">{message.sender_name}</strong>}
                  {renderReplyReference(message)}
                  {message.media && renderMedia(message)}
                  {message.deleted ? <span>پیام حذف شده است</span> : message.text && <span>{message.text}</span>}
                  {!message.deleted && Boolean(message.reactions?.length) && (
                    <div className="message-reactions">
                      {message.reactions.map(reaction => (
                        <button
                          type="button"
                          className={reaction.chosen ? 'chosen' : ''}
                          key={reaction.emoji}
                          onClick={() => setReaction(message, reaction.chosen ? null : reaction.emoji)}
                          disabled={reactionBusy !== null}
                        >
                          <span>{reaction.emoji}</span>
                          <small>{new Intl.NumberFormat('fa-IR').format(reaction.count)}</small>
                        </button>
                      ))}
                    </div>
                  )}
                  {!message.deleted && selectedMessageIds.size === 0 && (
                    <div className="message-actions">
                      <button type="button" onClick={() => beginReply(message)}>↩ پاسخ</button>
                      <button
                        type="button"
                        onClick={() => setReactionPickerFor(current => current === message.message_id ? null : message.message_id)}
                      >
                        ☺ واکنش
                      </button>
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
                  {reactionPickerFor === message.message_id && !message.deleted && selectedMessageIds.size === 0 && (
                    <div className="reaction-picker" role="group" aria-label="انتخاب واکنش">
                      {QUICK_REACTIONS.map(emoji => {
                        const chosen = message.reactions?.some(item => item.emoji === emoji && item.chosen) || false
                        const key = mediaKey(message) + ':' + (chosen ? 'remove' : emoji)
                        return (
                          <button
                            type="button"
                            className={chosen ? 'chosen' : ''}
                            key={emoji}
                            onClick={() => setReaction(message, chosen ? null : emoji)}
                            disabled={reactionBusy !== null}
                          >
                            {reactionBusy === key ? '…' : emoji}
                          </button>
                        )
                      })}
                    </div>
                  )}
                  <small className="message-meta">
                    <span>{formatTime(message.date)}{message.edited ? ' · ویرایش‌شده' : ''}</span>
                    {message.outgoing && (
                      <span
                        className={'read-receipt ' + (message.read ? 'read' : 'sent')}
                        aria-label={message.read ? 'خوانده شده' : 'ارسال شده'}
                        title={message.read ? 'خوانده شده' : 'ارسال شده'}
                      >
                        {message.read ? '✓✓' : '✓'}
                      </span>
                    )}
                  </small>
                </article>
                </Fragment>
              ))}
              {showJumpToBottom && (
                <button className="jump-bottom" type="button" onClick={() => scrollToBottom('smooth')} aria-label="رفتن به آخر گفتگو">
                  <span>↓</span>
                  {newBelowCount > 0 && <strong>{new Intl.NumberFormat('fa-IR').format(newBelowCount)}</strong>}
                </button>
              )}
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
              <form className="composer" ref={composerFormRef} onSubmit={sendMessage}>
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

      {messageContextMenu && (
        <div
          className="message-context-menu"
          style={{ left: messageContextMenu.x, top: messageContextMenu.y }}
          role="menu"
          onMouseDown={event => event.stopPropagation()}
        >
          <button type="button" role="menuitem" onClick={() => beginReply(messageContextMenu.message)}>↩ پاسخ</button>
          <button
            type="button"
            role="menuitem"
            onClick={() => {
              setReactionPickerFor(messageContextMenu.message.message_id)
              setMessageContextMenu(null)
            }}
          >
            ☺ واکنش
          </button>
          <button type="button" role="menuitem" onClick={() => beginForward(messageContextMenu.message)}>↗ فوروارد</button>
          <button type="button" role="menuitem" onClick={() => copyMessages([messageContextMenu.message])}>▣ کپی متن</button>
          <button type="button" role="menuitem" onClick={() => toggleMessageSelection(messageContextMenu.message.message_id)}>☑ انتخاب</button>
          {messageContextMenu.message.outgoing && messageContextMenu.message.text && !messageContextMenu.message.deleted && (
            <button type="button" role="menuitem" onClick={() => {
              beginEdit(messageContextMenu.message)
              setMessageContextMenu(null)
            }}>✎ ویرایش</button>
          )}
          {messageContextMenu.message.outgoing && !messageContextMenu.message.deleted && (
            <button type="button" role="menuitem" className="danger" onClick={() => {
              const message = messageContextMenu.message
              setMessageContextMenu(null)
              void deleteMessage(message)
            }}>حذف</button>
          )}
        </div>
      )}

      {forwarding && (
        <div className="forward-backdrop" onMouseDown={closeForwarding}>
          <section className="forward-modal" role="dialog" aria-modal="true" aria-label="انتخاب مقصد فوروارد" onMouseDown={event => event.stopPropagation()}>
            <header>
              <div>
                <strong>
                  {forwarding.length === 1
                    ? 'فوروارد پیام'
                    : 'فوروارد ' + new Intl.NumberFormat('fa-IR').format(forwarding.length) + ' پیام'}
                </strong>
                <small>{messageSnippet(forwarding[0])}</small>
              </div>
              <button className="icon-button" type="button" aria-label="بستن" onClick={closeForwarding}>×</button>
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
