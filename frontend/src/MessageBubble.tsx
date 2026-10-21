import { memo, type MouseEvent as ReactMouseEvent } from 'react'

import { formatCompact, formatNumber, formatTime, messageSnippet, senderColor } from './format'
import { ChatAvatar, MediaView } from './media'
import { MessageText } from './MessageText'
import type { MediaState, Message } from './types'

export const QUICK_REACTIONS = ['👍', '❤️', '😂', '😮', '😢', '🔥']

export type BubbleActions = {
  contextMenu: (event: ReactMouseEvent, message: Message) => void
  toggleSelection: (messageId: number) => void
  jumpTo: (messageId: number) => void
  react: (message: Message, emoji: string | null) => void
  download: (message: Message) => void
  view: (message: Message) => void
  reveal: (key: string) => void
  openLink: (url: string) => void
  addProxy: (url: string) => void
}

type BubbleProps = {
  message: Message
  album?: Message[]
  isGroup: boolean
  showSender: boolean
  showAvatar: boolean
  chatTitle: string
  replySource?: Message | null
  selected: boolean
  selectionMode: boolean
  pickerOpen: boolean
  reactionBusy: string | null
  mediaState: MediaState
  autoLoadPhotos: boolean
  revealed: boolean
  actions: BubbleActions
}

const VISUAL_KINDS = new Set(['photo', 'video', 'gif'])

function ServiceMessage({ message }: { message: Message }) {
  return (
    <div className="service-message" id={'message-' + message.chat_id + '-' + message.message_id}>
      <span>{message.action}</span>
    </div>
  )
}

function albumCell(count: number, index: number) {
  // Telegram-like mosaic: first item wide when the count is odd.
  const full = 340
  const half = 168
  if (count === 1) return undefined
  if (count % 2 === 1 && index === 0) return { width: full, height: 200 }
  return { width: half, height: half }
}

