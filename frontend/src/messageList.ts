import { messageDayKey } from './format'
import type { Message } from './types'

/** Insert or replace a message, keeping real messages sorted and optimistic ones last. */
export function mergeMessage(list: Message[], message: Message) {
  const real = list.filter(item => !item.pending && item.message_id !== message.message_id)
  const pending = list.filter(item => item.pending && item.message_id !== message.message_id)
  if (message.pending) return [...real, ...pending, message]
  const last = real[real.length - 1]
  if (!last || last.message_id < message.message_id) return [...real, message, ...pending]
  return [...real, message].sort((a, b) => a.message_id - b.message_id).concat(pending)
}

export type MessageRow = {
  lead: Message
  items: Message[]
  dayBreak: boolean
  showSender: boolean
  showAvatar: boolean
}

export function buildMessageRows(messages: Message[]): MessageRow[] {
  const visible = messages.filter(message => !message.deleted)
  const rows: MessageRow[] = []
  for (let index = 0; index < visible.length; index += 1) {
    const lead = visible[index]
    const items = [lead]
    // Albums arrive as consecutive messages sharing one grouped_id.
    while (
      lead.grouped_id
      && index + 1 < visible.length
      && visible[index + 1].grouped_id === lead.grouped_id
      && items.length < 10
    ) {
      index += 1
      items.push(visible[index])
    }
    const previous = rows[rows.length - 1]
    const dayBreak = !previous || messageDayKey(previous.lead.date) !== messageDayKey(lead.date)
    const sameSender = Boolean(
      previous
      && !dayBreak
      && !previous.lead.action
      && !lead.action
      && previous.lead.outgoing === lead.outgoing
      && previous.lead.sender_id === lead.sender_id
    )
    if (previous && sameSender) previous.showAvatar = false
    rows.push({ lead, items, dayBreak, showSender: !sameSender, showAvatar: true })
  }
  return rows
}
