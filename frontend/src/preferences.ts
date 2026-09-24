export type ThemePreference = 'system' | 'dark' | 'light'

export type ClientPreferences = {
  theme: ThemePreference
  compact: boolean
  autoLoadPhotos: boolean
}

export const PREFERENCES_STORAGE_KEY = 'telegram-client-preferences-v1'

export const DEFAULT_PREFERENCES: ClientPreferences = {
  theme: 'system',
  compact: false,
  autoLoadPhotos: true
}

export function parsePreferences(raw: string | null): ClientPreferences {
  if (!raw) return DEFAULT_PREFERENCES
  try {
    const value = JSON.parse(raw) as Partial<ClientPreferences>
    const theme = value.theme === 'dark' || value.theme === 'light' || value.theme === 'system'
      ? value.theme
      : DEFAULT_PREFERENCES.theme
    return {
      theme,
      compact: typeof value.compact === 'boolean' ? value.compact : DEFAULT_PREFERENCES.compact,
      autoLoadPhotos: typeof value.autoLoadPhotos === 'boolean'
        ? value.autoLoadPhotos
        : DEFAULT_PREFERENCES.autoLoadPhotos
    }
  } catch {
    return DEFAULT_PREFERENCES
  }
}

export function resolvedTheme(preference: ThemePreference, prefersLight: boolean): 'dark' | 'light' {
  if (preference === 'system') return prefersLight ? 'light' : 'dark'
  return preference
}