function BubbleView({
  message,
  album,
  isGroup,
  showSender,
  showAvatar,
  chatTitle,
  replySource,
  selected,
  selectionMode,
  pickerOpen,
  reactionBusy,
  mediaState,
  autoLoadPhotos,
  revealed,
  actions
}: BubbleProps) {
  if (message.action) return <ServiceMessage message={message} />

  const items = album && album.length > 1 ? album : [message]
  const caption = items.find(item => item.text.trim()) || message
  const firstMedia = items[0].media
  const kind = firstMedia?.kind
  const sticker = items.length === 1 && (kind === 'sticker' || kind === 'video_note')
  const visualOnly = !caption.text.trim() && items.every(item => item.media && VISUAL_KINDS.has(item.media.kind))
  const hasVisual = items.some(item => item.media && VISUAL_KINDS.has(item.media.kind))
  const mediaHandlers = { download: actions.download, view: actions.view, reveal: actions.reveal }

  const className = 'message'
    + (message.outgoing ? ' outgoing' : '')
    + (selected ? ' selected-message' : '')
    + (sticker ? ' sticker-message' : '')
    + (visualOnly ? ' media-only' : '')
    + (hasVisual && !visualOnly ? ' media-caption' : '')
    + (message.pending ? ' pending' : '')
    + (message.failed ? ' failed' : '')
    + (isGroup && !message.outgoing ? ' with-avatar' : '')
    + (showAvatar ? ' tail' : '')

  return (
    <article
      id={'message-' + message.chat_id + '-' + message.message_id}
      className={className}
      onContextMenu={event => actions.contextMenu(event, message)}
      onClick={event => {
        if (selectionMode && !(event.target as HTMLElement).closest('button, a')) actions.toggleSelection(message.message_id)
      }}
    >
      {isGroup && !message.outgoing && showAvatar && (
        <ChatAvatar
          chatId={message.sender_id || message.chat_id}
          title={message.sender_name || chatTitle}
          className="message-avatar"
        />
      )}
      {selectionMode && (
        <span className="message-selector" aria-hidden="true">{selected ? '✓' : ''}</span>
      )}
      {isGroup && !message.outgoing && showSender && message.sender_name && !sticker && (
        <strong className="sender-name" style={{ color: senderColor(message.sender_id) }}>
          {message.sender_name}
          {message.via_bot && <small className="via-bot"> via @{message.via_bot}</small>}
        </strong>
      )}
      {message.forward_from && (
        <span className="forward-header">
          <small>فورواردشده از</small>
          <strong>{message.forward_from}</strong>
        </span>
      )}
      {message.reply_to_message_id ? (
        <button
          className="reply-reference"
          type="button"
          onClick={event => {
            event.stopPropagation()
            actions.jumpTo(message.reply_to_message_id as number)
          }}
          style={replySource && !replySource.outgoing ? { borderColor: senderColor(replySource.sender_id) } : undefined}
        >
          <strong style={replySource && !replySource.outgoing ? { color: senderColor(replySource.sender_id) } : undefined}>
            {replySource ? (replySource.outgoing ? 'شما' : replySource.sender_name || chatTitle) : 'پیام قبلی'}
          </strong>
          <span>{messageSnippet(replySource || null)}</span>
        </button>
      ) : null}

      {firstMedia && (
        items.length > 1 ? (
          <div className={'tg-album' + (hasVisual ? ' visual' : '')}>
            {items.map((item, index) => (
              <MediaView
                key={item.message_id}
                message={item}
                state={mediaState}
                autoLoadPhotos={autoLoadPhotos}
                revealed={revealed}
                handlers={mediaHandlers}
                compact={hasVisual ? albumCell(items.length, index) : undefined}
              />
            ))}
          </div>
        ) : (
          <MediaView
            message={message}
            state={mediaState}
            autoLoadPhotos={autoLoadPhotos}
            revealed={revealed}
            handlers={mediaHandlers}
          />
        )
      )}

      {caption.text && (
        <span className="message-text" dir="auto">
          <MessageText text={caption.text} entities={caption.entities} handlers={actions} />
        </span>
      )}

      {message.link_preview && (
        <button
          type="button"
          className="link-preview"
          onClick={event => {
            event.stopPropagation()
            actions.openLink(message.link_preview!.url)
          }}
        >
          {message.link_preview.site_name && <strong>{message.link_preview.site_name}</strong>}
          {message.link_preview.title && <b>{message.link_preview.title}</b>}
          {message.link_preview.description && <span>{message.link_preview.description}</span>}
        </button>
      )}

      {Boolean(message.reactions?.length) && (
        <div className="message-reactions">
          {message.reactions.map(reaction => (
            <button
              type="button"
              className={reaction.chosen ? 'chosen' : ''}
              key={reaction.emoji}
              onClick={event => {
                event.stopPropagation()
                actions.react(message, reaction.chosen ? null : reaction.emoji)
              }}
              disabled={reactionBusy !== null}
            >
              <span>{reaction.emoji}</span>
              <small>{formatNumber(reaction.count)}</small>
            </button>
          ))}
        </div>
      )}
      {pickerOpen && !selectionMode && (
        <div className="reaction-picker" role="group" aria-label="انتخاب واکنش">
          {QUICK_REACTIONS.map(emoji => {
            const chosen = message.reactions?.some(item => item.emoji === emoji && item.chosen) || false
            const key = message.chat_id + ':' + message.message_id + ':' + (chosen ? 'remove' : emoji)
            return (
              <button
                type="button"
                className={chosen ? 'chosen' : ''}
                key={emoji}
                onClick={event => {
                  event.stopPropagation()
                  actions.react(message, chosen ? null : emoji)
                }}
                disabled={reactionBusy !== null}
              >
                {reactionBusy === key ? '…' : emoji}
              </button>
            )
          })}
        </div>
      )}
      <small className="message-meta">
        {message.views != null && message.post && <span className="views">👁 {formatCompact(message.views)}</span>}
        {message.edited && <span>ویرایش‌شده</span>}
        <span dir="ltr">{formatTime(message.date)}</span>
        {message.outgoing && (
          <span
            className={'read-receipt ' + (message.failed ? 'failed' : message.pending ? 'pending' : message.read ? 'read' : 'sent')}
            aria-label={message.failed ? 'ارسال نشد' : message.pending ? 'در حال ارسال' : message.read ? 'خوانده شده' : 'ارسال شده'}
          >
            {message.failed ? '!' : message.pending ? '◷' : message.read ? '✓✓' : '✓'}
          </span>
        )}
      </small>
    </article>
  )
}

export const MessageBubble = memo(BubbleView)
