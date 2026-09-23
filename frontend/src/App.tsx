import { useEffect, useMemo, useState } from 'react'

type Dialog = {
  chat_id: number
  title: string
  dialog_type: string
  username?: string | null
  unread_count: number
  pinned: boolean
  archived: boolean
}

type MediaInfo = {
  kind: 'photo' | 'video' | 'audio' | 'file' | 'other'
  name?: string | null
  size?: number | null
  mime_type?: string | null
  playable: boolean
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
  last_error?: string | null
}

const api = (path: string, options?: RequestInit) =>
  fetch(path, {
    ...options,
    headers: { 'Content-Type': 'application/json', ...(options?.headers || {}) }
  }).then(async response => {
    if (!response.ok) throw new Error((await response.text()) || 'Request failed')
    return response.json()
  })

function formatTime(value: string) {
  return new Intl.DateTimeFormat('fa-IR', { hour: '2-digit', minute: '2-digit' }).format(new Date(value))
}

function App() {
  const [status, setStatus] = useState<Status | null>(null)
  const [dialogs, setDialogs] = useState<Dialog[]>([])
  const [selected, setSelected] = useState<Dialog | null>(null)
  const [messages, setMessages] = useState<Message[]>([])
  const [query, setQuery] = useState('')
  const [draft, setDraft] = useState('')
  const [error, setError] = useState('')

  const visibleDialogs = useMemo(() => {
    const value = query.trim().toLocaleLowerCase()
    if (!value) return dialogs
    return dialogs.filter(item => item.title.toLocaleLowerCase().includes(value))
  }, [dialogs, query])

  useEffect(() => {
    api<Status>('/api/telegram/status').then(setStatus).catch(() => setError('اتصال به هسته تلگرام برقرار نشد.'))
    api<Dialog[]>('/api/telegram/dialogs').then(setDialogs).catch(() => undefined)

    const socket = new WebSocket(
      (location.protocol === 'https:' ? 'wss://' : 'ws://') + (location.host || '127.0.0.1:8110') + '/ws/telegram'
    )
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
      return
    }
    api<Message[]>('/api/telegram/chats/' + selected.chat_id + '/messages?limit=80')
      .then(setMessages)
      .catch(() => setError('تاریخچه این گفتگو دریافت نشد.'))
  }, [selected?.chat_id])

  async function sendMessage(event: React.FormEvent) {
    event.preventDefault()
    const text = draft.trim()
    if (!selected || !text) return
    setDraft('')
    try {
      const message = await api<Message>('/api/telegram/chats/' + selected.chat_id + '/messages', {
        method: 'POST',
        body: JSON.stringify({ text })
      })
      setMessages(current => [...current.filter(item => item.message_id !== message.message_id), message])
    } catch {
      setError('ارسال پیام انجام نشد.')
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
          <p>سشن مستقل برنامه آماده نیست.</p>
          <span className="status-pill">{status.state}</span>
          {status.last_error && <small>{status.last_error}</small>}
          <p className="muted">ورود و انتقال کنترل‌شده سشن در مرحله بعد اضافه می‌شود.</p>
        </div>
      </div>
    )
  }

  return (
    <main className="telegram-shell">
      <aside className="chat-sidebar">
        <header className="sidebar-header">
          <div className="brand-title"><span className="brand-mark small">✈</span> Telegram</div>
          <button className="icon-button" aria-label="منو">☰</button>
        </header>
        <label className="search-box">
          <span>⌕</span>
          <input value={query} onChange={event => setQuery(event.target.value)} placeholder="جست‌وجو" />
        </label>
        <div className="folder-tabs"><button className="active">همه</button><button>شخصی</button><button>گروه‌ها</button><button>کانال‌ها</button></div>
        <div className="dialog-list">
          {visibleDialogs.map(dialog => (
            <button className={'dialog-row ' + (selected?.chat_id === dialog.chat_id ? 'selected' : '')} key={dialog.chat_id} onClick={() => setSelected(dialog)}>
              <span className="avatar">{dialog.title.slice(0, 1)}</span>
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
              <div className="avatar large">{selected.title.slice(0, 1)}</div>
              <div><strong>{selected.title}</strong><small>{selected.dialog_type}</small></div>
              <div className="header-actions"><button className="icon-button">⌕</button><button className="icon-button">⋮</button></div>
            </header>
            <div className="message-list">
              {messages.map(message => (
                <article className={'message ' + (message.outgoing ? 'outgoing' : '') + (message.deleted ? ' deleted' : '')} key={message.message_id}>
                  {!message.outgoing && message.sender_name && <strong className="sender-name">{message.sender_name}</strong>}
                  {message.media && <div className="media-card">فایل {message.media.kind === 'video' ? 'ویدئو' : message.media.kind === 'audio' ? 'صدا' : message.media.kind}</div>}
                  {message.deleted ? <span>پیام حذف شده است</span> : message.text && <span>{message.text}</span>}
                  <small>{formatTime(message.date)}{message.edited ? ' · ویرایش‌شده' : ''}</small>
                </article>
              ))}
            </div>
            <form className="composer" onSubmit={sendMessage}>
              <button type="button" className="icon-button">＋</button>
              <input value={draft} onChange={event => setDraft(event.target.value)} placeholder="پیام..." />
              <button className="send-button" type="submit">➤</button>
            </form>
          </>
        ) : (
          <div className="empty-chat"><div className="brand-mark">✈</div><h2>یک گفتگو را انتخاب کنید</h2><p>پیام‌های تلگرام در اینجا نمایش داده می‌شوند.</p></div>
        )}
      </section>

      <aside className="info-panel">
        {selected ? <><div className="info-avatar avatar huge">{selected.title.slice(0, 1)}</div><h2>{selected.title}</h2><p>{selected.dialog_type}</p><hr /><p className="muted">جزئیات بیشتر در فاز بعد اضافه می‌شود.</p></> : <div className="muted">اطلاعات گفتگو</div>}
      </aside>

      {error && <button className="error-toast" onClick={() => setError('')}>{error}</button>}
    </main>
  )
}

export default App
