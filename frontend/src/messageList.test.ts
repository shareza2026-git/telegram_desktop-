import { describe, expect, it } from 'vitest'

import { buildMessageRows, mergeMessage } from './messageList'
import type { Message } from './types'

function message(id: number, extra: Partial<Message> = {}): Message {
  return {
    chat_id: 7,
    message_id: id,
    text: 'm' + id,
    date: '2026-10-17T10:00:00Z',
    sender_id: 1,
    outgoing: false,
    edited: false,
    reactions: [],
    read: false,
    deleted: false,
    ...extra
  }
}

describe('mergeMessage', () => {
  it('appends newer messages and keeps optimistic ones last', () => {
    const pending = message(-5, { pending: true, outgoing: true })
    const merged = mergeMessage([message(1), pending], message(2))
    expect(merged.map(item => item.message_id)).toEqual([1, 2, -5])
  })

  it('replaces an existing message in place', () => {
    const merged = mergeMessage([message(1), message(2)], message(1, { text: 'edited' }))
    expect(merged.map(item => item.text)).toEqual(['edited', 'm2'])
  })

  it('inserts an older message in order', () => {
    const merged = mergeMessage([message(1), message(3)], message(2))
    expect(merged.map(item => item.message_id)).toEqual([1, 2, 3])
  })
})

describe('buildMessageRows', () => {
  it('groups albums and marks sender runs', () => {
    const rows = buildMessageRows([
      message(1, { grouped_id: 9 }),
      message(2, { grouped_id: 9 }),
      message(3),
      message(4, { sender_id: 2 })
    ])
    expect(rows.map(row => row.items.map(item => item.message_id))).toEqual([[1, 2], [3], [4]])
    expect(rows.map(row => row.showSender)).toEqual([true, false, true])
    expect(rows.map(row => row.showAvatar)).toEqual([false, true, true])
  })

  it('starts a new day with a date break and hides deleted messages', () => {
    const rows = buildMessageRows([
      message(1),
      message(2, { deleted: true }),
      message(3, { date: '2026-10-18T10:00:00Z' })
    ])
    expect(rows.map(row => [row.lead.message_id, row.dayBreak])).toEqual([[1, true], [3, true]])
  })
})
