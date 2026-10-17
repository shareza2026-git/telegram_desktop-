import { Fragment, useCallback, useEffect, useMemo, useRef, useState, type ClipboardEvent, type DragEvent, type FormEvent, type MouseEvent as ReactMouseEvent } from 'react'
import { invoke } from '@tauri-apps/api/core'
import { getCurrentWindow } from '@tauri-apps/api/window'

import { api, apiBlob, authedUrl, backendBase, backendFetch, chatPath, socketBase } from './backend'
import { DialogRow, type DialogActions } from './DialogRow'
import { DRAFT_STORAGE_KEY, parseDraftMap, updateDraftMap } from './drafts'
import {
  chatActionLabel,
  dialogTypeLabel,
  errorMessage,
  formatBytes,
  formatMessageDate,
  formatNumber,
  formatTime,
  isChannelId,
  mediaKindLabel,
  messageDayKey,
  messageSnippet,
  presenceLabel,
  statusLabel
} from './format'
import { ChatAvatar, MediaViewer } from './media'
import { MessageBubble, type BubbleActions } from './MessageBubble'
import { buildMessageRows, mergeMessage } from './messageList'
import { PREFERENCES_STORAGE_KEY, parsePreferences, resolvedTheme, type ClientPreferences } from './preferences'
import type {
  AuthResponse,
  AuthStep,
  ChatAction,
  ChatInfo,
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

const HISTORY_PAGE_SIZE = 80
// Recently opened chats stay in memory so switching back is instant.
const CHAT_CACHE_LIMIT = 40
const COMPOSER_EMOJIS = [
  '😀', '😃', '😄', '😁', '😆', '😅', '😂', '🙂', '🙃', '😉',
  '😊', '😍', '🥰', '😘', '😎', '🤔', '😮', '😢', '😭', '😡',
  '👍', '👎', '👏', '🙏', '🤝', '💪', '❤️', '💔', '🔥', '✨',
  '🎉', '✅', '❌', '⚡', '💯', '👀', '📌', '📎', '🚀', '🌹'
]
// Null when the UI runs in a plain browser (vite dev without the Tauri shell).
const appWindow = '__TAURI_INTERNALS__' in window ? getCurrentWindow() : null
const startupParams = new URLSearchParams(window.location.search)
const popoutChatId = startupParams.get('popout') === '1'
  ? Number(startupParams.get('chat') || 0)
  : 0
const isPopoutWindow = Boolean(popoutChatId)

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

function isGroupType(value: string) {
  return value === 'group' || value === 'supergroup'
}

function firstName(value?: string | null) {
  return (value || '').trim().split(/\s+/)[0] || null
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
  const [sidebarWidth, setSidebarWidth] = useState(() => Number(window.localStorage.getItem('telegram-sidebar-width')) || 312)
  const sidebarResizeRef = useRef<{ startX: number; startWidth: number } | null>(null)
  const [loadingOlder, setLoadingOlder] = useState(false)
  const [hasOlder, setHasOlder] = useState(false)
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
  const [chatActions, setChatActions] = useState<Record<number, ChatAction>>({})
  const [viewerMessage, setViewerMessage] = useState<Message | null>(null)
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
  const [dialogContextMenu, setDialogContextMenu] = useState<DialogContextMenu | null>(null)
  const [selectedMessageIds, setSelectedMessageIds] = useState<Set<number>>(() => new Set())
  const [bulkBusy, setBulkBusy] = useState<'delete' | 'forward' | null>(null)
  const [settingsOpen, setSettingsOpen] = useState(false)
  const [proxySettingsOpen, setProxySettingsOpen] = useState(false)
  const [proxyProbes, setProxyProbes] = useState<ProxyProbe[]>([])
  const [proxyBusy, setProxyBusy] = useState(false)
  const [proxyLinkDraft, setProxyLinkDraft] = useState('')
  const [showProxyAdd, setShowProxyAdd] = useState(false)
  const [mainMenuOpen, setMainMenuOpen] = useState(false)
  const [transportStatus, setTransportStatus] = useState<TransportStatus | null>(null)
  const [deviceSessions, setDeviceSessions] = useState<DeviceSession[]>([])
  const [settingsBusy, setSettingsBusy] = useState(false)
  const [logoutBusy, setLogoutBusy] = useState(false)
  const [preferences, setPreferences] = useState<ClientPreferences>(() => (
    parsePreferences(window.localStorage.getItem(PREFERENCES_STORAGE_KEY))
  ))
  const [revealedPhotos, setRevealedPhotos] = useState<Set<string>>(() => new Set())
  const dialogsRef = useRef<Dialog[]>([])
  const notificationsEnabledRef = useRef(notificationsEnabled)
  const draftsRef = useRef(parseDraftMap(window.localStorage.getItem(DRAFT_STORAGE_KEY)))
  const draftSwitchRef = useRef<number | null>(null)
  const draftBeforeEditRef = useRef('')
  const pendingAttachmentsRef = useRef<PendingAttachment[]>([])
  const messagesRef = useRef<Message[]>([])
  const chatCacheRef = useRef(new Map<number, Message[]>())
  const dialogRefreshTimerRef = useRef<number | null>(null)
  const selectedChatAction = selected ? chatActions[selected.chat_id] || null : null

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

    const order = new Map(dialogs.map((item, index) => [item.chat_id, index]))
    const time = (item: Dialog) => (item.last_message_at ? Date.parse(item.last_message_at) : 0)
    return [...values].sort((a, b) => {
      if (a.pinned !== b.pinned) return a.pinned ? -1 : 1
      if (a.pinned) return (order.get(a.chat_id) || 0) - (order.get(b.chat_id) || 0)
      return time(b) - time(a)
    })
  }, [activeFolder, dialogs, query, telegramFolders])

  const messageRows = useMemo(() => buildMessageRows(messages), [messages])
  const messagesById = useMemo(() => new Map(messages.map(item => [item.message_id, item])), [messages])

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
    messagesRef.current = messages
    const chatId = messages.find(item => !item.pending)?.chat_id
    if (chatId === undefined) return
    const cache = chatCacheRef.current
    cache.delete(chatId)
    cache.set(chatId, messages.filter(item => !item.pending).slice(-200))
    while (cache.size > CHAT_CACHE_LIMIT) cache.delete(cache.keys().next().value as number)
  }, [messages])


  useEffect(() => {
    if (!isPopoutWindow || !popoutChatId || !dialogs.length) return
    if (selected?.chat_id === popoutChatId) return
    const dialog = dialogs.find(item => item.chat_id === popoutChatId)
    if (dialog) void openDialog(dialog)
  }, [dialogs, selected?.chat_id])

  useEffect(() => {
    notificationsEnabledRef.current = notificationsEnabled
  }, [notificationsEnabled])

  useEffect(() => {
    window.localStorage.setItem(PREFERENCES_STORAGE_KEY, JSON.stringify(preferences))
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
    if (status?.state !== 'PROXY_ERROR') return

    let disposed = false
    const refresh = async () => {
      try {
        const [transport, probes] = await Promise.all([
          api<TransportStatus>('/api/telegram/transport'),
          api<ProxyProbe[]>('/api/telegram/transport/probe')
        ])
        if (!disposed) {
          setTransportStatus(transport)
          setProxyProbes(probes)
        }
      } catch {
        // Keep the recovery screen usable; the next polling cycle retries.
      }
    }

    void refresh()
    const timer = window.setInterval(() => void refresh(), 5000)
    return () => {
      disposed = true
      window.clearInterval(timer)
    }
  }, [status?.state])

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

    async function refreshSnapshot() {
      try {
        const nextStatus = await api<Status>('/api/telegram/status')
        if (disposed) return
        setStatus(nextStatus)
        if (nextStatus.client_session_exists && !dialogsRef.current.length) {
          // Show the chat list from the local cache at once, like Telegram,
          // while the live list is fetched (or the proxy is still connecting).
          const cached = await api<Dialog[]>('/api/telegram/dialogs?cached=true').catch(() => [] as Dialog[])
          if (!disposed && !dialogsRef.current.length && cached.length) setDialogs(cached)
        }
        if (nextStatus.authorized) await loadLiveDialogs()
      } catch {
        // The packaged backend can need a moment to start. WebSocket retry handles recovery.
      }
    }

    async function resyncActiveChat() {
      const chatId = selectedChatIdRef.current
      if (!chatId || disposed) return
      try {
        const current = await api<Message[]>(chatPath(chatId) + '/messages?limit=' + HISTORY_PAGE_SIZE)
        if (!disposed && selectedChatIdRef.current === chatId) {
          setMessages(previous => [...current.filter(item => !item.deleted), ...previous.filter(item => item.pending)])
        }
      } catch {
        // A later reconnect or explicit refresh will retry the snapshot.
      }
    }

    function handlePacket(packet: { type: string; data: unknown }) {
      if (packet.type === 'READY') {
        const ready = packet.data as Status
        setStatus(ready)
        if (ready.authorized) {
          void refreshSnapshot()
          void resyncActiveChat()
        }
        return
      }
      if (packet.type === 'RESYNC') {
        void refreshSnapshot()
        void resyncActiveChat()
        return
      }
      if (packet.type === 'MESSAGE_NEW' || packet.type === 'MESSAGE_EDITED') {
        const message = packet.data as Message
        const isNew = packet.type === 'MESSAGE_NEW'
        const activeAndVisible = (
          selectedChatIdRef.current === message.chat_id
          && document.visibilityState === 'visible'
        )
        const dialog = dialogsRef.current.find(item => item.chat_id === message.chat_id)
        if (isNew && !dialog) scheduleDialogRefresh()
        setDialogs(current => current.map(item => {
          if (item.chat_id !== message.chat_id) return item
          const isLatest = isNew || item.last_message_id === message.message_id
          if (!isLatest) return item
          return {
            ...item,
            last_message_id: message.message_id,
            last_message_at: isNew ? message.date : item.last_message_at,
            last_message_preview: messageSnippet(message),
            last_message_sender: isGroupType(item.dialog_type) && !message.action
              ? (message.outgoing ? 'شما' : firstName(message.sender_name))
              : null,
            last_message_outgoing: message.outgoing,
            last_message_read: isNew ? false : item.last_message_read,
            unread_count: isNew && !message.outgoing && !activeAndVisible
              ? item.unread_count + 1
              : item.unread_count
          }
        }))
        if (isNew && !message.outgoing && !activeAndVisible) showDesktopNotification(message)

        if (selectedChatIdRef.current === message.chat_id) {
          const shouldFollow = message.outgoing || isNearBottom()
          const exists = messagesRef.current.some(item => item.message_id === message.message_id)
          if (isNew && !message.outgoing && !shouldFollow && !exists) setNewBelowCount(count => count + 1)
          setMessages(current => {
            let next = current
            if (isNew && message.outgoing) {
              // Our own message came back from Telegram before the send call
              // returned: retire the matching optimistic copy.
              const pendingIndex = next.findIndex(item => item.pending && item.text === message.text)
              if (pendingIndex >= 0) next = next.filter((_, index) => index !== pendingIndex)
            }
            return mergeMessage(next, message)
          })
          if (shouldFollow) window.requestAnimationFrame(() => scrollToBottom(message.outgoing ? 'smooth' : 'auto'))
        } else {
          const cached = chatCacheRef.current.get(message.chat_id)
          if (cached) chatCacheRef.current.set(message.chat_id, mergeMessage(cached, message))
        }
        return
      }
      if (packet.type === 'MESSAGE_REACTIONS') {
        const update = packet.data as ReactionUpdate
        const apply = (list: Message[]) => list.map(item => {
          if (item.message_id !== update.message_id) return item
          const reactions = update.min
            ? update.reactions.map(reaction => ({
              ...reaction,
              chosen: item.reactions.some(own => own.emoji === reaction.emoji && own.chosen)
            }))
            : update.reactions
          return { ...item, reactions }
        })
        if (selectedChatIdRef.current === update.chat_id) setMessages(apply)
        const cached = chatCacheRef.current.get(update.chat_id)
        if (cached) chatCacheRef.current.set(update.chat_id, apply(cached))
        return
      }
      if (packet.type === 'USER_STATUS') {
        const value = packet.data as { user_id: number; status: string | null }
        setChatInfo(current => (current && current.chat_id === value.user_id ? { ...current, status: value.status } : current))
        return
      }
      if (packet.type === 'DIALOG_UPDATED') {
        applyDialogPatch(packet.data as DialogPatch)
        return
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
          const expiresAt = Date.now() + 6000
          setChatActions(current => ({ ...current, [action.chat_id]: { ...action, expires_at: expiresAt } }))
          window.setTimeout(() => {
            setChatActions(current => {
              if (current[action.chat_id]?.expires_at !== expiresAt) return current
              const next = { ...current }
              delete next[action.chat_id]
              return next
            })
          }, 6100)
        }
        return
      }
      if (packet.type === 'MESSAGES_READ') {
        const receipt = packet.data as ReadReceipt
        setDialogs(current => current.map(item => (
          item.chat_id === receipt.chat_id && item.last_message_outgoing && (item.last_message_id || 0) <= receipt.max_id
            ? { ...item, last_message_read: true }
            : item
        )))
        if (selectedChatIdRef.current === receipt.chat_id) {
          setMessages(current => current.map(item => (
            item.outgoing && !item.pending && item.message_id <= receipt.max_id
              ? { ...item, read: true }
              : item
          )))
        }
        return
      }
      if (packet.type === 'MESSAGE_DELETED') {
        const deleted = packet.data as { chat_id: number | null; message_id: number }
        const openChat = selectedChatIdRef.current
        // Deletions in private chats and basic groups may arrive without a
        // chat id; their message ids are account-wide, so it is safe to drop
        // the id from whichever non-channel chat is open.
        const affectsOpen = openChat !== null && (
          deleted.chat_id === openChat || (deleted.chat_id === null && !isChannelId(openChat))
        )
        if (affectsOpen) {
          setMessages(current => current.filter(item => item.message_id !== deleted.message_id))
          setPinnedMessage(current => current?.message_id === deleted.message_id ? null : current)
          setReplyingTo(current => current?.message_id === deleted.message_id ? null : current)
          setEditing(current => current?.message_id === deleted.message_id ? null : current)
        }
        if (deleted.chat_id !== null) {
          const cached = chatCacheRef.current.get(deleted.chat_id)
          if (cached) chatCacheRef.current.set(deleted.chat_id, cached.filter(item => item.message_id !== deleted.message_id))
        }
      }
    }

    function connectSocket() {
      if (disposed) return
      socket = new WebSocket(authedUrl(socketBase + '/ws/telegram'))
      socket.onopen = () => {
        retryCount = 0
      }
      socket.onmessage = event => {
        try {
          handlePacket(JSON.parse(event.data) as { type: string; data: unknown })
        } catch {
          // One malformed packet must not stop live updates.
        }
      }
      socket.onclose = () => {
        if (disposed) return
        setStatus(current => current ? { ...current, connected: false, state: 'CONNECTING' } : current)
        const delay = Math.min(1000 * 2 ** retryCount, 10000)
        retryCount += 1
        retryTimer = window.setTimeout(connectSocket, delay)
      }
      socket.onerror = () => socket?.close()
    }

    // refreshSnapshot waits for the backend token; the socket needs it too.
    void refreshSnapshot().finally(connectSocket)
    return () => {
      disposed = true
      if (retryTimer !== undefined) window.clearTimeout(retryTimer)
      if (dialogRefreshTimerRef.current !== null) window.clearTimeout(dialogRefreshTimerRef.current)
      socket?.close()
    }
  }, [])

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
      clearPendingAttachments()
      setMediaPanel(null)
      setDragActive(false)
      setReactionPickerFor(null)
      setMessageContextMenu(null)
      setSelectedMessageIds(new Set())
      return
    }
    const chatId = selected.chat_id
    const unreadCount = selected.unread_count
    const remembered = chatCacheRef.current.get(chatId)
    setMessages(remembered || [])
    setHasOlder(Boolean(remembered && remembered.length >= HISTORY_PAGE_SIZE))
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
    if (remembered) window.requestAnimationFrame(() => scrollToBottom('auto'))

    // Every response below checks the chat is still open: switching chats
    // quickly must never show one chat's data inside another.
    const stillOpen = () => selectedChatIdRef.current === chatId
    let liveArrived = false

    if (!remembered) {
      api<Message[]>(chatPath(chatId) + '/messages?cached=true&limit=' + HISTORY_PAGE_SIZE)
        .then(items => {
          if (!stillOpen() || liveArrived || !items.length) return
          setMessages(items)
          setHasOlder(items.length === HISTORY_PAGE_SIZE)
          window.requestAnimationFrame(() => scrollToBottom('auto'))
        })
        .catch(() => undefined)
    }

    api<ChatInfo>(chatPath(chatId))
      .then(info => { if (stillOpen()) setChatInfo(info) })
      .catch(() => undefined)

    api<Message | null>(chatPath(chatId) + '/pinned')
      .then(message => { if (stillOpen()) setPinnedMessage(message) })
      .catch(() => undefined)

    api<Message[]>(chatPath(chatId) + '/messages?limit=' + HISTORY_PAGE_SIZE)
      .then(items => {
        if (!stillOpen()) return
        liveArrived = true
        const visibleItems = items.filter(item => !item.deleted)
        setMessages(current => [...visibleItems, ...current.filter(item => item.pending)])
        setHasOlder(items.length === HISTORY_PAGE_SIZE)
        const incoming = items.filter(item => !item.outgoing && !item.deleted && !item.action)
        const unreadIndex = Math.max(0, incoming.length - unreadCount)
        setUnreadBoundaryId(unreadCount > 0 && incoming.length > 0 ? incoming[unreadIndex].message_id : null)
        if (stickToBottomRef.current) window.requestAnimationFrame(() => scrollToBottom('auto'))
      })
      .catch(error => {
        if (stillOpen() && !messagesRef.current.length) setError(errorMessage(error, 'تاریخچه این گفتگو دریافت نشد.'))
      })

    if (unreadCount > 0) {
      api<{ chat_id: number; read: boolean }>(chatPath(chatId) + '/read', { method: 'POST' })
        .then(() => {
          setDialogs(current => current.map(item => item.chat_id === chatId ? { ...item, unread_count: 0 } : item))
          setSelected(current => current && current.chat_id === chatId ? { ...current, unread_count: 0 } : current)
        })
        .catch(() => undefined)
    }
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

    const handleUp = () => {
      sidebarResizeRef.current = null
      window.localStorage.setItem('telegram-sidebar-width', String(latestWidth))
      window.removeEventListener('mousemove', handleMove)
      window.removeEventListener('mouseup', handleUp)
      document.body.classList.remove('sidebar-resizing')
    }

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

  async function loadLiveDialogs() {
    const nextDialogs = await api<Dialog[]>('/api/telegram/dialogs')
    setDialogs(nextDialogs)
    const nextFolders = await api<DialogFolder[]>('/api/telegram/dialog-folders').catch(() => null)
    if (nextFolders) setTelegramFolders(nextFolders)
  }

  // A message from a chat that is not in the list (new chat): refetch once,
  // debounced so a burst of messages costs one request.
  function scheduleDialogRefresh() {
    if (dialogRefreshTimerRef.current !== null) return
    dialogRefreshTimerRef.current = window.setTimeout(() => {
      dialogRefreshTimerRef.current = null
      void loadLiveDialogs().catch(() => undefined)
    }, 1500)
  }

  async function refreshDialogs() {
    try {
      await loadLiveDialogs()
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
    const chatId = selected.chat_id
    const oldestId = messages.find(item => !item.pending)?.message_id || 0
    try {
      const older = await api<Message[]>(
        chatPath(chatId) + '/messages?limit=' + HISTORY_PAGE_SIZE + '&offset_id=' + oldestId
      )
      if (selectedChatIdRef.current !== chatId) return
      setMessages(current => {
        const known = new Set(current.map(item => item.message_id))
        return [...older.filter(item => !item.deleted && !known.has(item.message_id)), ...current]
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
    if (nextStatus.authorized) await loadLiveDialogs()
  }

  async function importSession() {
    setImporting(true)
    setError('')
    try {
      const nextStatus = await api<Status>('/api/telegram/session/import', { method: 'POST' })
      setStatus(nextStatus)
      if (nextStatus.authorized) await loadLiveDialogs()
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
      if (nextStatus.authorized) await loadLiveDialogs()
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
      await api<{ index: number }>('/api/telegram/transport/add-link', {
        method: 'POST',
        body: JSON.stringify({ link })
      })
      setProxyLinkDraft('')
      setShowProxyAdd(false)
      await refreshProxySettings()
    } catch (caught) {
      setError(errorMessage(caught, 'پراکسی اضافه نشد.'))
    } finally {
      setProxyBusy(false)
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

  function updatePreferences(values: Partial<ClientPreferences>) {
    setPreferences(current => ({ ...current, ...values }))
  }

  async function refreshProxySettings() {
    const [transport, probes] = await Promise.all([
      api<TransportStatus>('/api/telegram/transport'),
      api<ProxyProbe[]>('/api/telegram/transport/probe')
    ])
    setTransportStatus(transport)
    setProxyProbes(probes)
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
      await api<{ index: number }>('/api/telegram/transport/add-link', {
        method: 'POST',
        body: JSON.stringify({ link: value })
      })
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
      const blob = await apiBlob(
        chatPath(message.chat_id) + '/messages/' + message.message_id + '/media?download=true',
        'دانلود رسانه انجام نشد.'
      )
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

  async function sendMessage(event: FormEvent) {
    event.preventDefault()
    const text = draft.trim()
    if (!selected || (!text && !pendingAttachments.length)) return

    if (!editing && pendingAttachments.length) {
      await uploadPendingFiles()
      return
    }

    if (editing) {
      if (composerBusy) return
      setComposerBusy(true)
      try {
        const message = await api<Message>(
          chatPath(selected.chat_id) + '/messages/' + editing.message_id + '/edit',
          {
            method: 'POST',
            body: JSON.stringify({ text })
          }
        )
        setMessages(current => current.map(item => item.message_id === message.message_id ? message : item))
        setEditing(null)
        setDraft(draftBeforeEditRef.current)
      } catch (caught) {
        setError(errorMessage(caught, 'ویرایش پیام انجام نشد.'))
      } finally {
        setComposerBusy(false)
      }
      return
    }

    // Show the message at once, like Telegram, and swap in the real one when
    // Telegram confirms it. The composer stays free for the next message.
    const chatId = selected.chat_id
    const replyTo = replyingTo?.message_id || null
    const tempId = -Date.now() - Math.floor(Math.random() * 1000)
    const optimistic: Message = {
      chat_id: chatId,
      message_id: tempId,
      text,
      date: new Date().toISOString(),
      sender_id: status?.user_id || null,
      sender_name: status?.display_name || null,
      outgoing: true,
      edited: false,
      reply_to_message_id: replyTo,
      reactions: [],
      read: false,
      deleted: false,
      pending: true
    }
    setMessages(current => mergeMessage(current, optimistic))
    setReplyingTo(null)
    setDraft('')
    window.requestAnimationFrame(() => scrollToBottom('smooth'))
    try {
      const message = await api<Message>(chatPath(chatId) + '/messages', {
        method: 'POST',
        body: JSON.stringify({ text, reply_to_message_id: replyTo })
      })
      if (selectedChatIdRef.current === chatId) {
        setMessages(current => mergeMessage(current.filter(item => item.message_id !== tempId), message))
      }
    } catch (caught) {
      if (selectedChatIdRef.current === chatId) {
        setMessages(current => current.filter(item => item.message_id !== tempId))
        setDraft(current => current || text)
      }
      setError(errorMessage(caught, 'ارسال پیام انجام نشد.'))
    }
  }

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

  const dialogActions = useStableHandlers<DialogActions>({
    open: dialog => openDialog(dialog),
    contextMenu: (event, dialog) => {
      event.preventDefault()
      event.stopPropagation()
      setDialogContextMenu({ dialog, x: event.clientX, y: event.clientY })
    }
  })

  const closeViewer = useCallback(() => setViewerMessage(null), [])

  if (!status) {
    return <div className="loading-screen">در حال راه‌اندازی تلگرام…</div>
  }

  // With a saved session, open straight into the cached chat list while
  // Telegram connects, instead of a login/connecting screen.
  const showMain = status.authorized || (
    status.client_session_exists && status.state === 'CONNECTING' && dialogs.length > 0
  )

  if (!showMain) {
    return (
      <div className="auth-screen">
        <div className={'auth-card' + (status.state === 'PROXY_ERROR' ? ' proxy-recovery-card' : '')}>
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
                  placeholder="tg://proxy?... or https://t.me/proxy?..."
                  dir="ltr"
                  autoComplete="off"
                />
              </label>
              <button className="primary-action auth-submit" type="submit" disabled={runtimeConfigBusy}>
                {runtimeConfigBusy ? 'در حال اتصال…' : 'ذخیره و اتصال'}
              </button>
            </form>
          ) : status.state === 'PROXY_ERROR' ? (
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
                    <small>MTProto or SOCKS Telegram link</small>
                  </span>
                </button>

                {showProxyAdd && (
                  <form className="auth-proxy-add" onSubmit={addProxyFromAuth}>
                    <input
                      value={proxyLinkDraft}
                      onChange={event => setProxyLinkDraft(event.target.value)}
                      placeholder="https://t.me/proxy?server=...&port=...&secret=..."
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
                        {probe?.available
                          ? Math.round(probe.latency_ms || 0) + ' ms'
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
                <button type="button" disabled={proxyBusy} onClick={() => void selectProxy(null)}>
                  {proxyBusy ? 'در حال اتصال…' : 'تلاش مجدد با همه مسیرها'}
                </button>
              </div>
            </section>
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
    <main className={'telegram-shell' + (preferences.compact ? ' compact-mode' : '') + (isPopoutWindow ? ' popout-mode' : '')} style={{ '--sidebar-width': sidebarWidth + 'px' } as React.CSSProperties} onMouseDown={() => { setMessageContextMenu(null); setDialogContextMenu(null) }}>
      <header className="app-titlebar" data-tauri-drag-region>
        <div className="titlebar-brand" data-tauri-drag-region>
          <button className="titlebar-menu" aria-label="منوی اصلی" title="منوی اصلی" onClick={() => setMainMenuOpen(value => !value)}>☰</button>
          <span className="account-stack" aria-hidden="true"><i /><i /></span>
          <span className="telegram-logo" aria-hidden="true">➤</span>
          <strong className="app-title">{status.authorized && status.connected ? 'Telegram' : 'در حال اتصال…'}</strong>
        </div>
        <div className="titlebar-drag-fill" data-tauri-drag-region aria-hidden="true" />
        <div className="window-controls">
          <button aria-label="کمینه" onClick={() => void appWindow?.minimize()}>—</button>
          <button aria-label="بیشینه" onClick={() => void appWindow?.toggleMaximize()}>□</button>
          <button className="window-close" aria-label="بستن" onClick={() => void appWindow?.close()}>×</button>
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
              <span className="menu-chevron">⌃</span>
            </section>
            <button className="menu-item" type="button" onClick={() => menuUnavailable('افزودن حساب')}><i>⊕</i><span>Add Account</span></button>
            <hr />
            <button className="menu-item" type="button" onClick={openSelfChat}><i>⌑</i><span>Saved Messages</span></button>
            <button className="menu-item" type="button" onClick={openSelfChat}><i>◉</i><span>My Profile</span></button>
            <button className="menu-item" type="button" onClick={() => menuUnavailable('گروه جدید')}><i>♧</i><span>New Group</span></button>
            <button className="menu-item" type="button" onClick={() => menuUnavailable('کانال جدید')}><i>▷</i><span>New Channel</span></button>
            <hr />
            <button className="menu-item active" type="button" onClick={() => setMainMenuOpen(false)}><i>◌</i><span>Chats</span></button>
            <button className="menu-item" type="button" onClick={() => menuUnavailable('مخاطبین')}><i>♙</i><span>Contacts</span></button>
            <button className="menu-item" type="button" onClick={() => menuUnavailable('تماس‌ها')}><i>⌕</i><span>Calls</span></button>
            <button className="menu-item" type="button" onClick={() => void openSettings()}><i>⚙</i><span>Settings</span></button>
            <hr />
            <button className="menu-item" type="button" onClick={() => menuUnavailable('قابلیت‌های تلگرام')}><i>?</i><span>Telegram Features</span></button>
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
            <span>□</span>
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
              {messageRows.map(row => {
                const lead = row.lead
                const key = mediaKey(lead)
                const busyPrefix = key + ':'
                return (
                  <Fragment key={lead.message_id}>
                    {row.dayBreak && (
                      <div className="date-separator"><span>{formatMessageDate(lead.date)}</span></div>
                    )}
                    {unreadBoundaryId !== null && row.items.some(item => item.message_id === unreadBoundaryId) && (
                      <div className="unread-divider"><span>پیام‌های خوانده‌نشده</span></div>
                    )}
                    <MessageBubble
                      message={lead}
                      album={row.items.length > 1 ? row.items : undefined}
                      isGroup={isGroupType(selected.dialog_type)}
                      showSender={row.showSender}
                      showAvatar={row.showAvatar}
                      chatTitle={selected.title}
                      replySource={lead.reply_to_message_id ? messagesById.get(lead.reply_to_message_id) || null : undefined}
                      selected={selectedMessageIds.has(lead.message_id)}
                      selectionMode={selectedMessageIds.size > 0}
                      pickerOpen={reactionPickerFor === lead.message_id}
                      reactionBusy={reactionBusy !== null && reactionBusy.startsWith(busyPrefix) ? reactionBusy : null}
                      mediaState={mediaStates[key] || 'ready'}
                      autoLoadPhotos={preferences.autoLoadPhotos}
                      revealed={revealedPhotos.has(key)}
                      actions={bubbleActions}
                    />
                  </Fragment>
                )
              })}
              {showJumpToBottom && (
                <button className="jump-bottom" type="button" onClick={() => scrollToBottom('smooth')} aria-label="رفتن به آخر گفتگو">
                  <span>↓</span>
                  {newBelowCount > 0 && <strong>{formatNumber(newBelowCount)}</strong>}
                </button>
              )}
            </div>
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
                            {recentMediaSending === key ? (
                              <strong>…</strong>
                            ) : (
                              <img
                                src={authedUrl(backendBase + '/api/telegram/media/recent/' + item.kind + '/' + encodeURIComponent(item.media_id) + '/preview')}
                                alt={item.label}
                                loading="lazy"
                                decoding="async"
                                draggable={false}
                                onError={event => { event.currentTarget.style.display = 'none' }}
                              />
                            )}
                            <small>{item.kind === 'sticker' ? item.label : 'GIF'}</small>
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
                    disabled={(editing !== null && composerBusy) || uploadBusy || (!draft.trim() && !pendingAttachments.length)}
                  >
                    <span className="composer-action-icon" aria-hidden="true" />
                  </button>
                </div>
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
                    placeholder="tg://proxy?... or https://t.me/proxy?..."
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
                          {probe?.available
                            ? 'Connected, Ping: ' + Math.round(probe.latency_ms || 0) + ' ms'
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

      {viewerMessage && (
        <MediaViewer message={viewerMessage} onClose={closeViewer} onDownload={message => void downloadMedia(message)} />
      )}

      {error && <button className="error-toast" onClick={() => setError('')}>{error}</button>}
    </main>
  )
}

export default App
