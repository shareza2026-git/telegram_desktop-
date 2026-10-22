import { Fragment, memo, useCallback, useEffect, useMemo, useRef, useState, type ClipboardEvent, type DragEvent, type FormEvent, type MouseEvent as ReactMouseEvent } from 'react'
import { invoke } from '@tauri-apps/api/core'
import { getCurrentWindow } from '@tauri-apps/api/window'

import { api, apiBlob, authedUrl, backendFetch, chatPath, configureBackend } from './backend'
import { DialogRow, type DialogActions } from './DialogRow'
import { DRAFT_STORAGE_KEY, parseDraftMap, updateDraftMap } from './drafts'
import {
  chatActionLabel,
  dialogTypeLabel,
  errorMessage,
  formatBytes,
  formatCompact,
  formatDialogTime,
  formatMessageDate,
  messageDayKey,
  formatNumber,
  formatTime,
  isChannelId,
  mediaKindLabel,
  messageSnippet,
  presenceLabel,
  statusLabel
} from './format'
import { Icon } from './icons'
import { ChatAvatar, MediaViewer } from './media'
import { MessageBubble, type BubbleActions } from './MessageBubble'
import { buildMessageRows } from './messageList'
import type {
  AuthResponse,
  AuthStep,
  ChatAction,
  ChatInfo,
  CallEntry,
  ContactInfo,
  DeviceSession,
  Dialog,
  DialogContextMenu,
  DialogFolder,
  DialogPatch,
  FolderKey,
  MediaState,
  Message,
  MessageContextMenu,
  PendingAttachment,
  ProxyProbe,
  ReactionUpdate,
  ReadReceipt,
  RecentMediaCatalog,
  RecentMediaItem,
  Status,
  TransportStatus
} from './types'
import { PREFERENCES_STORAGE_KEY, parsePreferences, resolvedTheme, type ClientPreferences } from './preferences'
import { shouldHoldAuthScreen, canShowCachedWorkspace } from './startup'

type RelayStatus = {
  configured: boolean
  connected: boolean
  authorized: boolean
  display_name?: string | null
  pending: number
  sent: number
  failed: number
  blocked: number
  delete_pending: number
  deleted: number
  delete_failed: number
  last_delivery_ms?: number | null
  last_error?: string | null
}

type RelayChannel = { chat_id: number; title: string; dialog_type?: string }
type RelayMapping = {
  id: number
  source_chat_id: number
  destination_chat_id: number
  source_title: string
  destination_title: string
}

const HISTORY_PAGE_SIZE = 80
const MAX_LOADED_MESSAGES = 480
const COMPOSER_EMOJIS = [
  '😀', '😃', '😄', '😁', '😆', '😅', '😂', '🙂', '🙃', '😉',
  '😊', '😍', '🥰', '😘', '😎', '🤔', '😮', '😢', '😭', '😡',
  '👍', '👎', '👏', '🙏', '🤝', '💪', '❤️', '💔', '🔥', '✨',
  '🎉', '✅', '❌', '⚡', '💯', '👀', '📌', '📎', '🚀', '🌹'
]
let backendBase = (import.meta.env.VITE_BACKEND_URL || 'http://127.0.0.1:8110').replace(/\/$/, '')
let socketBase = backendBase.replace(/^http/, 'ws')
let runtimeStoragePrefix = 'telegram-instance-development'

export function configureRuntime(port: number, instanceId: string) {
  backendBase = 'http://127.0.0.1:' + port
  socketBase = 'ws://127.0.0.1:' + port
  runtimeStoragePrefix = 'telegram-instance-' + instanceId
  configureBackend(port)
}

function instanceStorageKey(key: string) {
  return runtimeStoragePrefix + ':' + key
}

// Null when the UI runs in a plain browser (vite dev without the Tauri shell).
const appWindow = '__TAURI_INTERNALS__' in window ? getCurrentWindow() : null
const startupParams = new URLSearchParams(window.location.search)
const popoutChatId = startupParams.get('popout') === '1'
  ? Number(startupParams.get('chat') || 0)
  : 0
const isPopoutWindow = Boolean(popoutChatId)
if (isPopoutWindow) {
  document.documentElement.classList.add('popout-window')
}
/**
 * Stable callbacks that always run the latest render's handler. Memoized rows
 * receive these, so typing in the composer does not re-render every message.
 */
function useStableHandlers<T extends object>(handlers: T): T {
  const ref = useRef(handlers)
  ref.current = handlers
  return useMemo(() => {
    const stable: Record<string, unknown> = {}
    for (const key of Object.keys(handlers)) {
      stable[key] = (...args: unknown[]) => (ref.current as Record<string, (...values: unknown[]) => unknown>)[key](...args)
    }
    return stable as T
  }, [])
}

// Header subtitle in Telegram's words: presence for people, size for groups.
function headerStatus(dialog: Dialog, info: ChatInfo | null) {
  const presence: Record<string, string> = {
    online: 'online', offline: 'last seen recently', recently: 'last seen recently',
    last_week: 'last seen within a week', last_month: 'last seen within a month'
  }
  if (dialog.dialog_type === 'user') return info?.is_bot ? 'bot' : presence[info?.status || ''] || 'last seen recently'
  const count = info?.participants_count
  const noun = dialog.dialog_type === 'channel' ? 'subscribers' : 'members'
  if (count != null) return new Intl.NumberFormat('en-US').format(count) + ' ' + noun
  return dialog.dialog_type === 'channel' ? 'channel' : 'group'
}

function isGroupType(value: string) {
  return value === 'group' || value === 'supergroup'
}

function firstName(value?: string | null) {
  return (value || '').trim().split(/\s+/)[0] || null
}

const COUNTRY_NAMES: Record<string, string> = {
  '+98': 'Iran', '+1': 'USA / Canada', '+44': 'United Kingdom', '+49': 'Germany', '+90': 'Turkey',
  '+971': 'United Arab Emirates', '+7': 'Russia', '+93': 'Afghanistan', '+964': 'Iraq', '+33': 'France',
  '+39': 'Italy', '+31': 'Netherlands', '+46': 'Sweden', '+61': 'Australia', '+91': 'India', '+86': 'China'
}

function countryName(code: string) {
  return COUNTRY_NAMES[code] || 'Country'
}

