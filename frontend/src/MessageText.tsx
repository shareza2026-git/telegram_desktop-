import { Fragment, memo, useState, type ReactNode } from 'react'

import type { MessageEntity } from './types'

const PROXY_LINK = /^(?:tg:\/\/(?:proxy|socks)\?|https?:\/\/(?:t\.me|telegram\.me)\/(?:proxy|socks)\?)/i
const PROXY_SPLIT = /(tg:\/\/(?:proxy|socks)\?[^\s]+|https?:\/\/(?:t\.me|telegram\.me)\/(?:proxy|socks)\?[^\s]+)/gi

type LinkHandlers = {
  openLink: (url: string) => void
  addProxy: (url: string) => void
}

function Spoiler({ children }: { children: ReactNode }) {
  const [revealed, setRevealed] = useState(false)
  return (
    <span
      className={'tg-spoiler' + (revealed ? ' revealed' : '')}
      onClick={event => {
        if (revealed) return
        event.stopPropagation()
        setRevealed(true)
      }}
    >
      {children}
    </span>
  )
}

function linkTarget(entity: MessageEntity, text: string) {
  if (entity.type === 'text_url') return entity.url || ''
  if (entity.type === 'url') return /^[a-z][a-z0-9+.-]*:/i.test(text) ? text : 'https://' + text
  if (entity.type === 'email') return 'mailto:' + text
  return ''
}

function plainWithProxyLinks(value: string, handlers: LinkHandlers, keyPrefix: string) {
  if (!value.includes('proxy') && !value.includes('socks')) return value
  return value.split(PROXY_SPLIT).map((part, index) => (
    PROXY_LINK.test(part)
      ? <button className="proxy-link" type="button" key={keyPrefix + index} onClick={() => handlers.addProxy(part)}>{part}</button>
      : <Fragment key={keyPrefix + index}>{part}</Fragment>
  ))
}

function wrap(entity: MessageEntity, content: ReactNode, text: string, key: string, handlers: LinkHandlers): ReactNode {
  switch (entity.type) {
    case 'bold': return <strong key={key}>{content}</strong>
    case 'italic': return <em key={key}>{content}</em>
    case 'underline': return <u key={key}>{content}</u>
    case 'strike': return <s key={key}>{content}</s>
    case 'code': return <code key={key} className="tg-code">{content}</code>
    case 'pre': return <pre key={key} className="tg-pre" dir="ltr">{content}</pre>
    case 'blockquote': return <blockquote key={key} className="tg-quote">{content}</blockquote>
    case 'spoiler': return <Spoiler key={key}>{content}</Spoiler>
    case 'url':
    case 'text_url':
    case 'email': {
      const target = linkTarget(entity, text)
      if (PROXY_LINK.test(target)) {
        return <button className="proxy-link" type="button" key={key} onClick={() => handlers.addProxy(target)}>{content}</button>
      }
      return (
        <a
          key={key}
          className="tg-link"
          href={target}
          title={entity.type === 'text_url' ? target : undefined}
          onClick={event => {
            event.preventDefault()
            event.stopPropagation()
            handlers.openLink(target)
          }}
        >
          {content}
        </a>
      )
    }
    case 'mention':
    case 'mention_name':
    case 'hashtag':
    case 'cashtag':
    case 'bot_command':
    case 'phone':
      return <span key={key} className="tg-link">{content}</span>
    default:
      return <Fragment key={key}>{content}</Fragment>
  }
}

/**
 * Renders Telegram formatting. Entities may nest (a bold link), so the text
 * is cut at every entity edge and each piece is wrapped by all entities that
 * cover it, outermost first.
 */
function MessageTextView({ text, entities, handlers }: { text: string; entities?: MessageEntity[]; handlers: LinkHandlers }) {
  const runs = (entities || []).filter(item => item.length > 0 && item.offset < text.length)
  if (!runs.length) return <>{plainWithProxyLinks(text, handlers, 'p')}</>

  const edges = new Set<number>([0, text.length])
  for (const entity of runs) {
    edges.add(entity.offset)
    edges.add(Math.min(text.length, entity.offset + entity.length))
  }
  const points = [...edges].sort((left, right) => left - right)
  // Block entities (pre/blockquote) render once around their whole range.
  const blocks = runs.filter(item => item.type === 'pre' || item.type === 'blockquote')
  const inline = runs.filter(item => item.type !== 'pre' && item.type !== 'blockquote')

  const pieces: Array<{ start: number; end: number; node: ReactNode }> = []
  for (let index = 0; index < points.length - 1; index += 1) {
    const start = points[index]
    const end = points[index + 1]
    if (end <= start) continue
    const slice = text.slice(start, end)
    const covering = inline
      .filter(item => item.offset <= start && item.offset + item.length >= end)
      .sort((left, right) => right.length - left.length)
    let node: ReactNode = covering.length ? slice : plainWithProxyLinks(slice, handlers, 'p' + start + '-')
    for (let depth = covering.length - 1; depth >= 0; depth -= 1) {
      const entity = covering[depth]
      node = wrap(entity, node, text.slice(entity.offset, entity.offset + entity.length), 'e' + start + '-' + depth, handlers)
    }
    pieces.push({ start, end, node })
  }

  if (!blocks.length) return <>{pieces.map(piece => <Fragment key={piece.start}>{piece.node}</Fragment>)}</>

  const output: ReactNode[] = []
  let cursor = 0
  for (const block of [...blocks].sort((left, right) => left.offset - right.offset)) {
    if (block.offset < cursor) continue
    const blockEnd = block.offset + block.length
    for (const piece of pieces) {
      if (piece.start >= cursor && piece.end <= block.offset) output.push(<Fragment key={piece.start}>{piece.node}</Fragment>)
    }
    const inner = pieces
      .filter(piece => piece.start >= block.offset && piece.end <= blockEnd)
      .map(piece => <Fragment key={piece.start}>{piece.node}</Fragment>)
    output.push(wrap(block, inner, text.slice(block.offset, blockEnd), 'b' + block.offset, handlers))
    cursor = blockEnd
  }
  for (const piece of pieces) {
    if (piece.start >= cursor) output.push(<Fragment key={piece.start}>{piece.node}</Fragment>)
  }
  return <>{output}</>
}

export const MessageText = memo(MessageTextView)
