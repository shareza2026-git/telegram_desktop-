import { memo, type MouseEvent as ReactMouseEvent } from 'react'

import { dialogTypeLabel, formatDialogTime, formatNumber } from './format'
import { ChatAvatar } from './media'
import type { Dialog } from './types'

export type DialogActions = {
  open: (dialog: Dialog) => void
  contextMenu: (event: ReactMouseEvent, dialog: Dialog) => void
}

function DialogRowView({
  dialog,
  selected,
  typing,
  actions
}: {
  dialog: Dialog
  selected: boolean
  typing: string | null
  actions: DialogActions
}) {
  const preview = dialog.last_message_preview || dialog.username || dialogTypeLabel(dialog.dialog_type)
  return (
    <button
      className={'dialog-row ' + (selected ? 'selected' : '')}
      onClick={() => actions.open(dialog)}
      onContextMenu={event => actions.contextMenu(event, dialog)}
    >
      <ChatAvatar chatId={dialog.chat_id} title={dialog.title} />
      <span className="dialog-copy">
        <span className="dialog-title-line">
          <strong>{dialog.title}</strong>
          {dialog.muted && <i aria-label="بی‌صدا">🔇</i>}
        </span>
        {typing ? (
          <small className="dialog-typing">{typing}</small>
        ) : (
          <small>
            {dialog.last_message_sender && <b className="dialog-sender">{dialog.last_message_sender}: </b>}
            {preview}
          </small>
        )}
      </span>
      <span className="dialog-meta">
        <span className="dialog-time-line">
          {dialog.last_message_outgoing && (
            <span className={'dialog-receipt ' + (dialog.last_message_read ? 'read' : '')}>
              {dialog.last_message_read ? '✓✓' : '✓'}
            </span>
          )}
          <time>{formatDialogTime(dialog.last_message_at)}</time>
        </span>
        {dialog.unread_count > 0 ? (
          <span className={'unread' + (dialog.muted ? ' muted' : '')}>{formatNumber(dialog.unread_count)}</span>
        ) : dialog.pinned ? (
          <i className="dialog-pin" aria-label="سنجاق‌شده">📌</i>
        ) : null}
      </span>
    </button>
  )
}

export const DialogRow = memo(DialogRowView)