function upsertSortedMessage(current: Message[], message: Message): Message[] {
  const index = current.findIndex(item => item.message_id === message.message_id)
  if (index >= 0) {
    if (current[index] === message) return current
    const next = current.slice()
    next[index] = message
    return next
  }

  if (!current.length || current[current.length - 1].message_id < message.message_id) {
    return [...current, message]
  }
  if (current[0].message_id > message.message_id) {
    return [message, ...current]
  }

  let low = 0
  let high = current.length
  while (low < high) {
    const mid = (low + high) >>> 1
    if (current[mid].message_id < message.message_id) low = mid + 1
    else high = mid
  }
  return [...current.slice(0, low), message, ...current.slice(low)]
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
  const [apiIdDraft, setApiIdDraft] = useState('')
  const [apiHashDraft, setApiHashDraft] = useState('')
  const [runtimeConfigBusy, setRuntimeConfigBusy] = useState(false)
  const [activeFolder, setActiveFolder] = useState<FolderKey>('all')
  const [telegramFolders, setTelegramFolders] = useState<DialogFolder[]>([])
  const [sidebarWidth, setSidebarWidth] = useState(() => Number(window.localStorage.getItem(instanceStorageKey('telegram-sidebar-width'))) || 312)
  const sidebarResizeRef = useRef<{ startX: number; startWidth: number } | null>(null)
  const sidebarResizeCleanupRef = useRef<(() => void) | null>(null)
  const [loadingOlder, setLoadingOlder] = useState(false)
  const [hasOlder, setHasOlder] = useState(false)
  const [hasNewer, setHasNewer] = useState(false)
  const [mediaStates, setMediaStates] = useState<Record<string, MediaState>>({})
  const [replyingTo, setReplyingTo] = useState<Message | null>(null)
  const [editing, setEditing] = useState<Message | null>(null)
  const [composerBusy, setComposerBusy] = useState(false)
  const [uploadBusy, setUploadBusy] = useState(false)
  const [uploadName, setUploadName] = useState('')
  const [pendingAttachments, setPendingAttachments] = useState<PendingAttachment[]>([])
  const [dragActive, setDragActive] = useState(false)
  const [mediaPanel, setMediaPanel] = useState<'emoji' | 'sticker' | 'gif' | null>(null)
  const [recentMedia, setRecentMedia] = useState<RecentMediaCatalog | null>(null)
  const [recentMediaBusy, setRecentMediaBusy] = useState(false)
  const [recentMediaSending, setRecentMediaSending] = useState<string | null>(null)
  const fileInputRef = useRef<HTMLInputElement>(null)
  const composerInputRef = useRef<HTMLInputElement>(null)
  const composerFormRef = useRef<HTMLFormElement>(null)
  const messageListRef = useRef<HTMLDivElement>(null)
  const stickToBottomRef = useRef(true)
  const selectedChatIdRef = useRef<number | null>(null)
  const [messageActionBusy, setMessageActionBusy] = useState<string | null>(null)
  const [reactionPickerFor, setReactionPickerFor] = useState<number | null>(null)
  const [reactionBusy, setReactionBusy] = useState<string | null>(null)
  const [selectedChatAction, setSelectedChatAction] = useState<ChatAction | null>(null)
  // Typing/uploading per chat, for the chat list (like Telegram).
  const [chatActions, setChatActions] = useState<Record<number, ChatAction>>({})
  const [viewerMessage, setViewerMessage] = useState<Message | null>(null)
  const [countryCode, setCountryCode] = useState('+98')
  const [contactsOpen, setContactsOpen] = useState(false)
  const [addAccountOpen, setAddAccountOpen] = useState(false)
  const [calls, setCalls] = useState<CallEntry[] | null>(null)
  const [callsOpen, setCallsOpen] = useState(false)
  const [contacts, setContacts] = useState<ContactInfo[] | null>(null)
  const [contactsQuery, setContactsQuery] = useState('')
  const [createKind, setCreateKind] = useState<'group' | 'channel' | null>(null)
  const [createTitle, setCreateTitle] = useState('')
  const [createAbout, setCreateAbout] = useState('')
  const [createBusy, setCreateBusy] = useState(false)
  const typingTimerRef = useRef<number | null>(null)
  const typingSentRef = useRef<{ chatId: number; active: boolean; at: number } | null>(null)
  const chatActionTimerRef = useRef<number | null>(null)
  const focusTimerRef = useRef<number | null>(null)
  const searchJumpTimerRef = useRef<number | null>(null)
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
    && window.localStorage.getItem(instanceStorageKey('telegram-notifications')) === '1'
  ))
  const [chatMenuOpen, setChatMenuOpen] = useState(false)
  const [dialogActionBusy, setDialogActionBusy] = useState<string | null>(null)
  const [messageContextMenu, setMessageContextMenu] = useState<MessageContextMenu | null>(null)
  const [dialogContextMenu, setDialogContextMenu] = useState<DialogContextMenu | null>(null)
  const [selectedMessageIds, setSelectedMessageIds] = useState<Set<number>>(() => new Set())
  const [bulkBusy, setBulkBusy] = useState<'delete' | 'forward' | null>(null)
  const [settingsOpen, setSettingsOpen] = useState(false)
  const [relayOpen, setRelayOpen] = useState(false)
  const [relayStatus, setRelayStatus] = useState<RelayStatus | null>(null)
  const [relayMappings, setRelayMappings] = useState<RelayMapping[]>([])
  const [relaySources, setRelaySources] = useState<RelayChannel[]>([])
  const [relayDestinations, setRelayDestinations] = useState<RelayChannel[]>([])
  const [relayAddOpen, setRelayAddOpen] = useState(false)
  const [relaySourceDraft, setRelaySourceDraft] = useState('')
  const [relayDestinationDraft, setRelayDestinationDraft] = useState('')
  const [relayPhone, setRelayPhone] = useState('')
  const [relayCode, setRelayCode] = useState('')
  const [relayPassword, setRelayPassword] = useState('')
  const [relayAuthStep, setRelayAuthStep] = useState<AuthStep>('phone')
  const [relayBusy, setRelayBusy] = useState(false)
  const [relayError, setRelayError] = useState('')
  const [proxySettingsOpen, setProxySettingsOpen] = useState(false)
  const [proxyProbes, setProxyProbes] = useState<ProxyProbe[]>([])
  const [proxyBusy, setProxyBusy] = useState(false)
  const [proxyLinkDraft, setProxyLinkDraft] = useState('')
  const [showProxyAdd, setShowProxyAdd] = useState(false)
  const [showAuthProxyManager, setShowAuthProxyManager] = useState(false)
  const [mainMenuOpen, setMainMenuOpen] = useState(false)
  const verifyInFlightRef = useRef(false)
  const [instances, setInstances] = useState<Array<[string, string, boolean]>>([])
  const [newAccountName, setNewAccountName] = useState('')
  const [addAccountBusy, setAddAccountBusy] = useState(false)
  const [addAccountError, setAddAccountError] = useState('')
  const [newAccountCountry, setNewAccountCountry] = useState('+98')
  const [transportStatus, setTransportStatus] = useState<TransportStatus | null>(null)
  const [deviceSessions, setDeviceSessions] = useState<DeviceSession[]>([])
  const [settingsBusy, setSettingsBusy] = useState(false)
  const [logoutBusy, setLogoutBusy] = useState(false)
  const [preferences, setPreferences] = useState<ClientPreferences>(() => (
    parsePreferences(window.localStorage.getItem(instanceStorageKey(PREFERENCES_STORAGE_KEY)))
  ))
  const [revealedPhotos, setRevealedPhotos] = useState<Set<string>>(() => new Set())
  const dialogsRef = useRef<Dialog[]>([])
  const notificationsEnabledRef = useRef(notificationsEnabled)
  const draftsRef = useRef(parseDraftMap(window.localStorage.getItem(instanceStorageKey(DRAFT_STORAGE_KEY))))
  const draftSwitchRef = useRef<number | null>(null)
  const draftBeforeEditRef = useRef('')
  const liveDraftRef = useRef(draft)
  const editingRef = useRef<Message | null>(editing)
  const pendingAttachmentsRef = useRef<PendingAttachment[]>([])
  const hasNewerRef = useRef(hasNewer)

  liveDraftRef.current = draft
  editingRef.current = editing
  hasNewerRef.current = hasNewer

  const visibleDialogs = useMemo(() => {
    let values = dialogs
    if (activeFolder.startsWith('folder:')) {
      const folderId = Number(activeFolder.slice('folder:'.length))
      const folder = telegramFolders.find(item => item.id === folderId)
      const allowed = new Set(folder?.chat_ids || [])
      values = values.filter(item => allowed.has(item.chat_id))
    } else {
      if (activeFolder === 'private') values = values.filter(item => item.dialog_type === 'user' && !item.archived)
      if (activeFolder === 'unread') values = values.filter(item => item.unread_count > 0 && !item.archived)
      if (activeFolder === 'groups') values = values.filter(item => (item.dialog_type === 'group' || item.dialog_type === 'supergroup') && !item.archived)
      if (activeFolder === 'channels') values = values.filter(item => item.dialog_type === 'channel' && !item.archived)
      if (activeFolder === 'archived') values = values.filter(item => item.archived)
      if (activeFolder === 'all') values = values.filter(item => !item.archived)
    }

    const value = query.trim().toLocaleLowerCase()
    if (value) values = values.filter(item => item.title.toLocaleLowerCase().includes(value))

    // Parse each date once, not on every comparison of the sort.
    const times = new Map(values.map(item => [item.chat_id, item.last_message_at ? Date.parse(item.last_message_at) : 0]))
    return [...values].sort((a, b) => {
      if (a.pinned !== b.pinned) return a.pinned ? -1 : 1
      return (times.get(b.chat_id) || 0) - (times.get(a.chat_id) || 0)
    })
  }, [activeFolder, dialogs, query, telegramFolders])

  const totalUnread = useMemo(
    () => dialogs.reduce((total, dialog) => total + (dialog.muted || dialog.archived ? 0 : dialog.unread_count), 0),
    [dialogs]
  )

  const selectedMessages = useMemo(
    () => messages.filter(message => selectedMessageIds.has(message.message_id)),
    [messages, selectedMessageIds]
  )

  const visibleMessages = useMemo(
    () => messages.filter(message => !message.deleted),
    [messages]
  )

  const messageRows = useMemo(() => buildMessageRows(visibleMessages), [visibleMessages])
  const messagesById = useMemo(() => new Map(messages.map(item => [item.message_id, item])), [messages])

  const bubbleActions = useStableHandlers<BubbleActions>({
    contextMenu: (event, message) => {
      if (message.pending) {
        event.preventDefault()
        return
      }
      openMessageContextMenu(event, message)
    },
    toggleSelection: messageId => toggleMessageSelection(messageId),
    jumpTo: messageId => jumpToMessage(messageId),
    react: (message, emoji) => void setReaction(message, emoji),
    download: message => void downloadMedia(message),
    view: message => setViewerMessage(message),
    reveal: key => setRevealedPhotos(current => new Set(current).add(key)),
    openLink: url => openLink(url),
    addProxy: url => void addProxyLink(url)
  })

  const messageNodes = useMemo(() => {
    const isGroup = isGroupType(selected?.dialog_type || '')
    const chatTitle = selected?.title || ''
    return messageRows.map(row => {
      const lead = row.lead
      const key = lead.chat_id + ':' + lead.message_id
      return (
        <Fragment key={lead.message_id}>
          {row.dayBreak && (
            <div className="date-separator"><span>{formatMessageDate(lead.date)}</span></div>
          )}
          {unreadBoundaryId !== null && row.items.some(item => item.message_id === unreadBoundaryId) && (
            <div className="unread-divider"><span>Unread Messages</span></div>
          )}
          <MessageBubble
            message={lead}
            album={row.items.length > 1 ? row.items : undefined}
            isGroup={isGroup}
            showSender={row.showSender}
            showAvatar={row.showAvatar}
            chatTitle={chatTitle}
            replySource={lead.reply_to_message_id ? messagesById.get(lead.reply_to_message_id) || null : undefined}
            selected={selectedMessageIds.has(lead.message_id)}
            selectionMode={selectedMessageIds.size > 0}
            pickerOpen={reactionPickerFor === lead.message_id}
            reactionBusy={reactionBusy !== null && reactionBusy.startsWith(key + ':') ? reactionBusy : null}
            mediaState={mediaStates[key] || 'ready'}
            autoLoadPhotos={preferences.autoLoadPhotos}
            revealed={revealedPhotos.has(key)}
            actions={bubbleActions}
          />
        </Fragment>
      )
    })
  }, [
    messageRows,
    messagesById,
    unreadBoundaryId,
    selectedMessageIds,
    selected?.title,
    selected?.dialog_type,
    reactionPickerFor,
    reactionBusy,
    mediaStates,
    preferences.autoLoadPhotos,
    revealedPhotos,
    bubbleActions
  ])

  const dialogActions = useStableHandlers<DialogActions>({
    open: dialog => openDialog(dialog),
    contextMenu: (event, dialog) => openDialogContextMenu(event, dialog)
  })

  const closeViewer = useCallback(() => setViewerMessage(null), [])

  useEffect(() => {
    selectedChatIdRef.current = selected?.chat_id || null
    setChatMenuOpen(false)
    if (chatActionTimerRef.current !== null) {
      window.clearTimeout(chatActionTimerRef.current)
      chatActionTimerRef.current = null
    }
    setSelectedChatAction(null)
  }, [selected?.chat_id, status?.authorized])

  useEffect(() => {
    return () => {
      if (typingTimerRef.current !== null) window.clearTimeout(typingTimerRef.current)
      if (chatActionTimerRef.current !== null) window.clearTimeout(chatActionTimerRef.current)
      if (focusTimerRef.current !== null) window.clearTimeout(focusTimerRef.current)
      if (searchJumpTimerRef.current !== null) window.clearTimeout(searchJumpTimerRef.current)
      sidebarResizeCleanupRef.current?.()
      sidebarResizeCleanupRef.current = null
      document.body.classList.remove('sidebar-resizing')
    }
  }, [])

  useEffect(() => {
    dialogsRef.current = dialogs
  }, [dialogs])


  useEffect(() => {
    if (!isPopoutWindow || !popoutChatId || !status?.authorized) return
    if (selectedChatIdRef.current === popoutChatId) return

    let disposed = false
    api<ChatInfo>('/api/telegram/chats/' + popoutChatId)
      .then(info => {
        if (disposed || selectedChatIdRef.current === popoutChatId) return
        openDialog({
          chat_id: info.chat_id,
          title: info.title,
          dialog_type: info.dialog_type,
          username: info.username,
          unread_count: 0,
          pinned: false,
          archived: false,
          muted: false
        })
      })
      .catch(error => {
        if (!disposed) setError(errorMessage(error, 'گفتگو در پنجره جدید بارگذاری نشد.'))
      })

    return () => {
      disposed = true
    }
  }, [status?.authorized])

  useEffect(() => {
    notificationsEnabledRef.current = notificationsEnabled
  }, [notificationsEnabled])

  useEffect(() => {
    window.localStorage.setItem(instanceStorageKey(PREFERENCES_STORAGE_KEY), JSON.stringify(preferences))
    const media = window.matchMedia('(prefers-color-scheme: light)')
    const applyTheme = () => {
      document.documentElement.dataset.theme = resolvedTheme(preferences.theme, media.matches)
    }
    applyTheme()
    media.addEventListener('change', applyTheme)
    return () => media.removeEventListener('change', applyTheme)
  }, [preferences])

  useEffect(() => {
    pendingAttachmentsRef.current = pendingAttachments
  }, [pendingAttachments])

  useEffect(() => () => {
    for (const item of pendingAttachmentsRef.current) {
      if (item.previewUrl) URL.revokeObjectURL(item.previewUrl)
    }
  }, [])

  useEffect(() => {
    document.title = totalUnread > 0
      ? '(' + formatNumber(totalUnread) + ') Telegram'
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

  useEffect(() => {
    if (status?.state !== 'PROXY_ERROR' && !showAuthProxyManager) return

    let disposed = false
    const refresh = async () => {
      try {
        const transport = await api<TransportStatus>('/api/telegram/transport')
        if (!disposed) setTransportStatus(transport)
        const probes = await api<ProxyProbe[]>('/api/telegram/transport/probe')
        if (!disposed) setProxyProbes(probes)
      } catch {
        // Keep the recovery screen usable; the next polling cycle retries.
      }
    }

    void refresh()
    const timer = window.setInterval(() => void refresh(), 20000)
    return () => {
      disposed = true
      window.clearInterval(timer)
    }
  }, [status?.state, showAuthProxyManager])

  const forwardDialogs = useMemo(() => {
    const value = forwardQuery.trim().toLocaleLowerCase()
    if (!value) return dialogs
    return dialogs.filter(item => (
      item.title.toLocaleLowerCase().includes(value)
      || Boolean(item.username?.toLocaleLowerCase().includes(value))
    ))
  }, [dialogs, forwardQuery])

  useEffect(() => {
    let disposed = false
    let retryTimer: number | undefined
    let retryCount = 0
    let socket: WebSocket | undefined
    let snapshotPromise: Promise<void> | null = null
    let lastFullSnapshotAt = 0
    let cacheHydrated = false

    async function hydrateCachedDialogs() {
      if (isPopoutWindow || disposed || cacheHydrated) return
      try {
        const cached = await api<Dialog[]>('/api/cache/dialogs')
        if (disposed) return
        cacheHydrated = true
        if (cached.length) setDialogs(cached)
      } catch {
        // The sidecar may still be starting; socket open retries this immediately.
      }
    }

    async function refreshStatus() {
      try {
        const nextStatus = await api<Status>('/api/telegram/status')
        if (!disposed) setStatus(nextStatus)
        return nextStatus
      } catch {
        return null
      }
    }

    async function refreshSnapshot(force = false) {
      if (isPopoutWindow) {
        await refreshStatus()
        return
      }
      const now = Date.now()
      if (!force && lastFullSnapshotAt && now - lastFullSnapshotAt < 15000) return
      if (snapshotPromise) return snapshotPromise

      snapshotPromise = (async () => {
        try {
          const nextStatus = await refreshStatus()
          if (!nextStatus?.authorized || disposed) return

          const nextDialogs = await api<Dialog[]>('/api/telegram/dialogs')
          if (disposed) return
          setDialogs(nextDialogs)

          const nextFolders = await api<DialogFolder[]>('/api/telegram/dialog-folders')
          if (disposed) return
          setTelegramFolders(nextFolders)
          lastFullSnapshotAt = Date.now()
        } catch {
          // The packaged backend can need a moment to start. WebSocket retry handles recovery.
        } finally {
          snapshotPromise = null
        }
      })()
      return snapshotPromise
    }

    async function resyncActiveChat() {
      await refreshStatus()
      const chatId = selectedChatIdRef.current
      if (!chatId || disposed) return
      try {
        const current = await api<Message[]>('/api/telegram/chats/' + chatId + '/messages?limit=' + HISTORY_PAGE_SIZE)
        if (!disposed && selectedChatIdRef.current === chatId) {
          setMessages(current.filter(item => !item.deleted))
          setHasOlder(current.length === HISTORY_PAGE_SIZE)
          setHasNewer(false)
        }
      } catch {
        // A later reconnect or explicit refresh will retry the active chat.
      }
    }

    function connectSocket() {
      if (disposed) return
      const socketUrl = isPopoutWindow && popoutChatId
        ? socketBase + '/ws/telegram?chat_id=' + encodeURIComponent(String(popoutChatId))
        : socketBase + '/ws/telegram'
      socket = new WebSocket(authedUrl(socketUrl))
      socket.onopen = () => {
        const wasReconnect = retryCount > 0
        retryCount = 0
        void hydrateCachedDialogs()
        if (!isPopoutWindow && !lastFullSnapshotAt) void refreshSnapshot()
        if (wasReconnect) void resyncActiveChat()
      }
      socket.onmessage = event => {
        // Busy chats push several messages per second. Collect what arrives
        // within a few milliseconds and apply it in one React update instead
        // of re-rendering (and re-sorting the chat list) once per message.
        let packet: { type: string; data: unknown; priority?: boolean }
        try {
          packet = JSON.parse(event.data as string)
        } catch {
          return
        }
        pendingPackets.push(packet)
        if (packet.priority) {
          // Quotes from priority chats are drawn at once, with whatever else
          // is already waiting, instead of after the batching delay.
          if (flushTimer !== undefined) window.clearTimeout(flushTimer)
          flushPackets()
        } else if (flushTimer === undefined) {
          flushTimer = window.setTimeout(flushPackets, 16)
        }
      }
      socket.onclose = () => {
        if (disposed) return
        void refreshStatus()
        const delay = Math.min(250 * 2 ** Math.min(retryCount, 5), 5000)
        retryCount += 1
        retryTimer = window.setTimeout(connectSocket, delay)
      }
      socket.onerror = () => socket?.close()
    }

    let pendingPackets: Array<{ type: string; data: unknown; priority?: boolean }> = []
    let flushTimer: number | undefined

    function flushPackets() {
      flushTimer = undefined
      const batch = pendingPackets
      pendingPackets = []
      for (const packet of batch) {
        try {
          handlePacket(packet)
        } catch {
          // One malformed packet must not stop live updates.
        }
      }
    }

    function handlePacket(packet: { type: string; data: unknown }) {
      if (packet.type === 'READY') {
        const ready = packet.data as Status
        setStatus(ready)
        // A fresh connection (e.g. after switching proxy) makes old login errors stale.
        if (!ready.authorized && ready.connected) setError('')
        if (ready.authorized) {
          setError('')
          setAuthBusy(false)
        }
        if (ready.authorized && !lastFullSnapshotAt && !isPopoutWindow) {
          void refreshSnapshot()
        }
      }
      if (packet.type === 'RESYNC') {
        if (isPopoutWindow) {
          void resyncActiveChat()
        } else {
          void refreshSnapshot(true).then(() => resyncActiveChat())
        }
      }
      if (packet.type === 'DIALOGS_REFRESHED' && !isPopoutWindow) {
        if (snapshotPromise) {
          void snapshotPromise.then(() => refreshSnapshot(true))
        } else {
          void refreshSnapshot(true)
        }
      }
      if (packet.type === 'MESSAGE_NEW' || packet.type === 'MESSAGE_EDITED') {
        const message = packet.data as Message
        if (isPopoutWindow && selectedChatIdRef.current !== message.chat_id) return
        const isNew = packet.type === 'MESSAGE_NEW'
        if (!isPopoutWindow) setDialogs(current => current.map(dialog => {
          if (dialog.chat_id !== message.chat_id) return dialog
          if (!isNew && dialog.last_message_id != null && dialog.last_message_id !== message.message_id) return dialog
          const activeAndVisible = (
            selectedChatIdRef.current === message.chat_id
            && document.visibilityState === 'visible'
          )
          return {
            ...dialog,
            last_message_id: message.message_id,
            last_message_at: isNew ? message.date : dialog.last_message_at,
            last_message_preview: messageSnippet(message),
            last_message_sender: isGroupType(dialog.dialog_type) && !message.action
              ? (message.outgoing ? 'شما' : firstName(message.sender_name))
              : null,
            last_message_outgoing: message.outgoing,
            last_message_read: isNew ? false : dialog.last_message_read,
            unread_count: isNew && !message.outgoing && !activeAndVisible
              ? dialog.unread_count + 1
              : dialog.unread_count
          }
        }))
        if (!isPopoutWindow && packet.type === 'MESSAGE_NEW' && !message.outgoing) {
          const activeAndVisible = (
            selectedChatIdRef.current === message.chat_id
            && document.visibilityState === 'visible'
          )
          if (!activeAndVisible) {
            showDesktopNotification(message)
          }
        }
        if (selectedChatIdRef.current === message.chat_id) {
          const browsingOlderWindow = hasNewerRef.current
          const shouldFollow = !browsingOlderWindow && (message.outgoing || isNearBottom())
          setMessages(current => {
            const exists = current.some(item => item.message_id === message.message_id)
            if (packet.type === 'MESSAGE_NEW' && !message.outgoing && (!shouldFollow || browsingOlderWindow) && !exists) {
              setNewBelowCount(count => count + 1)
            }
            if (browsingOlderWindow && packet.type === 'MESSAGE_NEW' && !exists) return current
            const next = upsertSortedMessage(current, message)
            return next.length > MAX_LOADED_MESSAGES
              ? next.slice(next.length - MAX_LOADED_MESSAGES)
              : next
          })
          if (shouldFollow) {
            window.requestAnimationFrame(() => scrollToBottom(message.outgoing ? 'smooth' : 'auto'))
          }
        }
      }
      if (packet.type === 'DIALOG_UPDATED' && !isPopoutWindow) {
        applyDialogPatch(packet.data as DialogPatch)
      }
      if (packet.type === 'MESSAGE_REACTIONS') {
        const update = packet.data as ReactionUpdate
        if (selectedChatIdRef.current === update.chat_id) {
          setMessages(current => current.map(item => {
            if (item.message_id !== update.message_id) return item
            const reactions = update.min
              ? update.reactions.map(reaction => ({
                ...reaction,
                chosen: item.reactions.some(own => own.emoji === reaction.emoji && own.chosen)
              }))
              : update.reactions
            return { ...item, reactions }
          }))
        }
      }
      if (packet.type === 'USER_STATUS') {
        const value = packet.data as { user_id: number; status: string | null }
        setChatInfo(current => (current && current.chat_id === value.user_id ? { ...current, status: value.status } : current))
      }
      if (packet.type === 'CHAT_ACTION') {
        const action = packet.data as ChatAction
        if (!action.active || action.action === 'cancel') {
          setChatActions(current => {
            if (!current[action.chat_id]) return current
            const next = { ...current }
            delete next[action.chat_id]
            return next
          })
        } else {
          const listExpiresAt = Date.now() + 6000
          setChatActions(current => ({ ...current, [action.chat_id]: { ...action, expires_at: listExpiresAt } }))
          window.setTimeout(() => {
            setChatActions(current => {
              if (current[action.chat_id]?.expires_at !== listExpiresAt) return current
              const next = { ...current }
              delete next[action.chat_id]
              return next
            })
          }, 6100)
        }
        if (selectedChatIdRef.current === action.chat_id) {
          if (chatActionTimerRef.current !== null) {
            window.clearTimeout(chatActionTimerRef.current)
            chatActionTimerRef.current = null
          }
          if (!action.active || action.action === 'cancel') {
            setSelectedChatAction(null)
          } else {
            const expiresAt = Date.now() + 6000
            setSelectedChatAction({ ...action, expires_at: expiresAt })
            chatActionTimerRef.current = window.setTimeout(() => {
              setSelectedChatAction(current => (
                current && current.expires_at === expiresAt ? null : current
              ))
              chatActionTimerRef.current = null
            }, 6100)
          }
        }
      }
      if (packet.type === 'MESSAGES_READ') {
        const receipt = packet.data as ReadReceipt
        if (!isPopoutWindow) setDialogs(current => current.map(item => (
          item.chat_id === receipt.chat_id && item.last_message_outgoing && (item.last_message_id || 0) <= receipt.max_id
            ? { ...item, last_message_read: true }
            : item
        )))
        if (selectedChatIdRef.current === receipt.chat_id) {
          setMessages(current => current.map(item => (
            item.outgoing && item.message_id <= receipt.max_id
              ? { ...item, read: true }
              : item
          )))
        }
      }
      if (packet.type === 'MESSAGE_DELETED') {
        const deleted = packet.data as { chat_id: number | null; message_id: number }
        const openChat = selectedChatIdRef.current
        if (openChat !== null && (deleted.chat_id === openChat || (deleted.chat_id === null && !isChannelId(openChat)))) {
          setMessages(current => current.filter(item => item.message_id !== deleted.message_id))
          setPinnedMessage(current => current?.message_id === deleted.message_id ? null : current)
          setReplyingTo(current => current?.message_id === deleted.message_id ? null : current)
          setEditing(current => current?.message_id === deleted.message_id ? null : current)
        }
      }
    }

    void hydrateCachedDialogs()
    void refreshSnapshot()
    connectSocket()
    return () => {
      disposed = true
      if (retryTimer !== undefined) window.clearTimeout(retryTimer)
      if (flushTimer !== undefined) window.clearTimeout(flushTimer)
      socket?.close()
    }
  }, [])

  useEffect(() => {
    if (!selected) {
      setMessages([])
      setHasOlder(false)
      setHasNewer(false)
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
      clearPendingAttachments()
      setMediaPanel(null)
      setDragActive(false)
      setReactionPickerFor(null)
      setMessageContextMenu(null)
      setSelectedMessageIds(new Set())
      setSelectedChatAction(null)
      return
    }

    const chatId = selected.chat_id
    const unreadCount = selected.unread_count
    const controller = new AbortController()
    let remoteHistoryApplied = false
    const isCurrentChat = () => !controller.signal.aborted && selectedChatIdRef.current === chatId

    setMessages([])
    setHasOlder(false)
    setHasNewer(false)
    setChatInfo(null)
    setPinnedMessage(null)
    setUnreadBoundaryId(null)
    setShowJumpToBottom(false)
    setNewBelowCount(0)
    stickToBottomRef.current = true
    setReplyingTo(null)
    setEditing(null)
    setDraft(draftsRef.current[String(chatId)] || '')
    setMessageSearchOpen(false)
    setMessageQuery('')
    setSearchResults([])
    setSearchPerformed(false)
    setForwarding(null)
    setForwardQuery('')
    setBulkBusy(null)
    clearPendingAttachments()
    setMediaPanel(null)
    setDragActive(false)
    setReactionPickerFor(null)
    setMessageContextMenu(null)
    setSelectedMessageIds(new Set())
    setSelectedChatAction(null)

    api<Message[]>('/api/cache/chats/' + chatId + '/messages?limit=' + HISTORY_PAGE_SIZE, { signal: controller.signal })
      .then(items => {
        if (!isCurrentChat() || remoteHistoryApplied || !items.length) return
        const visibleItems = items.filter(item => !item.deleted)
        setMessages(visibleItems)
        setHasOlder(items.length === HISTORY_PAGE_SIZE)
        window.requestAnimationFrame(() => {
          if (isCurrentChat() && !remoteHistoryApplied) scrollToBottom('auto')
        })
      })
      .catch(() => undefined)

    if (!status?.authorized) {
      return () => controller.abort()
    }

    api<ChatInfo>('/api/telegram/chats/' + chatId, { signal: controller.signal })
      .then(info => {
        if (isCurrentChat()) setChatInfo(info)
      })
      .catch(error => {
        if (error instanceof DOMException && error.name === 'AbortError') return
        if (isCurrentChat()) setChatInfo(null)
      })

    api<Message | null>('/api/telegram/chats/' + chatId + '/pinned', { signal: controller.signal })
      .then(message => {
        if (isCurrentChat()) setPinnedMessage(message)
      })
      .catch(error => {
        if (error instanceof DOMException && error.name === 'AbortError') return
        if (isCurrentChat()) setPinnedMessage(null)
      })

    api<Message[]>('/api/telegram/chats/' + chatId + '/messages?limit=' + HISTORY_PAGE_SIZE, { signal: controller.signal })
      .then(items => {
        if (!isCurrentChat()) return
        remoteHistoryApplied = true
        const visibleItems = items.filter(item => !item.deleted)
        setMessages(visibleItems)
        setHasOlder(items.length === HISTORY_PAGE_SIZE)
        setHasNewer(false)
        const incoming = items.filter(item => !item.outgoing && !item.deleted)
        const unreadIndex = Math.max(0, incoming.length - unreadCount)
        setUnreadBoundaryId(unreadCount > 0 && incoming.length > 0 ? incoming[unreadIndex].message_id : null)
        window.requestAnimationFrame(() => {
          if (isCurrentChat()) scrollToBottom('auto')
        })
      })
      .catch(error => {
        if (error instanceof DOMException && error.name === 'AbortError') return
        if (isCurrentChat()) setError(errorMessage(error, 'تاریخچه این گفتگو دریافت نشد.'))
      })

    api<{ chat_id: number; read: boolean }>('/api/telegram/chats/' + chatId + '/read', {
      method: 'POST',
      signal: controller.signal
    })
      .then(() => {
        setDialogs(current => current.map(item => item.chat_id === chatId ? { ...item, unread_count: 0 } : item))
        if (isCurrentChat()) {
          setSelected(current => current && current.chat_id === chatId ? { ...current, unread_count: 0 } : current)
        }
      })
      .catch(() => undefined)

    return () => controller.abort()
  }, [selected?.chat_id, status?.authorized])

  useEffect(() => {
    if (!selected || editing) return
    if (draftSwitchRef.current === selected.chat_id) {
      draftSwitchRef.current = null
      return
    }
    draftsRef.current = updateDraftMap(draftsRef.current, selected.chat_id, draft)
    window.localStorage.setItem(instanceStorageKey(DRAFT_STORAGE_KEY), JSON.stringify(draftsRef.current))
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
      } else if (mediaPanel) {
        setMediaPanel(null)
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
    mediaPanel,
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

  function beginSidebarResize(event: ReactMouseEvent<HTMLDivElement>) {
    event.preventDefault()
    sidebarResizeCleanupRef.current?.()
    sidebarResizeRef.current = { startX: event.clientX, startWidth: sidebarWidth }
    let latestWidth = sidebarWidth

    const handleMove = (moveEvent: MouseEvent) => {
      const resize = sidebarResizeRef.current
      if (!resize) return
      const maxWidth = Math.min(420, Math.max(250, window.innerWidth - 280))
      const nextWidth = Math.max(250, Math.min(maxWidth, resize.startWidth + (moveEvent.clientX - resize.startX)))
      latestWidth = nextWidth
      setSidebarWidth(nextWidth)
    }

    const cleanup = () => {
      window.removeEventListener('mousemove', handleMove)
      window.removeEventListener('mouseup', handleUp)
      document.body.classList.remove('sidebar-resizing')
      sidebarResizeRef.current = null
      if (sidebarResizeCleanupRef.current === cleanup) {
        sidebarResizeCleanupRef.current = null
      }
    }

    const handleUp = () => {
      window.localStorage.setItem(instanceStorageKey('telegram-sidebar-width'), String(latestWidth))
      cleanup()
    }

    sidebarResizeCleanupRef.current = cleanup
    document.body.classList.add('sidebar-resizing')
    window.addEventListener('mousemove', handleMove)
    window.addEventListener('mouseup', handleUp)
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
      window.localStorage.setItem(instanceStorageKey('telegram-notifications'), '0')
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
      window.localStorage.setItem(instanceStorageKey('telegram-notifications'), enabled ? '1' : '0')
      setNotificationsEnabled(enabled)
      if (!enabled) setError('مجوز اعلان دسکتاپ صادر نشد.')
    } catch {
      setError('فعال‌کردن اعلان دسکتاپ در این محیط انجام نشد.')
    }
  }

  async function updateDialogState(
    action: 'pin' | 'archive' | 'mute' | 'priority',
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

  async function openDialogInNewWindow(dialog: Dialog) {
    setDialogContextMenu(null)
    try {
      await invoke('open_chat_window', {
        chatId: dialog.chat_id,
        title: dialog.title
      })
    } catch (caught) {
      setError(errorMessage(caught, 'باز کردن گفتگو در پنجره جدا انجام نشد.'))
    }
  }

  const openDialog = useCallback((dialog: Dialog) => {
    const currentChatId = selectedChatIdRef.current
    if (currentChatId === dialog.chat_id) return
    if (currentChatId !== null && !editingRef.current) {
      draftsRef.current = updateDraftMap(draftsRef.current, currentChatId, liveDraftRef.current)
      window.localStorage.setItem(instanceStorageKey(DRAFT_STORAGE_KEY), JSON.stringify(draftsRef.current))
    }
    draftSwitchRef.current = dialog.chat_id
    setSelected(dialog)
  }, [])

  const openDialogContextMenu = useCallback((event: ReactMouseEvent, dialog: Dialog) => {
    event.preventDefault()
    event.stopPropagation()
    setDialogContextMenu({ dialog, x: event.clientX, y: event.clientY })
  }, [])

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
    if (!window.confirm(formatNumber(selectedMessages.length) + ' پیام برای همه حذف شود؟')) return

    setBulkBusy('delete')
    try {
      for (const message of selectedMessages) {
        await api<{ chat_id: number; message_id: number; deleted: boolean }>(
          '/api/telegram/chats/' + message.chat_id + '/messages/' + message.message_id + '/delete',
          { method: 'POST' }
        )
      }
      const deletedIds = new Set(selectedMessages.map(message => message.message_id))
      setMessages(current => current.filter(message => !deletedIds.has(message.message_id)))
      setSelectedMessageIds(new Set())
    } catch (caught) {
      setError(errorMessage(caught, 'حذف گروهی پیام‌ها کامل نشد.'))
    } finally {
      setBulkBusy(null)
    }
  }

  async function refreshDialogs() {
    try {
      const nextDialogs = await api<Dialog[]>('/api/telegram/dialogs?force=true')
      setDialogs(nextDialogs)
      const nextFolders = await api<DialogFolder[]>('/api/telegram/dialog-folders')
      setTelegramFolders(nextFolders)
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
      if (selectedChatIdRef.current !== selected.chat_id) return
      setMessages(current => {
        const known = new Set(current.map(item => item.message_id))
        const merged = [...older.filter(item => !item.deleted && !known.has(item.message_id)), ...current]
        if (merged.length <= MAX_LOADED_MESSAGES) return merged
        setHasNewer(true)
        return merged.slice(0, MAX_LOADED_MESSAGES)
      })
      setHasOlder(older.length === HISTORY_PAGE_SIZE)
      window.requestAnimationFrame(() => {
        if (!viewport || selectedChatIdRef.current !== selected.chat_id) return
        viewport.scrollTop = previousTop + viewport.scrollHeight - previousHeight
      })
    } catch (caught) {
      setError(errorMessage(caught, 'پیام‌های قدیمی‌تر دریافت نشد.'))
    } finally {
      setLoadingOlder(false)
    }
  }

  async function loadLatest() {
    if (!selected || !hasNewer) return
    const chatId = selected.chat_id
    try {
      const latest = await api<Message[]>(
        '/api/telegram/chats/' + chatId + '/messages?limit=' + HISTORY_PAGE_SIZE
      )
      if (selectedChatIdRef.current !== chatId) return
      setMessages(latest.filter(item => !item.deleted))
      setHasOlder(latest.length === HISTORY_PAGE_SIZE)
      setHasNewer(false)
      setUnreadBoundaryId(null)
      window.requestAnimationFrame(() => {
        if (selectedChatIdRef.current === chatId) scrollToBottom('auto')
      })
    } catch (caught) {
      if (selectedChatIdRef.current === chatId) {
        setError(errorMessage(caught, 'بازگشت به پیام‌های جدید انجام نشد.'))
      }
    }
  }

  async function refreshAuthorizedState() {
    const nextStatus = await api<Status>('/api/telegram/status')
    setStatus(nextStatus)
    if (nextStatus.authorized && !isPopoutWindow) {
      void Promise.allSettled([
        api<Dialog[]>('/api/telegram/dialogs').then(setDialogs),
        api<DialogFolder[]>('/api/telegram/dialog-folders').then(setTelegramFolders)
      ])
    }
  }

  async function recoverLoginResponse(): Promise<boolean> {
    // A lost response must never trigger another code/password submission.
    for (let attempt = 0; attempt < 4; attempt += 1) {
      if (attempt) await new Promise(resolve => window.setTimeout(resolve, 300))
      try {
        const latest = await api<Status>('/api/telegram/status')
        setStatus(latest)
        if (latest.authorized) {
          setError('')
          return true
        }
      } catch { /* The local backend may briefly be reconnecting. */ }
    }
    return false
  }

  async function importSession() {
    setImporting(true)
    setError('')
    try {
      const nextStatus = await api<Status>('/api/telegram/session/import', { method: 'POST' })
      setStatus(nextStatus)
      if (nextStatus.authorized) {
        const [nextDialogs, nextFolders] = await Promise.all([
          api<Dialog[]>('/api/telegram/dialogs'),
          api<DialogFolder[]>('/api/telegram/dialog-folders')
        ])
        setDialogs(nextDialogs)
        setTelegramFolders(nextFolders)
      }
    } catch (caught) {
      setError(errorMessage(caught, 'انتقال سشن انجام نشد؛ تنظیمات مسیر یا فایل منبع را بررسی کنید.'))
    } finally {
      setImporting(false)
    }
  }

  async function saveRuntimeConfig(event: FormEvent) {
    event.preventDefault()
    const apiId = Number(apiIdDraft.trim())
    const apiHash = apiHashDraft.trim()
    if (!Number.isInteger(apiId) || apiId < 1 || apiHash.length < 16) {
      setError('API ID یا API Hash معتبر نیست.')
      return
    }

    setRuntimeConfigBusy(true)
    setError('')
    try {
      if (proxyLinkDraft.trim()) {
        const added = await api<{ index: number }>('/api/telegram/transport/add-link', {
          method: 'POST',
          body: JSON.stringify({ link: proxyLinkDraft.trim() })
        })
        await api('/api/telegram/transport/select', {
          method: 'POST',
          body: JSON.stringify({ index: added.index })
        })
      }

      const nextStatus = await api<Status>('/api/telegram/runtime-config', {
        method: 'POST',
        body: JSON.stringify({ api_id: apiId, api_hash: apiHash })
      })
      setStatus(nextStatus)
      if (nextStatus.authorized) {
        const [nextDialogs, nextFolders] = await Promise.all([
          api<Dialog[]>('/api/telegram/dialogs'),
          api<DialogFolder[]>('/api/telegram/dialog-folders')
        ])
        setDialogs(nextDialogs)
        setTelegramFolders(nextFolders)
      }
    } catch (caught) {
      setError(errorMessage(caught, 'ذخیره تنظیمات و اتصال انجام نشد.'))
    } finally {
      setRuntimeConfigBusy(false)
    }
  }

  async function addProxyFromAuth(event: FormEvent) {
    event.preventDefault()
    const link = proxyLinkDraft.trim()
    if (!link) {
      setError('لینک پراکسی را وارد کنید.')
      return
    }

    setProxyBusy(true)
    setError('')
    try {
      const added = await api<{ index: number }>('/api/telegram/transport/add-link', {
        method: 'POST',
        body: JSON.stringify({ link })
      })
      await api('/api/telegram/transport/select', {
        method: 'POST',
        body: JSON.stringify({ index: added.index })
      })
      setStatus(await api<Status>('/api/telegram/status'))
      setProxyLinkDraft('')
      setShowProxyAdd(false)
      setShowAuthProxyManager(false)
      setAuthNotice('پراکسی ذخیره شد؛ اتصال در پس‌زمینه بررسی می‌شود.')
      void refreshProxySettings()
    } catch (caught) {
      setError(errorMessage(caught, 'پراکسی اضافه نشد.'))
    } finally {
      setProxyBusy(false)
    }
  }

  async function sendCode(event: FormEvent) {
    event.preventDefault()
    const value = phone.trim() ? countryCode + phone.replace(/\D/g, '') : ''
    if (!value) {
      setError('شماره تلفن را وارد کنید.')
      return
    }
    await requestCode(value)
  }

  async function requestCode(value: string) {
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
    // Auto-submit at 5 digits plus a click on "Next" must not send twice.
    if (verifyInFlightRef.current) return
    if (!code.trim()) {
      setError('کد تأیید را وارد کنید.')
      return
    }
    setAuthBusy(true)
    verifyInFlightRef.current = true
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
      if (!await recoverLoginResponse()) setError(errorMessage(caught, 'تأیید کد انجام نشد.'))
    } finally {
      verifyInFlightRef.current = false
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
      if (!await recoverLoginResponse()) setError(errorMessage(caught, 'تأیید رمز دومرحله‌ای انجام نشد.'))
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

  function updatePreferences(values: Partial<ClientPreferences>) {
    setPreferences(current => ({ ...current, ...values }))
  }

  async function refreshProxySettings() {
    const transport = await api<TransportStatus>('/api/telegram/transport')
    setTransportStatus(transport)
    void api<ProxyProbe[]>('/api/telegram/transport/probe')
      .then(setProxyProbes)
      .catch(() => undefined)
  }

  async function openProxySettings() {
    setMainMenuOpen(false)
    setProxySettingsOpen(true)
    setProxyBusy(true)
    setError('')
    try {
      await refreshProxySettings()
    } catch (caught) {
      setError(errorMessage(caught, 'وضعیت پراکسی دریافت نشد.'))
    } finally {
      setProxyBusy(false)
    }
  }

  async function selectProxy(index: number | null) {
    if (proxyBusy) return
    setProxyBusy(true)
    setError('')
    try {
      await api('/api/telegram/transport/select', {
        method: 'POST',
        body: JSON.stringify({ index })
      })
      const nextStatus = await api<Status>('/api/telegram/status')
      setStatus(nextStatus)
      await refreshProxySettings()
    } catch (caught) {
      setError(errorMessage(caught, 'تغییر پراکسی انجام نشد.'))
    } finally {
      setProxyBusy(false)
    }
  }

  async function addProxyLink(link: string) {
    const value = link.trim()
    if (!value || proxyBusy) return
    setProxyBusy(true)
    setError('')
    try {
      const added = await api<{ index: number }>('/api/telegram/transport/add-link', {
        method: 'POST',
        body: JSON.stringify({ link: value })
      })
      await api('/api/telegram/transport/select', {
        method: 'POST',
        body: JSON.stringify({ index: added.index })
      })
      setStatus(await api<Status>('/api/telegram/status'))
      setProxySettingsOpen(true)
      setShowProxyAdd(false)
      setProxyLinkDraft('')
      await refreshProxySettings()
      setProxyBusy(false)
    } catch (caught) {
      setError(errorMessage(caught, 'لینک پراکسی معتبر نیست یا اضافه نشد.'))
      setProxyBusy(false)
    }
  }

  function openLink(url: string) {
    if ('__TAURI_INTERNALS__' in window) {
      invoke('open_external', { url }).catch(() => setError('باز کردن لینک انجام نشد.'))
    } else {
      window.open(url, '_blank', 'noopener')
    }
  }

  async function openSettings() {
    setMainMenuOpen(false)
    setSettingsOpen(true)
    setSettingsBusy(true)
    try {
      const [transport, devices] = await Promise.all([
        api<TransportStatus>('/api/telegram/transport'),
        api<DeviceSession[]>('/api/telegram/devices'),
      ])
      setTransportStatus(transport)
      setDeviceSessions(devices)
    } catch (caught) {
      setError(errorMessage(caught, 'وضعیت مسیر اتصال دریافت نشد.'))
    } finally {
      setSettingsBusy(false)
    }
  }

  async function loadRelayChannels() {
    const [sources, destinations] = await Promise.all([
      api<RelayChannel[]>('/api/telegram/relay/source-channels'),
      api<RelayChannel[]>('/api/telegram/relay/destination-channels'),
    ])
    setRelaySources(sources)
    setRelayDestinations(destinations)
  }

  async function refreshRelay() {
    const [nextStatus, mappings] = await Promise.all([
      api<RelayStatus>('/api/telegram/relay/status'),
      api<RelayMapping[]>('/api/telegram/relay/mappings'),
    ])
    setRelayStatus(nextStatus)
    setRelayMappings(mappings)
    if (nextStatus.authorized) await loadRelayChannels()
  }

  async function openRelay() {
    setMainMenuOpen(false)
    setSettingsOpen(false)
    setRelayOpen(true)
    setRelayError('')
    setRelayBusy(true)
    try {
      await refreshRelay()
    } catch (caught) {
      setRelayError(errorMessage(caught, 'وضعیت انتقال دریافت نشد.'))
    } finally {
      setRelayBusy(false)
    }
  }

  async function relaySendCode(event: FormEvent) {
    event.preventDefault()
    setRelayBusy(true)
    setRelayError('')
    try {
      await api<AuthResponse>('/api/telegram/relay/auth/send-code', {
        method: 'POST', body: JSON.stringify({ phone: relayPhone.trim() }),
      })
      setRelayAuthStep('code')
    } catch (caught) {
      setRelayError(errorMessage(caught, 'ارسال کد اکانت دوم انجام نشد.'))
    } finally {
      setRelayBusy(false)
    }
  }

  async function relayVerify(event: FormEvent) {
    event.preventDefault()
    setRelayBusy(true)
    setRelayError('')
    try {
      const passwordStep = relayAuthStep === 'password'
      const result = await api<AuthResponse>(
        '/api/telegram/relay/auth/' + (passwordStep ? 'verify-password' : 'verify-code'),
        { method: 'POST', body: JSON.stringify(passwordStep ? { password: relayPassword } : { code: relayCode.trim() }) },
      )
      if (result.requires_2fa) setRelayAuthStep('password')
      if (result.authorized) {
        setRelayCode('')
        setRelayPassword('')
        await refreshRelay()
      }
    } catch (caught) {
      // The sign-in RPC can succeed even if its HTTP response was lost.
      try {
        const latest = await api<RelayStatus>('/api/telegram/relay/status')
        if (latest.authorized) {
          await refreshRelay()
          setRelayCode('')
          setRelayPassword('')
          return
        }
      } catch { /* Keep the original login error. */ }
      setRelayError(errorMessage(caught, 'ورود اکانت دوم انجام نشد.'))
    } finally {
      setRelayBusy(false)
    }
  }

  async function addRelayMapping(event: FormEvent) {
    event.preventDefault()
    if (!relaySourceDraft || !relayDestinationDraft) return
    setRelayBusy(true)
    setRelayError('')
    try {
      await api<RelayMapping>('/api/telegram/relay/mappings', {
        method: 'POST',
        body: JSON.stringify({
          source_chat_id: Number(relaySourceDraft),
          destination_chat_id: Number(relayDestinationDraft),
        }),
      })
      setRelayMappings(await api<RelayMapping[]>('/api/telegram/relay/mappings'))
      setRelayAddOpen(false)
      setRelaySourceDraft('')
      setRelayDestinationDraft('')
    } catch (caught) {
      setRelayError(errorMessage(caught, 'افزودن انتقال انجام نشد.'))
    } finally {
      setRelayBusy(false)
    }
  }

  async function removeRelayMapping(id: number) {
    if (!window.confirm('این انتقال حذف شود؟')) return
    setRelayBusy(true)
    try {
      await api('/api/telegram/relay/mappings/' + id, { method: 'DELETE' })
      setRelayMappings(current => current.filter(item => item.id !== id))
    } catch (caught) {
      setRelayError(errorMessage(caught, 'حذف انتقال انجام نشد.'))
    } finally {
      setRelayBusy(false)
    }
  }

  async function retryRelayFailed() {
    setRelayBusy(true)
    try {
      await api('/api/telegram/relay/retry-failed', { method: 'POST' })
      setRelayStatus(await api<RelayStatus>('/api/telegram/relay/status'))
    } catch (caught) {
      setRelayError(errorMessage(caught, 'تلاش دوباره انجام نشد.'))
    } finally {
      setRelayBusy(false)
    }
  }

  async function logoutRelayAccount() {
    if (!window.confirm('از اکانت دوم خارج شوید؟ نگاشت‌های انتقال هم پاک می‌شوند.')) return
    setRelayBusy(true)
    try {
      setRelayStatus(await api<RelayStatus>('/api/telegram/relay/auth/logout', { method: 'POST' }))
      setRelayMappings([])
      setRelaySources([])
      setRelayDestinations([])
      setRelayAuthStep('phone')
    } catch (caught) {
      setRelayError(errorMessage(caught, 'خروج از اکانت دوم انجام نشد.'))
    } finally {
      setRelayBusy(false)
    }
  }

  const pendingLoginRef = useRef<string | null | undefined>(undefined)
  useEffect(() => {
    if (!status || status.authorized || status.state !== 'AUTH_REQUIRED' || !('__TAURI_INTERNALS__' in window)) return
    if (pendingLoginRef.current !== undefined) return
    pendingLoginRef.current = null
    invoke<string | null>('take_pending_login').then(value => {
      if (!value) return
      const digits = value.replace(/\D/g, '')
      const code = Object.keys(COUNTRY_NAMES).filter(item => digits.startsWith(item.slice(1))).sort((a, b) => b.length - a.length)[0]
      if (code) {
        setCountryCode(code)
        setPhone(digits.slice(code.length - 1))
      }
      void requestCode('+' + digits)
    }).catch(() => undefined)
  }, [status?.state, status?.authorized])

  useEffect(() => {
    if (!mainMenuOpen || !('__TAURI_INTERNALS__' in window)) return
    invoke<Array<[string, string, boolean]>>('list_instances').then(setInstances).catch(() => setInstances([]))
  }, [mainMenuOpen])

  async function addAccount(event: FormEvent) {
    event.preventDefault()
    const digits = newAccountName.replace(/\D/g, '').replace(/^0+/, '')
    if (digits.length < 6 || addAccountBusy) {
      setAddAccountError('شماره تلفن را کامل وارد کنید.')
      return
    }
    const fullPhone = newAccountCountry + digits
    setAddAccountBusy(true)
    setAddAccountError('')
    try {
      // A separate copy of the app for this account, opened at the code step.
      await invoke('add_instance', { name: 'Telegram ' + fullPhone, phone: fullPhone })
      setAddAccountOpen(false)
      setNewAccountName('')
    } catch (caught) {
      setAddAccountError(typeof caught === 'string' ? caught : errorMessage(caught, 'ساخت حساب جدید انجام نشد.'))
    } finally {
      setAddAccountBusy(false)
    }
  }

  async function openCalls() {
    setMainMenuOpen(false)
    setCalls(null)
    setCallsOpen(true)
    try {
      setCalls(await api<CallEntry[]>('/api/telegram/calls'))
    } catch (caught) {
      setCalls([])
      setError(errorMessage(caught, 'فهرست تماس‌ها دریافت نشد.'))
    }
  }

  async function openUsername(username: string) {
    setMainMenuOpen(false)
    try {
      const dialog = await api<Dialog>('/api/telegram/resolve/' + encodeURIComponent(username))
      if (!dialogsRef.current.some(item => item.chat_id === dialog.chat_id)) setDialogs(current => [dialog, ...current])
      openDialog(dialog)
    } catch (caught) {
      setError(errorMessage(caught, 'باز کردن کانال انجام نشد.'))
    }
  }

  async function openContacts() {
    setMainMenuOpen(false)
    setContactsQuery('')
    setContactsOpen(true)
    try {
      setContacts(await api<ContactInfo[]>('/api/telegram/contacts'))
    } catch (caught) {
      setContacts([])
      setError(errorMessage(caught, 'فهرست مخاطبین دریافت نشد.'))
    }
  }

  function openContact(contact: ContactInfo) {
    setContactsOpen(false)
    const existing = dialogsRef.current.find(item => item.chat_id === contact.chat_id)
    if (existing) {
      openDialog(existing)
      return
    }
    const dialog: Dialog = {
      chat_id: contact.chat_id,
      title: contact.title,
      dialog_type: 'user',
      username: contact.username,
      unread_count: 0,
      pinned: false,
      archived: false,
      muted: false
    }
    setDialogs(current => [dialog, ...current])
    openDialog(dialog)
  }

  function openCreateChat(kind: 'group' | 'channel') {
    setMainMenuOpen(false)
    setCreateTitle('')
    setCreateAbout('')
    setCreateKind(kind)
  }

  async function submitCreateChat(event: FormEvent) {
    event.preventDefault()
    if (!createKind || createBusy || !createTitle.trim()) return
    setCreateBusy(true)
    try {
      const dialog = await api<Dialog>('/api/telegram/chats/create', {
        method: 'POST',
        body: JSON.stringify({ title: createTitle.trim(), kind: createKind, about: createAbout.trim() })
      })
      setDialogs(current => [dialog, ...current.filter(item => item.chat_id !== dialog.chat_id)])
      setCreateKind(null)
      openDialog(dialog)
    } catch (caught) {
      setError(errorMessage(caught, createKind === 'group' ? 'ساخت گروه انجام نشد.' : 'ساخت کانال انجام نشد.'))
    } finally {
      setCreateBusy(false)
    }
  }

  function menuUnavailable(label: string) {
    setMainMenuOpen(false)
    setError(label + ' در نسخهٔ فعلی هنوز فعال نشده است.')
  }

  function openSelfChat() {
    const selfDialog = dialogs.find(item => item.chat_id === status?.user_id)
    setMainMenuOpen(false)
    if (selfDialog) {
      void openDialog(selfDialog)
    } else {
      setError('گفت‌وگوی پیام‌های ذخیره‌شده در فهرست فعلی پیدا نشد.')
    }
  }

  async function logoutAccount() {
    if (logoutBusy) return
    if (!window.confirm('از حساب این برنامه خارج شوید؟ فقط سشن مستقل حذف می‌شود و سشن داشبورد دست‌نخورده می‌ماند.')) return
    setLogoutBusy(true)
    setError('')
    try {
      const nextStatus = await api<Status>('/api/telegram/auth/logout', { method: 'POST' })
      setStatus(nextStatus)
      setDialogs([])
      setSelected(null)
      setSettingsOpen(false)
      resetAuth()
    } catch (caught) {
      setError(errorMessage(caught, 'خروج امن از حساب انجام نشد.'))
    } finally {
      setLogoutBusy(false)
    }
  }

  function mediaKey(message: Message) {
    return message.chat_id + ':' + message.message_id
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
      const response = await backendFetch(chatPath(message.chat_id) + '/messages/' + message.message_id + '/media?download=true')
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
    const chatId = selected.chat_id
    const value = messageQuery.trim()
    if (value.length < 2) {
      setError('برای جست‌وجو حداقل دو حرف وارد کنید.')
      return
    }

    setSearchBusy(true)
    setSearchPerformed(false)
    try {
      const results = await api<Message[]>(
        '/api/telegram/chats/' + chatId + '/search?q=' + encodeURIComponent(value) + '&limit=50'
      )
      if (selectedChatIdRef.current !== chatId) return
      setSearchResults(results)
      setSearchPerformed(true)
    } catch (caught) {
      if (selectedChatIdRef.current === chatId) {
        setError(errorMessage(caught, 'جست‌وجوی پیام انجام نشد.'))
      }
    } finally {
      if (selectedChatIdRef.current === chatId) setSearchBusy(false)
    }
  }

  function openSearchResult(message: Message) {
    setMessages(current => (
      current.some(item => item.message_id === message.message_id)
        ? current
        : upsertSortedMessage(current, message)
    ))
    if (searchJumpTimerRef.current !== null) window.clearTimeout(searchJumpTimerRef.current)
    searchJumpTimerRef.current = window.setTimeout(() => {
      jumpToMessage(message.message_id)
      searchJumpTimerRef.current = null
    }, 0)
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
    clearPendingAttachments()
    setMediaPanel(null)
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
    if (focusTimerRef.current !== null) window.clearTimeout(focusTimerRef.current)
    focusTimerRef.current = window.setTimeout(() => {
      element.classList.remove('message-focus')
      focusTimerRef.current = null
    }, 1400)
  }

  function openPinnedMessage() {
    if (!pinnedMessage) return
    setMessages(current => (
      current.some(item => item.message_id === pinnedMessage.message_id)
        ? current
        : upsertSortedMessage(current, pinnedMessage)
    ))
    window.requestAnimationFrame(() => jumpToMessage(pinnedMessage.message_id))
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
      setMessages(current => current.filter(item => item.message_id !== message.message_id))
      setPinnedMessage(current => current?.message_id === message.message_id ? null : current)
      setReplyingTo(current => current?.message_id === message.message_id ? null : current)
      if (editing?.message_id === message.message_id) cancelComposerContext()
    } catch (caught) {
      setError(errorMessage(caught, 'حذف پیام انجام نشد.'))
    } finally {
      setMessageActionBusy(null)
    }
  }

  function clearPendingAttachments() {
    setPendingAttachments(current => {
      for (const item of current) {
        if (item.previewUrl) URL.revokeObjectURL(item.previewUrl)
      }
      return []
    })
  }

  function removePendingAttachment(id: string) {
    setPendingAttachments(current => {
      const removed = current.find(item => item.id === id)
      if (removed?.previewUrl) URL.revokeObjectURL(removed.previewUrl)
      return current.filter(item => item.id !== id)
    })
  }

  function queueFiles(values: File[] | FileList) {
    if (uploadBusy || editing) return
    const incoming = Array.from(values)
    if (!incoming.length) return
    const invalid = incoming.find(file => file.size === 0 || file.size > 2 * 1024 * 1024 * 1024)
    if (invalid) {
      setError(invalid.size === 0
        ? 'فایل خالی قابل ارسال نیست.'
        : 'حجم هر فایل نمی‌تواند بیشتر از ۲ گیگابایت باشد.')
      return
    }

    setPendingAttachments(current => {
      const available = 10 - current.length
      if (incoming.length > available) {
        setError('در هر آلبوم حداکثر ۱۰ فایل قابل ارسال است.')
      }
      return [
        ...current,
        ...incoming.slice(0, Math.max(available, 0)).map(file => ({
          id: crypto.randomUUID(),
          file,
          previewUrl: file.type.startsWith('image/') ? URL.createObjectURL(file) : null
        }))
      ]
    })
    setMediaPanel(null)
    setDragActive(false)
  }

  function handleComposerPaste(event: ClipboardEvent<HTMLInputElement>) {
    const files = event.clipboardData.files
    if (!files.length) return
    event.preventDefault()
    queueFiles(files)
  }

  function handleChatDrag(event: DragEvent<HTMLElement>) {
    if (!selected || editing || uploadBusy || !event.dataTransfer.types.includes('Files')) return
    event.preventDefault()
    event.dataTransfer.dropEffect = 'copy'
    setDragActive(true)
  }

  function handleChatDrop(event: DragEvent<HTMLElement>) {
    event.preventDefault()
    setDragActive(false)
    if (!event.dataTransfer.files.length) return
    queueFiles(event.dataTransfer.files)
  }

  async function uploadPendingFiles() {
    if (!selected || !pendingAttachments.length || uploadBusy || editing) return false
    const chatId = selected.chat_id
    const form = new FormData()
    for (const item of pendingAttachments) form.append('files', item.file, item.file.name)
    if (draft.trim()) form.append('caption', draft.trim())
    if (replyingTo) form.append('reply_to_message_id', String(replyingTo.message_id))

    setUploadBusy(true)
    setUploadName(
      pendingAttachments.length === 1
        ? pendingAttachments[0].file.name
        : formatNumber(pendingAttachments.length) + ' فایل'
    )
    setError('')
    try {
      const response = await backendFetch(chatPath(chatId) + '/files/album', {
        method: 'POST',
        body: form
      })
      if (!response.ok) {
        const body = await response.text()
        let detail = body || 'ارسال فایل‌ها انجام نشد.'
        try {
          const parsed = JSON.parse(body) as { detail?: string }
          if (parsed.detail) detail = parsed.detail
        } catch {
          // Keep the plain response body when the backend did not return JSON.
        }
        throw new Error(detail)
      }

      const sent = await response.json() as Message[]
      if (selectedChatIdRef.current === chatId) {
        setMessages(current => {
          const sentIds = new Set(sent.map(message => message.message_id))
          return [
            ...current.filter(message => !sentIds.has(message.message_id)),
            ...sent
          ].sort((left, right) => left.message_id - right.message_id)
        })
        clearPendingAttachments()
        setDraft('')
        setReplyingTo(null)
      }
      return true
    } catch (caught) {
      setError(errorMessage(caught, 'ارسال فایل‌ها انجام نشد.'))
      return false
    } finally {
      setUploadBusy(false)
      setUploadName('')
      if (fileInputRef.current) fileInputRef.current.value = ''
    }
  }

  function insertEmoji(emoji: string) {
    const input = composerInputRef.current
    const start = input?.selectionStart ?? draft.length
    const end = input?.selectionEnd ?? start
    const next = draft.slice(0, start) + emoji + draft.slice(end)
    setDraft(next)
    window.requestAnimationFrame(() => {
      input?.focus()
      input?.setSelectionRange(start + emoji.length, start + emoji.length)
    })
  }

  async function openMediaPanel(kind: 'emoji' | 'sticker' | 'gif') {
    setMediaPanel(current => current === kind ? null : kind)
    if (kind === 'emoji' || recentMedia || recentMediaBusy) return
    setRecentMediaBusy(true)
    try {
      setRecentMedia(await api<RecentMediaCatalog>('/api/telegram/media/recent'))
    } catch (caught) {
      setError(errorMessage(caught, 'استیکرها و GIFهای اخیر دریافت نشدند.'))
    } finally {
      setRecentMediaBusy(false)
    }
  }

  async function sendRecentMedia(item: RecentMediaItem) {
    if (!selected || recentMediaSending !== null || editing) return
    const chatId = selected.chat_id
    const key = item.kind + ':' + item.media_id
    setRecentMediaSending(key)
    setError('')
    try {
      const message = await api<Message>(
        '/api/telegram/chats/' + chatId + '/media/recent/' + item.kind + '/' + encodeURIComponent(item.media_id),
        {
          method: 'POST',
          body: JSON.stringify({
            caption: item.kind === 'gif' ? draft.trim() : '',
            reply_to_message_id: replyingTo?.message_id || null
          })
        }
      )
      if (selectedChatIdRef.current === chatId) {
        setMessages(current => [
          ...current.filter(value => value.message_id !== message.message_id),
          message
        ].sort((left, right) => left.message_id - right.message_id))
        if (item.kind === 'gif') setDraft('')
        setReplyingTo(null)
        setMediaPanel(null)
      }
    } catch (caught) {
      setError(errorMessage(caught, 'ارسال رسانه اخیر انجام نشد.'))
    } finally {
      setRecentMediaSending(null)
    }
  }

  async function closeApplication() {
    try {
      await invoke('close_current_window')
    } catch {
      await appWindow?.close()
    }
  }

  async function sendMessage(event: FormEvent) {
    event.preventDefault()
    const text = draft.trim()
    if (!selected || (!text && !pendingAttachments.length) || composerBusy) return

    if (!editing && pendingAttachments.length) {
      await uploadPendingFiles()
      return
    }

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

  const showCachedWorkspace = canShowCachedWorkspace(status, dialogs.length)
  if (!status || (shouldHoldAuthScreen(status) && !showCachedWorkspace)) {
    return <div className="loading-screen">در حال راه‌اندازی تلگرام…</div>
  }

  const loginMode = status.state !== 'UNCONFIGURED' && status.state !== 'PROXY_ERROR' && !showAuthProxyManager
  const loginTitle = authStep === 'phone'
    ? 'شماره تلفن شما'
    : authStep === 'code'
      ? countryCode + ' ' + phone
      : 'رمز ابری'
  const loginLead = authStep === 'phone'
    ? 'لطفاً کد کشور را تأیید و شماره تلفن خود را وارد کنید.'
    : authStep === 'code'
      ? 'کد ورود را به اپ تلگرام روی دستگاه دیگرتان فرستادیم.'
      : 'حساب شما با یک رمز اضافه محافظت می‌شود.'

  if (!status.authorized && !showCachedWorkspace) {
    return (
      <div className={'auth-screen' + (loginMode ? ' tg-login' : '')}>
        <div className={'auth-card' + (status.state === 'PROXY_ERROR' ? ' proxy-recovery-card' : '')}>
          <div className="brand-mark tg-login-logo"><span className="paper-plane" aria-hidden="true" /></div>
          {loginMode ? (
            <>
              <h1>{loginTitle}</h1>
              <p className="tg-login-lead">{loginLead}</p>
              {status.state === 'CONNECTING' && <small className="tg-login-connecting">در حال اتصال…</small>}
            </>
          ) : (
            <>
              <h1>Telegram Desktop</h1>
              <span className="status-pill">{statusLabel(status.state)}</span>
              {status.last_error && <small className="auth-error">{status.last_error}</small>}
            </>
          )}

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
            <form className="auth-form setup-form" onSubmit={saveRuntimeConfig}>
              <p className="muted">سشن آماده است. فقط اطلاعات API را یک‌بار وارد کنید.</p>
              <label className="auth-field">
                <span>API ID</span>
                <input
                  value={apiIdDraft}
                  onChange={event => setApiIdDraft(event.target.value.replace(/\D/g, ''))}
                  placeholder="12345678"
                  inputMode="numeric"
                  dir="ltr"
                  autoFocus
                />
              </label>
              <label className="auth-field">
                <span>API Hash</span>
                <input
                  value={apiHashDraft}
                  onChange={event => setApiHashDraft(event.target.value.trim())}
                  placeholder="0123456789abcdef..."
                  dir="ltr"
                  autoComplete="off"
                />
              </label>
              <label className="auth-field">
                <span>Proxy Link <small>(اختیاری)</small></span>
                <input
                  value={proxyLinkDraft}
                  onChange={event => setProxyLinkDraft(event.target.value)}
                  placeholder="tg://proxy?... or vless://..."
                  dir="ltr"
                  autoComplete="off"
                />
              </label>
              <button className="primary-action auth-submit" type="submit" disabled={runtimeConfigBusy}>
                {runtimeConfigBusy ? 'در حال اتصال…' : 'ذخیره و اتصال'}
              </button>
            </form>
          ) : (status.state === 'PROXY_ERROR' || showAuthProxyManager) ? (
            <section className="auth-proxy-manager">
              <div className="auth-proxy-title">
                <div>
                  <strong>Proxy Settings</strong>
                  <small>یک مسیر را انتخاب کنید؛ پینگ‌ها هر ۵ ثانیه تازه می‌شوند.</small>
                </div>
                <button
                  className="proxy-refresh-button"
                  type="button"
                  disabled={proxyBusy}
                  onClick={() => void refreshProxySettings()}
                  title="Refresh ping"
                >↻</button>
              </div>

              <div className="session-health-card">
                <span className={status.session_auth_key_present ? 'session-health-dot ok' : 'session-health-dot bad'} />
                <div>
                  <strong>Telegram Session</strong>
                  <small>
                    {status.session_auth_key_present
                      ? 'Auth key loaded'
                        + (status.session_dc_id ? ' · DC ' + status.session_dc_id : '')
                        + (status.session_auth_key_bytes ? ' · ' + status.session_auth_key_bytes + ' bytes' : '')
                        + (status.runtime_session_cloned ? ' · runtime clone ready' : '')
                      : 'Auth key not found in client.session'}
                  </small>
                </div>
              </div>

              <div className="auth-proxy-list">
                <button className="auth-proxy-row" type="button" disabled={proxyBusy} onClick={() => void selectProxy(null)}>
                  <span className={'proxy-radio ' + (!transportStatus?.routes.some(route => route.selected) && status.active_route !== 'direct' ? 'selected' : '')} />
                  <span className="auth-proxy-copy">
                    <strong>Automatic</strong>
                    <small>Try available proxy routes automatically</small>
                  </span>
                </button>

                <button className="auth-proxy-row" type="button" disabled={proxyBusy} onClick={() => void selectProxy(0)}>
                  <span className={'proxy-radio ' + (status.active_route === 'direct' ? 'selected' : '')} />
                  <span className="auth-proxy-copy">
                    <strong>Direct connection</strong>
                    <small>{transportStatus?.allow_direct ? 'Available as fallback' : 'May be blocked on this network'}</small>
                  </span>
                </button>

                <button className="auth-proxy-row add" type="button" onClick={() => setShowProxyAdd(value => !value)}>
                  <span className="proxy-plus">＋</span>
                  <span className="auth-proxy-copy">
                    <strong>Add Proxy</strong>
                    <small>MTProto, SOCKS or VLESS/V2Ray link</small>
                  </span>
                </button>

                {showProxyAdd && (
                  <form className="auth-proxy-add" onSubmit={addProxyFromAuth}>
                    <input
                      value={proxyLinkDraft}
                      onChange={event => setProxyLinkDraft(event.target.value)}
                      placeholder="https://t.me/proxy?... or vless://..."
                      dir="ltr"
                      autoComplete="off"
                      autoFocus
                    />
                    <button type="submit" disabled={proxyBusy || !proxyLinkDraft.trim()}>
                      {proxyBusy ? '…' : 'Add'}
                    </button>
                  </form>
                )}
              </div>

              <div className="auth-proxy-section-title">
                <span>Connections</span>
                <small>{transportStatus?.routes.length || 0}</small>
              </div>

              <div className="auth-proxy-connections">
                {transportStatus?.routes.map(route => {
                  const probe = proxyProbes.find(item => item.index === route.index)
                  return (
                    <button
                      className={'auth-proxy-row route' + (route.selected ? ' selected-route' : '')}
                      type="button"
                      key={route.index}
                      disabled={proxyBusy}
                      onClick={() => void selectProxy(route.index)}
                    >
                      <span className={'proxy-radio ' + (route.selected ? 'selected' : '')} />
                      <span className="auth-proxy-copy">
                        <strong dir="ltr">{route.name}</strong>
                        <small dir="ltr">{route.type} · {route.host}:{route.port}</small>
                      </span>
                      <span className={'auth-proxy-ping ' + (probe?.available ? 'ok' : probe ? 'bad' : 'checking')}>
                        {probe?.active
                          ? 'Connected'
                          : probe?.available
                            ? (probe.latency_ms != null ? Math.round(probe.latency_ms) + ' ms' : 'Available')
                            : probe
                              ? 'Unavailable'
                              : 'Checking…'}
                      </span>
                    </button>
                  )
                })}
                {!transportStatus?.routes.length && (
                  <div className="auth-proxy-empty">پراکسی ذخیره‌شده‌ای پیدا نشد. از «Add Proxy» اضافه کنید.</div>
                )}
              </div>

              <div className="auth-proxy-footer">
                <button type="button" onClick={() => { setShowProxyAdd(false); setShowAuthProxyManager(false) }}>بازگشت به ورود با شماره</button>
                <button type="button" disabled={proxyBusy} onClick={() => void selectProxy(null)}>
                  {proxyBusy ? 'در حال اتصال…' : 'تلاش مجدد با همه مسیرها'}
                </button>
              </div>
            </section>
          ) : (
            <form className="auth-form" onSubmit={authStep === 'phone' ? sendCode : authStep === 'code' ? verifyCode : verifyPassword}>
              {authStep === 'phone' && (
                <>
                  <div className="tg-login-country" dir="ltr">
                    <span>{countryName(countryCode)}</span>
                  </div>
                  <div className="tg-login-phone" dir="ltr">
                    <input
                      className="tg-login-code"
                      value={countryCode}
                      onChange={event => setCountryCode('+' + event.target.value.replace(/\D/g, '').slice(0, 4))}
                      inputMode="numeric"
                      aria-label="کد کشور"
                    />
                    <input
                      value={phone}
                      onChange={event => {
                        const raw = event.target.value.trim()
                        if (raw.startsWith('+')) {
                          // Full international number pasted: split off the country code.
                          const digits = raw.replace(/\D/g, '')
                          const code = Object.keys(COUNTRY_NAMES)
                            .filter(item => digits.startsWith(item.slice(1)))
                            .sort((a, b) => b.length - a.length)[0]
                          if (code) {
                            setCountryCode(code)
                            setPhone(digits.slice(code.length - 1))
                            return
                          }
                        }
                        // Local format (0918...) drops the trunk zero, as Telegram does.
                        setPhone(event.target.value.replace(/[^\d ]/g, '').replace(/^0+/, ''))
                      }}
                      placeholder="--- --- ----"
                      inputMode="tel"
                      autoComplete="tel-national"
                      aria-label="شماره تلفن"
                      autoFocus
                    />
                  </div>
                </>
              )}

              {authStep === 'code' && (
                <input
                  className="tg-login-single"
                  value={code}
                  onChange={event => {
                    const value = event.target.value.replace(/\D/g, '').slice(0, 6)
                    setCode(value)
                    // Telegram submits on its own once the 5-digit code is in.
                    if (value.length === 5 && !authBusy) window.setTimeout(() => event.target.form?.requestSubmit(), 0)
                  }}
                  placeholder="کد"
                  inputMode="numeric"
                  autoComplete="one-time-code"
                  dir="ltr"
                  autoFocus
                />
              )}

              {authStep === 'password' && (
                <input
                  className="tg-login-single"
                  value={password}
                  onChange={event => setPassword(event.target.value)}
                  type="password"
                  placeholder="رمز عبور"
                  autoComplete="current-password"
                  dir="ltr"
                  autoFocus
                />
              )}

              {error && <small className="tg-login-error">{error}</small>}

              <button className="tg-login-next" type="submit" disabled={authBusy}>
                {authBusy ? <span className="tg-login-spinner" aria-label="در حال انجام" /> : 'بعدی'}
              </button>
              {authStep !== 'phone' && (
                <button className="tg-login-link" type="button" onClick={resetAuth}>
                  {authStep === 'code' ? 'شماره اشتباه است؟' : 'شروع دوباره'}
                </button>
              )}
            </form>
          )}
        </div>
        {error && !loginMode && <button className="error-toast" onClick={() => setError('')}>{error}</button>}
        {loginMode && (
          <button
            type="button"
            className={'tg-login-proxy' + (status.active_route && status.active_route !== 'direct' ? ' active' : '')}
            onClick={() => {
              setShowProxyAdd(false)
              setShowAuthProxyManager(true)
            }}
            title="Proxy Settings"
            aria-label="تنظیمات پراکسی"
          >
            <span className="proxy-shield-icon" aria-hidden="true" />
          </button>
        )}
      </div>
    )
  }

  return (
    <main className={'telegram-shell' + (preferences.compact ? ' compact-mode' : '') + (isPopoutWindow ? ' popout-mode' : '')} style={{ '--sidebar-width': sidebarWidth + 'px' } as React.CSSProperties} onMouseDown={() => { setMessageContextMenu(null); setDialogContextMenu(null) }}>
      <header className="app-titlebar" data-tauri-drag-region>
        <div className={'titlebar-brand' + (isPopoutWindow ? ' popout-titlebar-brand' : '')} data-tauri-drag-region>
          {isPopoutWindow && selected ? (
            <>
              <ChatAvatar chatId={selected.chat_id} title={selected.title} className="popout-title-avatar" />
              <span className="popout-title-copy" data-tauri-drag-region>
                <strong dir="auto">{chatInfo?.title || selected.title}</strong>
                <small dir="auto">
                  {chatInfo?.participants_count != null
                    ? formatNumber(chatInfo.participants_count) + ' عضو'
                    : presenceLabel(chatInfo?.status) || dialogTypeLabel(chatInfo?.dialog_type || selected.dialog_type)}
                </small>
              </span>
            </>
          ) : (
            <>
              <button className="titlebar-menu" aria-label="منوی اصلی" title="منوی اصلی" onClick={() => setMainMenuOpen(value => !value)}>☰</button>
              <span className="account-stack" aria-hidden="true"><i /><i /></span>
              <span className="telegram-logo" aria-hidden="true">➤</span>
              <strong className="app-title">Telegram</strong>
            </>
          )}
        </div>
        <div className="titlebar-drag-fill" data-tauri-drag-region aria-hidden="true" />
        <div className="window-controls">
          <button aria-label="کمینه" onClick={() => void appWindow?.minimize()}>—</button>
          <button aria-label="بیشینه" onClick={() => void appWindow?.toggleMaximize()}>□</button>
          <button className="window-close" aria-label="بستن" onClick={() => void closeApplication()}>×</button>
        </div>
      </header>
      {mainMenuOpen && (
        <div className="main-menu-backdrop" onMouseDown={() => setMainMenuOpen(false)}>
          <nav className="main-menu-drawer" aria-label="منوی اصلی تلگرام" onMouseDown={event => event.stopPropagation()}>
            <section className="menu-account">
              <ChatAvatar chatId={status.user_id || 0} title={status.display_name || 'Telegram'} className="menu-profile-photo" />
              <button className="menu-night" type="button" aria-label="حالت شب" onClick={() => updatePreferences({ theme: preferences.theme === 'dark' ? 'light' : 'dark' })}>☾</button>
              <strong>{status.display_name || 'Telegram'}</strong>
              <small dir="ltr">{status.phone ? '+' + status.phone : 'Telegram account'}</small>
            </section>
            <button className="menu-item menu-current-account" type="button" onClick={() => setMainMenuOpen(false)}>
              <ChatAvatar chatId={status.user_id || 0} title={status.display_name || 'Telegram'} className="menu-small-avatar" />
              <span>{status.display_name || 'Telegram'}</span>
              {totalUnread > 0 && <b className="menu-badge">{formatCompact(totalUnread)}</b>}
            </button>
            <hr />
            {instances.filter(item => !item[2]).map(([name, path]) => (
              <button className="menu-item menu-current-account" type="button" key={path} onClick={() => {
                setMainMenuOpen(false)
                invoke('open_instance', { path }).catch(() => setError('باز کردن این حساب انجام نشد.'))
              }}>
                <span className="avatar menu-small-avatar" style={{ background: '#8e99a4' }}><span className="avatar-fallback">{Array.from(name)[0]}</span></span>
                <span>{name}</span>
              </button>
            ))}
            <button className="menu-item" type="button" onClick={() => { setMainMenuOpen(false); setAddAccountOpen(true) }}><Icon name="addAccount" /><span>Add Account</span></button>
            <hr />
            <button className="menu-item" type="button" onClick={openSelfChat}><Icon name="saved" /><span>Saved Messages</span></button>
            <button className="menu-item" type="button" onClick={() => void openSettings()}><Icon name="account" /><span>My Profile</span></button>
            <hr />
            <button className="menu-item" type="button" onClick={() => openCreateChat('group')}><Icon name="group" /><span>New Group</span></button>
            <button className="menu-item" type="button" onClick={() => openCreateChat('channel')}><Icon name="channel" /><span>New Channel</span></button>
            <button className="menu-item" type="button" onClick={() => setMainMenuOpen(false)}><Icon name="chats" /><span>Chats</span></button>
            <button className="menu-item" type="button" onClick={() => void openContacts()}><Icon name="contacts" /><span>Contacts</span></button>
            <button className="menu-item" type="button" onClick={() => void openCalls()}><Icon name="calls" /><span>Calls</span></button>
            <button className="menu-item" type="button" onClick={() => void openSettings()}><Icon name="settings" /><span>Settings</span></button>
            <hr />
            <button className="menu-item" type="button" onClick={() => { setMainMenuOpen(false); openLink('https://telegram.org/tour') }}><Icon name="help" /><span>Telegram Features</span></button>
            <button className="menu-item" type="button" onClick={() => void openUsername('telegram')}><Icon name="channel" /><span>News</span></button>
          </nav>
        </div>
      )}
      <aside className="chat-sidebar">
        <div className="search-row">
          <div className="search-box">
            <input value={query} onChange={event => setQuery(event.target.value)} placeholder="Search" />
            <button type="button" aria-label="به‌روزرسانی گفتگوها" title="به‌روزرسانی" onClick={refreshDialogs}>✎</button>
          </div>
          <button
            className={'sidebar-tool proxy-tool ' + (status.active_route && status.active_route !== 'direct' ? 'active' : '')}
            aria-label="تنظیمات پراکسی"
            title="Proxy Settings"
            onClick={() => void openProxySettings()}
          ><span className="proxy-shield-icon" aria-hidden="true" /></button>
        </div>
        <div className="folder-tabs">
          <button className={activeFolder === 'all' ? 'active' : ''} onClick={() => setActiveFolder('all')}>All Chats{dialogs.some(item => !item.archived && item.unread_count > 0) && <b>{dialogs.filter(item => !item.archived && item.unread_count > 0).length}</b>}</button>
          {telegramFolders.map(folder => {
            const key = ('folder:' + folder.id) as FolderKey
            return (
              <button key={folder.id} className={activeFolder === key ? 'active' : ''} onClick={() => setActiveFolder(key)}>
                {folder.title}{folder.unread_count > 0 && <b>{folder.unread_count}</b>}
              </button>
            )
          })}
        </div>
        <div className="dialog-list">
          {visibleDialogs.map(dialog => {
            const action = chatActions[dialog.chat_id]
            const typing = action
              ? (isGroupType(dialog.dialog_type) && action.user_name ? firstName(action.user_name) + ' ' : '') + chatActionLabel(action.action)
              : null
            return (
              <DialogRow
                key={dialog.chat_id}
                dialog={dialog}
                selected={selected?.chat_id === dialog.chat_id}
                typing={typing}
                actions={dialogActions}
              />
            )
          })}
          {!visibleDialogs.length && <div className="empty-list">گفت‌وگویی پیدا نشد</div>}
        </div>
      </aside>
      {dialogContextMenu && (
        <div
          className="dialog-context-menu"
          style={{ left: dialogContextMenu.x, top: dialogContextMenu.y }}
          onMouseDown={event => event.stopPropagation()}
        >
          <button type="button" onClick={() => void openDialogInNewWindow(dialogContextMenu.dialog)}>
            <Icon name="window" />
            Open in New Window
          </button>
        </div>
      )}
      <div className="sidebar-resizer" onMouseDown={beginSidebarResize} aria-hidden="true" />

      <section
        className={'chat-panel' + (dragActive ? ' drag-active' : '')}
        onDragEnter={handleChatDrag}
        onDragOver={handleChatDrag}
        onDragLeave={event => {
          if (!event.currentTarget.contains(event.relatedTarget as Node | null)) setDragActive(false)
        }}
        onDrop={handleChatDrop}
      >
        {dragActive && selected && (
          <div className="drop-overlay" aria-hidden="true">
            <strong>فایل‌ها را اینجا رها کنید</strong>
            <small>حداکثر ۱۰ فایل در یک آلبوم</small>
          </div>
        )}
        {selected ? (
          <>
            <header className="chat-header">
              <ChatAvatar chatId={selected.chat_id} title={selected.title} className="large" />
              <div>
                <strong>{selected.title}</strong>
                {selectedChatAction ? (
                  <small className="chat-action-live">
                    <span className="typing-dots" aria-hidden="true"><i /><i /><i /></span>
                    {(selected.dialog_type !== 'user' && selectedChatAction.user_name ? firstName(selectedChatAction.user_name) + ' is ' : '')
                      + ({ typing: 'typing', uploading: 'sending a file', recording: 'recording', cancel: '' } as Record<string, string>)[selectedChatAction.action]}
                  </small>
                ) : (
                  <small>{headerStatus(selected, chatInfo)}</small>
                )}
              </div>
              <div className="header-actions">
                <button className={'icon-button ' + (messageSearchOpen ? 'active' : '')} aria-label="جست‌وجوی پیام" onClick={toggleMessageSearch}><Icon name="search" /></button>
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
                      <Icon name="pin" />{selected.pinned ? 'برداشتن سنجاق گفتگو' : 'سنجاق‌کردن گفتگو'}
                    </button>
                    <button
                      type="button"
                      onClick={() => updateDialogState('mute', !selected.muted)}
                      disabled={dialogActionBusy !== null}
                    >
                      <Icon name="mute" />{selected.muted ? 'فعال‌کردن اعلان گفتگو' : 'بی‌صداکردن گفتگو'}
                    </button>
                    <button
                      type="button"
                      onClick={() => updateDialogState('archive', !selected.archived)}
                      disabled={dialogActionBusy !== null}
                    >
                      <Icon name="archive" />{selected.archived ? 'خارج‌کردن از آرشیو' : 'انتقال به آرشیو'}
                    </button>
                    <button
                      type="button"
                      onClick={() => updateDialogState('priority', !selected.priority)}
                      disabled={dialogActionBusy !== null}
                    >
                      <Icon name="bolt" />{selected.priority ? 'برداشتن اولویت لفظ' : 'اولویت لفظ (تحویل سریع‌تر)'}
                    </button>
                  </div>
                )}
              </div>
            </header>
            {selectedMessageIds.size > 0 && (
              <div className="selection-toolbar">
                <strong>{formatNumber(selectedMessageIds.size)} پیام انتخاب شده</strong>
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
                <span className="pinned-mark" aria-hidden="true" />
                <span>
                  <strong>Pinned Message</strong>
                  <small dir="auto">{messageSnippet(pinnedMessage)}</small>
                </span>
              </button>
            )}
            <div className="message-list" ref={messageListRef} onScroll={handleMessageScroll}>
              {hasOlder && (
                <button className="older-button" onClick={loadOlder} disabled={loadingOlder}>
                  {loadingOlder ? 'در حال دریافت…' : 'پیام‌های قدیمی‌تر'}
                </button>
              )}
              {hasNewer && (
                <button className="newer-button" onClick={() => void loadLatest()}>
                  بازگشت به پیام‌های جدید
                </button>
              )}
              {messageNodes}
              {showJumpToBottom && (
                <button className="jump-bottom" type="button" onClick={() => scrollToBottom('smooth')} aria-label="رفتن به آخر گفتگو">
                  <span>↓</span>
                  {newBelowCount > 0 && <strong>{formatNumber(newBelowCount)}</strong>}
                </button>
              )}
            </div>
            {chatInfo && chatInfo.can_post === false ? (
              <div className="channel-bar">
                <button type="button" onClick={() => updateDialogState('mute', !selected.muted)} disabled={dialogActionBusy !== null}>
                  {selected.muted ? 'UNMUTE' : 'MUTE'}
                </button>
              </div>
            ) : (
            <div className="composer-shell">
              <input
                ref={fileInputRef}
                className="hidden-file-input"
                type="file"
                multiple
                onChange={event => {
                  if (event.target.files) queueFiles(event.target.files)
                  event.target.value = ''
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
              {pendingAttachments.length > 0 && !uploadBusy && (
                <div className="attachment-tray">
                  <div className="attachment-tray-header">
                    <strong>{formatNumber(pendingAttachments.length)} پیوست آماده ارسال</strong>
                    <button type="button" onClick={clearPendingAttachments}>حذف همه</button>
                  </div>
                  <div className="attachment-items">
                    {pendingAttachments.map(item => (
                      <div className="attachment-item" key={item.id} title={item.file.name}>
                        {item.previewUrl
                          ? <img src={item.previewUrl} alt="" />
                          : <span className="attachment-file-icon">▤</span>}
                        <span>{item.file.name}</span>
                        <small>{formatBytes(item.file.size)}</small>
                        <button type="button" aria-label={'حذف ' + item.file.name} onClick={() => removePendingAttachment(item.id)}>×</button>
                      </div>
                    ))}
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
              {mediaPanel && (
                <section className="composer-media-panel">
                  <nav>
                    <button type="button" className={mediaPanel === 'emoji' ? 'active' : ''} onClick={() => openMediaPanel('emoji')}>ایموجی</button>
                    <button type="button" className={mediaPanel === 'sticker' ? 'active' : ''} onClick={() => openMediaPanel('sticker')}>استیکر</button>
                    <button type="button" className={mediaPanel === 'gif' ? 'active' : ''} onClick={() => openMediaPanel('gif')}>GIF</button>
                    <button type="button" className="panel-close" aria-label="بستن پنل رسانه" onClick={() => setMediaPanel(null)}>×</button>
                  </nav>
                  {mediaPanel === 'emoji' ? (
                    <div className="emoji-grid">
                      {COMPOSER_EMOJIS.map(emoji => <button type="button" key={emoji} onClick={() => insertEmoji(emoji)}>{emoji}</button>)}
                    </div>
                  ) : recentMediaBusy ? (
                    <div className="media-panel-empty">در حال دریافت…</div>
                  ) : (
                    <div className="recent-media-grid">
                      {(mediaPanel === 'sticker' ? recentMedia?.stickers : recentMedia?.gifs)?.map(item => {
                        const key = item.kind + ':' + item.media_id
                        return (
                          <button type="button" key={key} onClick={() => sendRecentMedia(item)} disabled={recentMediaSending !== null} title={item.label}>
                            <strong>{recentMediaSending === key ? '…' : item.kind === 'sticker' ? item.label : 'GIF'}</strong>
                            <small>{item.label}</small>
                          </button>
                        )
                      })}
                      {!recentMediaBusy && !(mediaPanel === 'sticker' ? recentMedia?.stickers.length : recentMedia?.gifs.length) && (
                        <div className="media-panel-empty">مورد اخیری در تلگرام پیدا نشد.</div>
                      )}
                    </div>
                  )}
                </section>
              )}
              <form className="composer" ref={composerFormRef} onSubmit={sendMessage}>
                <div className="composer-input-shell">
                  <button
                    type="button"
                    className="composer-attach"
                    aria-label="ارسال عکس یا فایل"
                    title="پیوست"
                    onClick={() => fileInputRef.current?.click()}
                    disabled={uploadBusy || editing !== null}
                  >
                    <span className="paperclip-icon" aria-hidden="true" />
                  </button>
                  <input
                    ref={composerInputRef}
                    value={draft}
                    onChange={event => setDraft(event.target.value)}
                    onPaste={handleComposerPaste}
                    placeholder={editing ? 'ویرایش پیام...' : replyingTo ? 'کپشن یا پاسخ...' : 'Message'}
                    disabled={uploadBusy}
                  />
                  <button
                    type="button"
                    className={'composer-emoji' + (mediaPanel ? ' active' : '')}
                    aria-label="ایموجی، استیکر و GIF"
                    onClick={() => openMediaPanel(mediaPanel || 'emoji')}
                    disabled={uploadBusy || editing !== null}
                  >
                    ☺
                  </button>
                  <button
                    className={'send-button' + ((!draft.trim() && !pendingAttachments.length && !editing) ? ' voice-mode' : ' send-mode')}
                    type="submit"
                    aria-label={(!draft.trim() && !pendingAttachments.length && !editing) ? 'پیام صوتی' : 'ارسال'}
                    disabled={composerBusy || uploadBusy || (!draft.trim() && !pendingAttachments.length)}
                  >
                    <span className="composer-action-icon" aria-hidden="true" />
                  </button>
                </div>
              </form>
            </div>
            )}
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
                <div><span>اعضا</span><strong>{formatNumber(chatInfo.participants_count)}</strong></div>
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
          <button type="button" role="menuitem" onClick={() => beginReply(messageContextMenu.message)}><Icon name="reply" />پاسخ</button>
          <button
            type="button"
            role="menuitem"
            onClick={() => {
              setReactionPickerFor(messageContextMenu.message.message_id)
              setMessageContextMenu(null)
            }}
          >
            <Icon name="smile" />واکنش
          </button>
          <button type="button" role="menuitem" onClick={() => beginForward(messageContextMenu.message)}><Icon name="forward" />فوروارد</button>
          <button type="button" role="menuitem" onClick={() => copyMessages([messageContextMenu.message])}><Icon name="copy" />کپی متن</button>
          <button type="button" role="menuitem" onClick={() => toggleMessageSelection(messageContextMenu.message.message_id)}><Icon name="select" />انتخاب</button>
          {messageContextMenu.message.outgoing && messageContextMenu.message.text && !messageContextMenu.message.deleted && (
            <button type="button" role="menuitem" onClick={() => {
              beginEdit(messageContextMenu.message)
              setMessageContextMenu(null)
            }}><Icon name="edit" />ویرایش</button>
          )}
          {messageContextMenu.message.outgoing && !messageContextMenu.message.deleted && (
            <button type="button" role="menuitem" className="danger" onClick={() => {
              const message = messageContextMenu.message
              setMessageContextMenu(null)
              void deleteMessage(message)
            }}><Icon name="trash" />حذف</button>
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
                    : 'فوروارد ' + formatNumber(forwarding.length) + ' پیام'}
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

      {proxySettingsOpen && (
        <div className="proxy-settings-backdrop" onMouseDown={() => setProxySettingsOpen(false)}>
          <section className="proxy-settings-panel" role="dialog" aria-modal="true" aria-label="Proxy Settings" onMouseDown={event => event.stopPropagation()}>
            <header className="proxy-settings-header">
              <button type="button" aria-label="بازگشت" onClick={() => setProxySettingsOpen(false)}>‹</button>
              <strong>Proxy Settings</strong>
            </header>
            <div className="proxy-settings-scroll">
              <button className="proxy-choice" type="button" disabled={proxyBusy} onClick={() => void selectProxy(0)}>
                <span className={'proxy-radio ' + (transportStatus?.routes.every(route => !route.selected) && status.active_route === 'direct' ? 'selected' : '')} />
                <span>Disable Proxy</span>
              </button>
              <button className="proxy-choice disabled" type="button" disabled title="Telethon MTProto does not use Windows system proxy automatically">
                <span className="proxy-radio" />
                <span>Use System Proxy Settings</span>
                <small>Not available for MTProto</small>
              </button>
              <button className="proxy-choice add" type="button" onClick={() => setShowProxyAdd(value => !value)}>
                <span className="proxy-plus">＋</span>
                <span>Add Proxy</span>
              </button>
              {showProxyAdd && (
                <form className="proxy-add-form" onSubmit={event => { event.preventDefault(); void addProxyLink(proxyLinkDraft) }}>
                  <input
                    value={proxyLinkDraft}
                    onChange={event => setProxyLinkDraft(event.target.value)}
                    placeholder="tg://proxy?... or vless://..."
                    dir="ltr"
                    autoFocus
                  />
                  <button type="submit" disabled={proxyBusy || !proxyLinkDraft.trim()}>Add</button>
                </form>
              )}
              <h3>Connections</h3>
              <div className="proxy-connections">
                {transportStatus?.routes.map(route => {
                  const probe = proxyProbes.find(item => item.index === route.index)
                  return (
                    <button className="proxy-route" type="button" key={route.index} disabled={proxyBusy} onClick={() => void selectProxy(route.index)}>
                      <span className={'proxy-radio ' + (route.selected ? 'selected' : '')} />
                      <span className="proxy-route-copy">
                        <strong dir="ltr">{route.name}</strong>
                        <small className={probe?.available === false ? 'unavailable' : ''}>
                          {probe?.active
                            ? 'Connected'
                            : probe?.available
                              ? (probe.latency_ms != null ? 'Ping: ' + Math.round(probe.latency_ms) + ' ms' : 'Available')
                              : probe
                                ? 'Unavailable'
                                : 'Checking…'}
                          {route.managed_v2ray ? ' · V2Ray' : ''}
                        </small>
                      </span>
                    </button>
                  )
                })}
              </div>
            </div>
          </section>
        </div>
      )}

      {settingsOpen && (
        <div className="settings-backdrop" onMouseDown={() => setSettingsOpen(false)}>
          <section className="settings-modal" role="dialog" aria-modal="true" aria-label="تنظیمات برنامه" onMouseDown={event => event.stopPropagation()}>
            <header>
              <div>
                <strong>تنظیمات</strong>
                <small>حساب مستقل و تنظیمات همین دستگاه</small>
              </div>
              <button className="icon-button" type="button" aria-label="بستن تنظیمات" onClick={() => setSettingsOpen(false)}>×</button>
            </header>

            <div className="settings-scroll">
              <section className="settings-section">
                <h3>حساب تلگرام</h3>
                <div className="account-summary">
                  <span className="brand-mark small">✈</span>
                  <div>
                    <strong>{status.display_name || 'حساب تلگرام'}</strong>
                    <small>{status.connected ? 'متصل' : 'قطع'} · سشن مستقل {status.client_session_exists ? 'فعال' : 'ایجاد نشده'}</small>
                  </div>
                </div>
                <div className="safe-note">خروج فقط سشن مستقل این برنامه را حذف می‌کند؛ سشن و تنظیمات داشبورد فقط‌خواندنی و دست‌نخورده می‌مانند.</div>
                <button className="danger-action" type="button" onClick={logoutAccount} disabled={logoutBusy}>
                  {logoutBusy ? 'در حال خروج…' : 'خروج امن از حساب'}
                </button>
              </section>

              <section className="settings-section">
                <h3>Devices</h3>
                {settingsBusy ? (
                  <div className="settings-muted">در حال دریافت نشست‌های تلگرام…</div>
                ) : deviceSessions.length ? (
                  <div className="device-list">
                    {deviceSessions.map(device => (
                      <div className="device-card" key={device.hash}>
                        <span className="device-picture" aria-hidden="true"><i /><i /><i /><i /></span>
                        <div>
                          <strong>{device.device_model}</strong>
                          <span>{device.app_name}{device.app_version ? ' ' + device.app_version : ''}</span>
                          <small>{[device.region || device.country, device.current ? 'Online' : new Date(device.date_active).toLocaleString('en-US', { hour: 'numeric', minute: '2-digit' })].filter(Boolean).join(' · ')}</small>
                        </div>
                        {device.current && <b>Current</b>}
                      </div>
                    ))}
                  </div>
                ) : (
                  <div className="settings-muted">نشست فعالی گزارش نشده است.</div>
                )}
              </section>

              <section className="settings-section settings-proxy-shortcut" onClick={() => { setSettingsOpen(false); void openProxySettings() }}>
                <h3>اتصال و پراکسی</h3>
                {settingsBusy ? (
                  <div className="settings-muted">در حال دریافت وضعیت…</div>
                ) : (
                  <>
                    <div className="settings-row"><span>مسیر فعال</span><strong>{status.active_route || (transportStatus?.allow_direct ? 'اتصال مستقیم' : 'نامشخص')}</strong></div>
                    <div className="settings-row"><span>مسیرهای امن موجود</span><strong>{formatNumber(transportStatus?.routes.length || 0)}</strong></div>
                    {transportStatus?.routes.map(route => (
                      <div className="transport-row" key={route.index}>
                        <span>{route.name}{route.managed_v2ray ? ' · V2Ray' : ''}</span>
                        <small dir="ltr">{route.type} · {route.host}:{route.port}</small>
                      </div>
                    ))}
                  </>
                )}
              </section>

              <section className="settings-section">
                <h3>انتقال به اکانت دوم</h3>
                <div className="safe-note">اکانت دوم فقط برای ارسال به کانال‌های مقصد استفاده می‌شود؛ پیام‌های آن در این برنامه بارگیری نمی‌شوند.</div>
                <button className="relay-action" type="button" onClick={() => void openRelay()}>فوروارد خودکار / مدیریت اکانت دوم</button>
              </section>

              <section className="settings-section">
                <h3>ظاهر</h3>
                <label className="settings-select">
                  <span>پوسته</span>
                  <select value={preferences.theme} onChange={event => updatePreferences({ theme: event.target.value as ClientPreferences['theme'] })}>
                    <option value="system">مطابق ویندوز</option>
                    <option value="dark">تیره</option>
                    <option value="light">روشن</option>
                  </select>
                </label>
                <label className="settings-toggle">
                  <span><strong>حالت فشرده</strong><small>فاصله کمتر در فهرست گفتگوها و پیام‌ها</small></span>
                  <input type="checkbox" checked={preferences.compact} onChange={event => updatePreferences({ compact: event.target.checked })} />
                </label>
              </section>

              <section className="settings-section">
                <h3>رسانه و دانلود</h3>
                <label className="settings-toggle">
                  <span><strong>بارگیری خودکار تصاویر</strong><small>در حالت خاموش، هر تصویر فقط با انتخاب شما نمایش داده می‌شود.</small></span>
                  <input type="checkbox" checked={preferences.autoLoadPhotos} onChange={event => updatePreferences({ autoLoadPhotos: event.target.checked })} />
                </label>
                <div className="safe-note">ویدئو، پیام صوتی و موسیقی داخل گفتگو پخش می‌شوند. فایل‌ها فقط با دکمه دانلود ذخیره می‌شوند.</div>
              </section>
            </div>
          </section>
        </div>
      )}

      {relayOpen && (
        <div className="settings-backdrop" onMouseDown={() => setRelayOpen(false)}>
          <section className="settings-modal relay-modal" role="dialog" aria-modal="true" aria-label="انتقال کانال‌ها به اکانت دوم" onMouseDown={event => event.stopPropagation()}>
            <header>
              <div><strong>انتقال به اکانت دوم</strong><small>اکانت اول مبدأ · اکانت دوم فقط فرستنده</small></div>
              <button className="icon-button" type="button" aria-label="بستن انتقال" onClick={() => setRelayOpen(false)}>×</button>
            </header>
            <div className="settings-scroll">
              {relayError && <div className="relay-error" role="alert">{relayError}</div>}
              {relayBusy && !relayStatus ? <div className="settings-muted">در حال دریافت وضعیت…</div> : null}
              {relayStatus && !relayStatus.authorized ? (
                <section className="settings-section">
                  <h3>ورود اکانت دوم</h3>
                  <div className="safe-note">سشن این اکانت جداگانه روی همین دستگاه ذخیره می‌شود. شماره، کد و رمز را فقط اینجا وارد کنید.</div>
                  <form className="relay-form" onSubmit={relayAuthStep === 'phone' ? relaySendCode : relayVerify}>
                    {relayAuthStep === 'phone' && <label>شماره اکانت دوم<input type="tel" dir="ltr" autoComplete="tel" value={relayPhone} onChange={event => setRelayPhone(event.target.value)} required placeholder="+98…" /></label>}
                    {relayAuthStep === 'code' && <label>کد تأیید<input type="text" dir="ltr" autoComplete="one-time-code" value={relayCode} onChange={event => setRelayCode(event.target.value)} required /></label>}
                    {relayAuthStep === 'password' && <label>رمز دومرحله‌ای<input type="password" dir="ltr" autoComplete="current-password" value={relayPassword} onChange={event => setRelayPassword(event.target.value)} required /></label>}
                    <button className="relay-action" type="submit" disabled={relayBusy}>{relayBusy ? 'لطفاً صبر کنید…' : relayAuthStep === 'phone' ? 'دریافت کد' : 'تأیید و ورود'}</button>
                    {relayAuthStep !== 'phone' && <button type="button" className="relay-secondary" onClick={() => setRelayAuthStep('phone')}>تغییر شماره</button>}
                  </form>
                </section>
              ) : null}
              {relayStatus?.authorized && (
                <>
                  <section className="settings-section">
                    <h3>اکانت دوم: {relayStatus.display_name || 'متصل'}</h3>
                    <div className="safe-note">فقط پیام‌های جدید گروه‌ها یا کانال‌های انتخاب‌شده از اکانت اول به کانال مقصد ارسال می‌شوند. حذف پیام منتقل‌شده نیز وقتی تلگرام رویداد حذف را به برنامه برساند در مقصد اعمال می‌شود. پیام‌های قدیمی منتقل نمی‌شوند.</div>
                    <div className="relay-counts">در صف ارسال: {relayStatus.pending} · ارسال‌شده: {relayStatus.sent} · حذف‌شده در مقصد: {relayStatus.deleted} · در صف حذف: {relayStatus.delete_pending} · خطا: {relayStatus.failed + relayStatus.delete_failed} · مسدود: {relayStatus.blocked}</div>
                    {relayStatus.last_delivery_ms != null && <div className="relay-counts">زمان آخرین انتقال از دریافت رویداد تا تأیید ارسال: {relayStatus.last_delivery_ms} میلی‌ثانیه</div>}
                    {relayStatus.failed + relayStatus.delete_failed > 0 && <button type="button" className="relay-secondary" disabled={relayBusy} onClick={() => void retryRelayFailed()}>تلاش دوباره برای خطاها</button>}
                    <button type="button" className="relay-secondary" disabled={relayBusy} onClick={() => void refreshRelay().catch(caught => setRelayError(errorMessage(caught, 'بازخوانی انجام نشد.')))}>بازخوانی وضعیت و کانال‌ها</button>
                  </section>
                  <section className="settings-section">
                    <div className="relay-heading"><h3>انتقال‌ها</h3><button type="button" className="relay-plus" aria-label="افزودن انتقال" title="افزودن انتقال" onClick={() => setRelayAddOpen(true)}>+</button></div>
                    {!relayMappings.length && <div className="settings-muted">هنوز انتقالی ثبت نشده است. با + یک جفت کانال انتخاب کنید.</div>}
                    {relayMappings.map(mapping => <div className="relay-mapping" key={mapping.id}><span dir="auto">{mapping.source_title} ← {mapping.destination_title}</span><button type="button" disabled={relayBusy} aria-label={'حذف انتقال ' + mapping.source_title} onClick={() => void removeRelayMapping(mapping.id)}>×</button></div>)}
                    {relayAddOpen && <form className="relay-form" onSubmit={addRelayMapping}>
                      <label>گروه یا کانال مبدأ از اکانت اول<select value={relaySourceDraft} onChange={event => setRelaySourceDraft(event.target.value)} required><option value="">انتخاب گروه یا کانال مبدأ</option>{relaySources.map(channel => <option value={channel.chat_id} key={channel.chat_id}>{channel.dialog_type === 'channel' ? 'کانال' : 'گروه'} · {channel.title}</option>)}</select></label>
                      <label>کانال مقصد از اکانت دوم<select value={relayDestinationDraft} onChange={event => setRelayDestinationDraft(event.target.value)} required><option value="">انتخاب کانال مقصد</option>{relayDestinations.map(channel => <option value={channel.chat_id} key={channel.chat_id}>{channel.title}</option>)}</select></label>
                      <div className="relay-form-actions"><button className="relay-action" type="submit" disabled={relayBusy || !relaySourceDraft || !relayDestinationDraft}>ثبت انتقال</button><button className="relay-secondary" type="button" onClick={() => setRelayAddOpen(false)}>انصراف</button></div>
                    </form>}
                  </section>
                  <section className="settings-section"><button className="danger-action" type="button" disabled={relayBusy} onClick={() => void logoutRelayAccount()}>خروج از اکانت دوم و حذف انتقال‌ها</button></section>
                </>
              )}
            </div>
          </section>
        </div>
      )}

      {contactsOpen && (
        <div className="forward-backdrop" onMouseDown={() => setContactsOpen(false)}>
          <section className="forward-modal tg-panel" role="dialog" aria-modal="true" aria-label="Contacts" onMouseDown={event => event.stopPropagation()}>
            <header>
              <div><strong>Contacts</strong></div>
              <button className="icon-button" type="button" aria-label="بستن" onClick={() => setContactsOpen(false)}>×</button>
            </header>
            <input
              className="forward-search"
              value={contactsQuery}
              onChange={event => setContactsQuery(event.target.value)}
              placeholder="Search"
              autoFocus
            />
            <div className="forward-dialogs">
              {contacts === null && <div className="search-empty">در حال دریافت…</div>}
              {contacts?.filter(item => {
                const value = contactsQuery.trim().toLocaleLowerCase()
                return !value || item.title.toLocaleLowerCase().includes(value) || Boolean(item.username?.toLocaleLowerCase().includes(value)) || Boolean(item.phone?.includes(value))
              }).map(contact => (
                <button className="forward-dialog-row" type="button" key={contact.chat_id} onClick={() => openContact(contact)}>
                  <ChatAvatar chatId={contact.chat_id} title={contact.title} />
                  <span>
                    <strong>{contact.title}</strong>
                    <small>{presenceLabel(contact.status) || (contact.username ? '@' + contact.username : '')}</small>
                  </span>
                </button>
              ))}
              {contacts?.length === 0 && <div className="search-empty">مخاطبی پیدا نشد.</div>}
            </div>
          </section>
        </div>
      )}

      {callsOpen && (
        <div className="forward-backdrop" onMouseDown={() => setCallsOpen(false)}>
          <section className="forward-modal tg-panel" role="dialog" aria-modal="true" aria-label="Calls" onMouseDown={event => event.stopPropagation()}>
            <header>
              <div><strong>Calls</strong></div>
              <button className="icon-button" type="button" aria-label="بستن" onClick={() => setCallsOpen(false)}>×</button>
            </header>
            <div className="forward-dialogs">
              {calls === null && <div className="search-empty">در حال دریافت…</div>}
              {calls?.map((call, index) => (
                <button className="forward-dialog-row" type="button" key={index} onClick={() => {
                  setCallsOpen(false)
                  openContact({ chat_id: call.chat_id, title: call.title })
                }}>
                  <ChatAvatar chatId={call.chat_id} title={call.title} />
                  <span>
                    <strong className={call.missed ? 'call-missed' : ''}>{call.title}</strong>
                    <small>
                      {(call.outgoing ? '↗ ' : '↙ ') + (call.video ? 'Video · ' : '')}
                      {new Intl.DateTimeFormat('en-US', { month: 'short', day: 'numeric', hour: 'numeric', minute: '2-digit' }).format(new Date(call.date))}
                      {call.duration ? ' · ' + Math.floor(call.duration / 60) + ':' + String(call.duration % 60).padStart(2, '0') : call.missed ? ' · Missed' : ''}
                    </small>
                  </span>
                </button>
              ))}
              {calls?.length === 0 && <div className="search-empty">تماسی ثبت نشده است.</div>}
            </div>
          </section>
        </div>
      )}

      {addAccountOpen && (
        <div className="tg-add-account-screen auth-screen tg-login">
          <button className="tg-add-account-back" type="button" aria-label="بازگشت" onClick={() => !addAccountBusy && setAddAccountOpen(false)}>←</button>
          <div className="auth-card">
            <div className="brand-mark tg-login-logo"><span className="paper-plane" aria-hidden="true" /></div>
            <h1>Your Phone Number</h1>
            <p className="tg-login-lead">Please confirm your country code and enter your phone number.</p>
            <form className="auth-form" onSubmit={addAccount}>
              <div className="tg-login-country" dir="ltr"><span>{countryName(newAccountCountry)}</span></div>
              <div className="tg-login-phone" dir="ltr">
                <input
                  className="tg-login-code"
                  value={newAccountCountry}
                  onChange={event => setNewAccountCountry('+' + event.target.value.replace(/\D/g, '').slice(0, 4))}
                  inputMode="numeric"
                  aria-label="کد کشور"
                />
                <input
                  value={newAccountName}
                  onChange={event => setNewAccountName(event.target.value.replace(/[^\d ]/g, ''))}
                  placeholder="--- --- ----"
                  inputMode="tel"
                  aria-label="شماره تلفن"
                  autoFocus
                />
              </div>
              {addAccountError && <small className="tg-login-error">{addAccountError}</small>}
              <button className="tg-login-next" type="submit" disabled={addAccountBusy}>
                {addAccountBusy ? <span className="tg-login-spinner" aria-label="در حال آماده‌سازی" /> : 'NEXT'}
              </button>
              {addAccountBusy && <small className="tg-login-connecting">در حال آماده‌سازی حساب جدید… چند ثانیه صبر کنید</small>}
            </form>
          </div>
        </div>
      )}

      {createKind && (
        <div className="forward-backdrop" onMouseDown={() => !createBusy && setCreateKind(null)}>
          <form className="forward-modal tg-panel tg-create" role="dialog" aria-modal="true" onSubmit={submitCreateChat} onMouseDown={event => event.stopPropagation()}>
            <header>
              <div><strong>{createKind === 'group' ? 'New Group' : 'New Channel'}</strong></div>
              <button className="icon-button" type="button" aria-label="بستن" onClick={() => setCreateKind(null)} disabled={createBusy}>×</button>
            </header>
            <input
              className="tg-login-single"
              value={createTitle}
              onChange={event => setCreateTitle(event.target.value)}
              placeholder={createKind === 'group' ? 'Group name' : 'Channel name'}
              maxLength={128}
              autoFocus
            />
            {createKind === 'channel' && (
              <input
                className="tg-login-single"
                value={createAbout}
                onChange={event => setCreateAbout(event.target.value)}
                placeholder="Description (optional)"
                maxLength={255}
              />
            )}
            <button className="tg-login-next" type="submit" disabled={createBusy || !createTitle.trim()}>
              {createBusy ? <span className="tg-login-spinner" aria-label="در حال ساخت" /> : 'Create'}
            </button>
          </form>
        </div>
      )}

      {viewerMessage && (
        <MediaViewer message={viewerMessage} onClose={closeViewer} onDownload={message => void downloadMedia(message)} />
      )}

      {error && <button className="error-toast" onClick={() => setError('')}>{error}</button>}
    </main>
  )
}

export default App
