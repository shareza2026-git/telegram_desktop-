import { memo, useEffect, useRef, useState, type CSSProperties } from 'react'

import { avatarUrl, mediaUrl } from './backend'
import { formatBytes, formatDuration, mediaKindLabel, senderColor } from './format'
import type { MediaState, Message } from './types'

// Avatars that failed recently: chat id -> retry time. A member's photo can
// become available once their details arrive, so failures expire.
const missingAvatars = new Map<number, number>()
const AVATAR_RETRY_MS = 3 * 60 * 1000

function avatarMissing(chatId: number) {
  const until = missingAvatars.get(chatId)
  return until !== undefined && until > Date.now()
}

function AvatarView({ chatId, title, className = '' }: { chatId: number; title: string; className?: string }) {
  const [failed, setFailed] = useState(() => avatarMissing(chatId))

  useEffect(() => {
    setFailed(avatarMissing(chatId))
  }, [chatId])

  return (
    <span className={'avatar ' + className} style={{ '--avatar-color': senderColor(chatId) } as CSSProperties}>
      <span className="avatar-fallback">{Array.from(title.trim())[0] || '?'}</span>
      {!failed && chatId !== 0 && (
        <img
          src={avatarUrl(chatId)}
          alt=""
          loading="lazy"
          decoding="async"
          draggable={false}
          onError={() => {
            missingAvatars.set(chatId, Date.now() + AVATAR_RETRY_MS)
            setFailed(true)
          }}
        />
      )}
    </span>
  )
}

export const ChatAvatar = memo(AvatarView)

/** Bubble size for a photo/video, keeping Telegram's aspect ratio limits. */
export function mediaBox(width?: number | null, height?: number | null, max = 340) {
  const w = width && width > 0 ? width : 320
  const h = height && height > 0 ? height : 240
  const scale = Math.min(1, max / Math.max(w, h))
  const boxWidth = Math.max(120, Math.round(w * scale))
  const boxHeight = Math.max(80, Math.min(max, Math.round(h * scale)))
  return { width: boxWidth, height: boxHeight }
}

type MediaHandlers = {
  download: (message: Message) => void
  view: (message: Message) => void
  reveal: (key: string) => void
}

function PhotoView({
  message,
  autoLoad,
  handlers,
  compact
}: {
  message: Message
  autoLoad: boolean
  handlers: MediaHandlers
  compact?: { width: number; height: number }
}) {
  const media = message.media!
  const [loaded, setLoaded] = useState(false)
  const [failed, setFailed] = useState(false)
  const box = compact || mediaBox(media.width, media.height)
  const key = message.chat_id + ':' + message.message_id

  return (
    <button
      type="button"
      className="tg-photo"
      style={{ width: box.width, height: box.height, backgroundImage: media.thumb_data ? `url(${media.thumb_data})` : undefined }}
      onClick={event => {
        event.stopPropagation()
        if (!autoLoad) handlers.reveal(key)
        else handlers.view(message)
      }}
    >
      {autoLoad && !failed && (
        <img
          src={mediaUrl(message.chat_id, message.message_id, { thumb: true })}
          alt=""
          loading="lazy"
          decoding="async"
          draggable={false}
          className={loaded ? 'loaded' : ''}
          onLoad={() => setLoaded(true)}
          onError={() => setFailed(true)}
        />
      )}
      {(!autoLoad || failed) && (
        <span className="tg-photo-overlay">
          <span className="tg-round-icon">{failed ? '↻' : '↓'}</span>
          <small>{formatBytes(media.size)}</small>
        </span>
      )}
    </button>
  )
}

function StickerView({ message }: { message: Message }) {
  const media = message.media!
  const [failed, setFailed] = useState(false)
  const src = mediaUrl(message.chat_id, message.message_id)
  if (media.animated || failed) {
    return <span className="tg-sticker-emoji" title="استیکر">{media.emoji || '🙂'}</span>
  }
  if (media.mime_type === 'video/webm') {
    return <video className="tg-sticker" src={src} autoPlay loop muted playsInline onError={() => setFailed(true)} />
  }
  return <img className="tg-sticker" src={src} alt={media.emoji || ''} loading="lazy" decoding="async" draggable={false} onError={() => setFailed(true)} />
}

