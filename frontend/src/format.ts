import type { ChatAction, MediaKind, Message } from './types'

// Intl formatters are expensive to build; create each once.
const timeFormat = new Intl.DateTimeFormat('en-US', { hour: 'numeric', minute: '2-digit' })
const dialogTimeFormat = new Intl.DateTimeFormat('en-US', { hour: 'numeric', minute: '2-digit' })
const dialogDateFormat = new Intl.DateTimeFormat('en-US', { month: 'short', day: 'numeric' })
const weekdayFormat = new Intl.DateTimeFormat('en-US', { weekday: 'short' })
const messageDateFormat = new Intl.DateTimeFormat('en-US', { month: 'long', day: 'numeric' })
const messageDateYearFormat = new Intl.DateTimeFormat('en-US', { year: 'numeric', month: 'long', day: 'numeric' })
const numberFormat = new Intl.NumberFormat('en-US')
const compactFormat = new Intl.NumberFormat('en-US', { notation: 'compact', maximumFractionDigits: 1 })

export function formatNumber(value: number) {
  return numberFormat.format(value)
}

export function formatCompact(value: number) {
  return compactFormat.format(value)
}

export function formatTime(value: string) {
  return timeFormat.format(new Date(value))
}

export function formatDialogTime(value?: string | null) {
  if (!value) return ''
  const date = new Date(value)
  const now = new Date()
  if (date.toDateString() === now.toDateString()) return dialogTimeFormat.format(date)
  if (now.getTime() - date.getTime() < 6 * 24 * 60 * 60 * 1000) return weekdayFormat.format(date)
  return dialogDateFormat.format(date)
}

export function messageDayKey(value: string) {
  const date = new Date(value)
  return [date.getFullYear(), date.getMonth(), date.getDate()].join('-')
}

export function formatMessageDate(value: string) {
  const date = new Date(value)
  const now = new Date()
  if (date.toDateString() === now.toDateString()) return 'Today'
  const yesterday = new Date(now)
  yesterday.setDate(now.getDate() - 1)
  if (date.toDateString() === yesterday.toDateString()) return 'Yesterday'
  return date.getFullYear() === now.getFullYear()
    ? messageDateFormat.format(date)
    : messageDateYearFormat.format(date)
}

export function formatDuration(seconds: number | null | undefined) {
  const total = Math.max(0, Math.round(seconds || 0))
  const minutes = Math.floor(total / 60)
  const rest = String(total % 60).padStart(2, '0')
  return minutes + ':' + rest
}

export function formatBytes(value: number | null | undefined) {
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

const mediaLabels: Record<MediaKind, string> = {
  photo: 'عکس',
  video: 'ویدئو',
  video_note: 'پیام ویدئویی',
  gif: 'GIF',
  sticker: 'استیکر',
  voice: 'پیام صوتی',
  audio: 'موسیقی',
  file: 'فایل',
  other: 'رسانه'
}

export function mediaKindLabel(kind: MediaKind) {
  return mediaLabels[kind] || mediaLabels.other
}

export function statusLabel(value: string) {
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

export function errorMessage(error: unknown, fallback: string) {
  return error instanceof Error && error.message ? error.message : fallback
}

export function dialogTypeLabel(value: string) {
  const labels: Record<string, string> = {
    user: 'گفت‌وگوی شخصی',
    group: 'گروه',
    supergroup: 'سوپرگروه',
    channel: 'کانال'
  }
  return labels[value] || value
}

export function chatActionLabel(value: ChatAction['action']) {
  const labels: Record<ChatAction['action'], string> = {
    typing: 'در حال نوشتن…',
    uploading: 'در حال ارسال فایل…',
    recording: 'در حال ضبط…',
    cancel: ''
  }
  return labels[value]
}

export function presenceLabel(value: string | null | undefined) {
  const labels: Record<string, string> = {
    online: 'آنلاین',
    offline: 'آفلاین',
    recently: 'اخیراً آنلاین',
    last_week: 'آخرین بازدید این هفته',
    last_month: 'آخرین بازدید این ماه'
  }
  return value ? labels[value] || value : ''
}

export function messageSnippet(message: Message | null) {
  if (!message) return 'پیام قبلی'
  if (message.action) return message.action
  const text = message.text.trim()
  if (text) return text.length > 110 ? text.slice(0, 110) + '…' : text
  if (message.media) {
    if (message.media.kind === 'sticker' && message.media.emoji) return message.media.emoji + ' استیکر'
    if (message.media.kind === 'other' && message.media.title) return message.media.title
    return mediaKindLabel(message.media.kind)
  }
  return 'پیام'
}

// Telegram's seven name colours, picked from the sender id.
const SENDER_COLORS = ['#e17076', '#eda86c', '#a695e7', '#7bc862', '#6ec9cb', '#65aadd', '#ee7aae']

export function senderColor(id: number | null | undefined) {
  return SENDER_COLORS[Math.abs(Number(id) || 0) % SENDER_COLORS.length]
}

export function isChannelId(chatId: number) {
  return chatId < -1_000_000_000_000
}
