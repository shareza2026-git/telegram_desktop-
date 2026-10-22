export type Dialog = {
  chat_id: number
  title: string
  dialog_type: string
  username?: string | null
  unread_count: number
  pinned: boolean
  archived: boolean
  muted: boolean
  last_message_id?: number | null
  last_message_at?: string | null
  last_message_preview?: string | null
  last_message_sender?: string | null
  last_message_outgoing?: boolean
  last_message_read?: boolean
  // Quote room or price feed: delivered and drawn ahead of everything else.
  priority?: boolean
}

export type DialogFolder = {
  id: number
  title: string
  chat_ids: number[]
  unread_count: number
}

export type DialogPatch = {
  chat_id: number
  pinned?: boolean
  archived?: boolean
  muted?: boolean
  priority?: boolean
}

export type MessageContextMenu = {
  message: Message
  x: number
  y: number
}

export type DialogContextMenu = {
  dialog: Dialog
  x: number
  y: number
}

export type ChatInfo = {
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

export type MediaKind = 'photo' | 'video' | 'video_note' | 'gif' | 'sticker' | 'voice' | 'audio' | 'file' | 'other'

export type MediaInfo = {
  kind: MediaKind
  name?: string | null
  size?: number | null
  mime_type?: string | null
  playable: boolean
  downloadable: boolean
  width?: number | null
  height?: number | null
  duration?: number | null
  thumb_data?: string | null
  has_thumb?: boolean
  emoji?: string | null
  title?: string | null
  performer?: string | null
  animated?: boolean
}

export type ReactionSummary = {
  emoji: string
  count: number
  chosen: boolean
}

export type EntityType =
  | 'bold' | 'italic' | 'underline' | 'strike' | 'code' | 'pre' | 'spoiler' | 'blockquote'
  | 'url' | 'text_url' | 'mention' | 'mention_name' | 'hashtag' | 'cashtag' | 'bot_command'
  | 'email' | 'phone' | 'custom_emoji'

export type MessageEntity = {
  type: EntityType
  offset: number
  length: number
  url?: string | null
  user_id?: number | null
  language?: string | null
}

export type LinkPreview = {
  url: string
  site_name?: string | null
  title?: string | null
  description?: string | null
  has_photo?: boolean
}

export type Message = {
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
  entities?: MessageEntity[]
  forward_from?: string | null
  grouped_id?: number | null
  views?: number | null
  post?: boolean
  action?: string | null
  link_preview?: LinkPreview | null
  via_bot?: string | null
  // Client-only: optimistic message waiting for Telegram's answer.
  pending?: boolean
  failed?: boolean
}

export type Status = {
  configured: boolean
  connected: boolean
  authorized: boolean
  state: string
  user_id?: number | null
  display_name?: string | null
  phone?: string | null
  active_route?: string | null
  source_session_available: boolean
  client_session_exists: boolean
  session_dc_id?: number | null
  session_auth_key_present?: boolean
  session_auth_key_bytes?: number
  runtime_session_cloned?: boolean
  last_error?: string | null
}

export type ChatAction = {
  chat_id: number
  user_id?: number | null
  user_name?: string | null
  action: 'typing' | 'uploading' | 'recording' | 'cancel'
  active: boolean
  expires_at?: number
}

export type ReadReceipt = {
  chat_id: number
  max_id: number
}

export type ReactionUpdate = {
  chat_id: number
  message_id: number
  reactions: ReactionSummary[]
  min: boolean
}

export type PendingAttachment = {
  id: string
  file: File
  previewUrl: string | null
}

export type RecentMediaItem = {
  media_id: string
  kind: 'sticker' | 'gif'
  label: string
  mime_type?: string | null
}

export type RecentMediaCatalog = {
  stickers: RecentMediaItem[]
  gifs: RecentMediaItem[]
}

export type TransportStatus = {
  routes: Array<{
    index: number
    type: string
    host: string
    port: number
    managed_v2ray: boolean
    name: string
    selected?: boolean
  }>
  allow_direct: boolean
}

export type ProxyProbe = {
  index: number
  available: boolean
  latency_ms?: number | null
  detail?: string | null
  active?: boolean
}

export type AuthResponse = {
  code_sent: boolean
  requires_2fa: boolean
  authorized: boolean
}

export type DeviceSession = {
  hash: number
  current: boolean
  device_model: string
  platform: string
  system_version: string
  app_name: string
  app_version: string
  date_active: string
  country?: string | null
  region?: string | null
}

export type CallEntry = {
  chat_id: number
  title: string
  date: string
  outgoing: boolean
  missed: boolean
  video: boolean
  duration: number
}

export type ContactInfo = {
  chat_id: number
  title: string
  username?: string | null
  phone?: string | null
  status?: string | null
}

export type AuthStep = 'phone' | 'code' | 'password'
export type FolderKey = 'all' | 'private' | 'unread' | 'groups' | 'channels' | 'archived' | `folder:${number}`
export type MediaState = 'loading' | 'ready' | 'downloading' | 'done' | 'error'