function GifView({ message, autoLoad }: { message: Message; autoLoad: boolean }) {
  const media = message.media!
  const box = mediaBox(media.width, media.height, 300)
  const holder = useRef<HTMLDivElement>(null)
  const [visible, setVisible] = useState(false)

  // Only load and play GIFs while they are on screen, like Telegram.
  useEffect(() => {
    const element = holder.current
    if (!element || !autoLoad) return
    const observer = new IntersectionObserver(entries => setVisible(entries.some(entry => entry.isIntersecting)), { rootMargin: '200px' })
    observer.observe(element)
    return () => observer.disconnect()
  }, [autoLoad])

  return (
    <div
      ref={holder}
      className="tg-photo tg-gif"
      style={{ width: box.width, height: box.height, backgroundImage: media.thumb_data ? `url(${media.thumb_data})` : undefined }}
    >
      {visible && <video src={mediaUrl(message.chat_id, message.message_id)} autoPlay loop muted playsInline preload="auto" />}
      <span className="tg-media-badge">GIF</span>
    </div>
  )
}

function VideoView({ message, round }: { message: Message; round?: boolean }) {
  const media = message.media!
  const [playing, setPlaying] = useState(false)
  const box = round ? { width: 220, height: 220 } : mediaBox(media.width, media.height)
  const poster = media.has_thumb ? mediaUrl(message.chat_id, message.message_id, { thumb: true }) : undefined

  return (
    <div
      className={'tg-photo tg-video' + (round ? ' round' : '')}
      style={{ width: box.width, height: box.height, backgroundImage: media.thumb_data ? `url(${media.thumb_data})` : undefined }}
      onClick={event => event.stopPropagation()}
    >
      {playing ? (
        <video src={mediaUrl(message.chat_id, message.message_id)} poster={poster} controls={!round} autoPlay playsInline onEnded={() => round && setPlaying(false)} />
      ) : (
        <button type="button" className="tg-video-start" onClick={() => setPlaying(true)} aria-label="پخش ویدئو">
          {poster && <img src={poster} alt="" loading="lazy" decoding="async" draggable={false} />}
          <span className="tg-round-icon play">▶</span>
        </button>
      )}
      {!playing && (
        <span className="tg-media-badge">{formatDuration(media.duration)}{media.size ? ' · ' + formatBytes(media.size) : ''}</span>
      )}
    </div>
  )
}

function AudioView({ message, voice }: { message: Message; voice: boolean }) {
  const media = message.media!
  const audio = useRef<HTMLAudioElement>(null)
  const [playing, setPlaying] = useState(false)
  const [position, setPosition] = useState(0)
  const [duration, setDuration] = useState(media.duration || 0)
  const [started, setStarted] = useState(false)

  function toggle() {
    if (!started) {
      setStarted(true)
      return
    }
    const element = audio.current
    if (!element) return
    if (element.paused) void element.play()
    else element.pause()
  }

  useEffect(() => {
    if (started) void audio.current?.play().catch(() => setPlaying(false))
  }, [started])

  const progress = duration > 0 ? Math.min(100, (position / duration) * 100) : 0
  return (
    <div className={'tg-audio' + (voice ? ' voice' : '')} onClick={event => event.stopPropagation()}>
      <button type="button" className="tg-round-icon play" onClick={toggle} aria-label={playing ? 'توقف' : 'پخش'}>
        {playing ? '❚❚' : '▶'}
      </button>
      <div className="tg-audio-body">
        {!voice && <strong>{media.title || media.name || mediaKindLabel(media.kind)}</strong>}
        {!voice && media.performer && <small>{media.performer}</small>}
        <div
          className="tg-audio-track"
          onClick={event => {
            const element = audio.current
            if (!element || !duration) return
            const rect = event.currentTarget.getBoundingClientRect()
            element.currentTime = ((event.clientX - rect.left) / rect.width) * duration
          }}
        >
          <span style={{ width: progress + '%' }} />
        </div>
        <small className="tg-audio-time">
          {formatDuration(started ? position : duration)}{!started && media.size ? ' · ' + formatBytes(media.size) : ''}
        </small>
      </div>
      {started && (
        <audio
          ref={audio}
          src={mediaUrl(message.chat_id, message.message_id)}
          preload="auto"
          onPlay={() => setPlaying(true)}
          onPause={() => setPlaying(false)}
          onEnded={() => {
            setPlaying(false)
            setPosition(0)
          }}
          onTimeUpdate={event => setPosition(event.currentTarget.currentTime)}
          onLoadedMetadata={event => {
            if (Number.isFinite(event.currentTarget.duration)) setDuration(event.currentTarget.duration)
          }}
        />
      )}
    </div>
  )
}

