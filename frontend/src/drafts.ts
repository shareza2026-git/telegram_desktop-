export const DRAFT_STORAGE_KEY = 'telegram-chat-drafts-v1'

export type DraftMap = Record<string, string>

export function parseDraftMap(value: string | null): DraftMap {
  if (!value) return {}
  try {
    const parsed = JSON.parse(value) as unknown
    if (!parsed || typeof parsed !== 'object' || Array.isArray(parsed)) return {}
    return Object.fromEntries(
      Object.entries(parsed).filter((entry): entry is [string, string] => (
        typeof entry[1] === 'string'
      ))
    )
  } catch {
    return {}
  }
}

export function updateDraftMap(
  current: DraftMap,
  chatId: number,
  text: string
): DraftMap {
  const next = { ...current }
  const key = String(chatId)
  if (text) next[key] = text
  else delete next[key]
  return next
}
