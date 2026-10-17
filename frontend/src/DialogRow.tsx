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
          {dialog.muted && <svg className="dialog-icon" viewBox="0 0 16 16" aria-label="بی‌صدا"><path d="M3 6h2l3-3v10l-3-3H3z" fill="currentColor"/><path d="m10.5 6 3 4m0-4-3 4" stroke="currentColor" strokeWidth="1.4" strokeLinecap="round"/></svg>}
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
          <svg className="dialog-icon pin" viewBox="0 0 16 16" aria-label="سنجاق‌شده"><path d="M10.2 2.2 13.8 5.8l-1.4.6-2.3 2.3.2 2.6-1.1 1.1L6.9 10l-3.3 3.3-.6-.6L6.3 9.4 3.9 7.1 5 6l2.6.2 2.3-2.3z" fill="currentColor"/></svg>
        ) : null}
      </span>
    </button>
  )
}

export const DialogRow = memo(DialogRowView)