function FileView({ message, state, handlers }: { message: Message; state: MediaState; handlers: MediaHandlers }) {
  const media = message.media!
  if (media.kind === 'other') {
    return (
      <div className="tg-file">
        <span className="tg-file-icon">◇</span>
        <div className="tg-file-copy"><strong>{media.title || mediaKindLabel(media.kind)}</strong></div>
      </div>
    )
  }
  const extension = (media.name || '').split('.').pop()?.slice(0, 4).toUpperCase() || ''
  const label = state === 'downloading' ? '…' : state === 'done' ? '✓' : state === 'error' ? '↻' : '↓'
  return (
    <div className="tg-file">
      <button
        type="button"
        className="tg-file-icon"
        onClick={event => {
          event.stopPropagation()
          handlers.download(message)
        }}
        disabled={state === 'downloading'}
        aria-label="دانلود"
      >
        <span>{label}</span>
        {extension && state === 'ready' && <small>{extension}</small>}
      </button>
      <div className="tg-file-copy">
        <strong>{media.name || mediaKindLabel(media.kind)}</strong>
        <small>{formatBytes(media.size)}{state === 'error' ? ' · دانلود ناموفق' : ''}</small>
      </div>
    </div>
  )
}

export function MediaView({
  message,
  state,
  autoLoadPhotos,
  revealed,
  handlers,
  compact
}: {
  message: Message
  state: MediaState
  autoLoadPhotos: boolean
  revealed: boolean
  handlers: MediaHandlers
  compact?: { width: number; height: number }
}) {
  const media = message.media
  if (!media) return null
  switch (media.kind) {
    case 'photo':
      return <PhotoView message={message} autoLoad={autoLoadPhotos || revealed} handlers={handlers} compact={compact} />
    case 'sticker':
      return <StickerView message={message} />
    case 'gif':
      return <GifView message={message} autoLoad={autoLoadPhotos || revealed} />
    case 'video':
      return <VideoView message={message} />
    case 'video_note':
      return <VideoView message={message} round />
    case 'voice':
      return <AudioView message={message} voice />
    case 'audio':
      return <AudioView message={message} voice={false} />
    default:
      return <FileView message={message} state={state} handlers={handlers} />
  }
}

/** Full-window photo/video viewer, opened by clicking a photo. */
export function MediaViewer({
  message,
  onClose,
  onDownload
}: {
  message: Message
  onClose: () => void
  onDownload: (message: Message) => void
}) {
  const media = message.media
  const [fullLoaded, setFullLoaded] = useState(false)

  useEffect(() => {
    function onKey(event: KeyboardEvent) {
      if (event.key === 'Escape') onClose()
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [onClose])

  if (!media) return null
  const preview = mediaUrl(message.chat_id, message.message_id, { thumb: true })
  const original = mediaUrl(message.chat_id, message.message_id)
  return (
    <div className="tg-viewer" onMouseDown={onClose}>
      <div className="tg-viewer-bar" onMouseDown={event => event.stopPropagation()}>
        <span>{message.sender_name || ''}</span>
        <button type="button" onClick={() => onDownload(message)} aria-label="دانلود">↓</button>
        <button type="button" onClick={onClose} aria-label="بستن">×</button>
      </div>
      <div className="tg-viewer-stage" onMouseDown={event => event.stopPropagation()}>
        {media.kind === 'photo' ? (
          <>
            {!fullLoaded && <img src={preview} alt="" className="tg-viewer-media" />}
            <img
              src={original}
              alt=""
              className="tg-viewer-media"
              style={fullLoaded ? undefined : { position: 'absolute', opacity: 0 }}
              onLoad={() => setFullLoaded(true)}
            />
          </>
        ) : (
          <video src={original} className="tg-viewer-media" controls autoPlay playsInline />
        )}
      </div>
      {message.text && <div className="tg-viewer-caption" onMouseDown={event => event.stopPropagation()}>{message.text}</div>}
    </div>
  )
}
