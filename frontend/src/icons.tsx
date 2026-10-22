// Line icons in the style of Telegram Desktop's menus (24px grid, 1.6px stroke).
const PATHS: Record<string, string> = {
  account: 'M12 12a4 4 0 1 0 0-8 4 4 0 0 0 0 8Zm-7 8a7 7 0 0 1 14 0',
  group: 'M9 11a3.5 3.5 0 1 0 0-7 3.5 3.5 0 0 0 0 7Zm-6 9a6 6 0 0 1 12 0m1-9a3 3 0 1 0 0-6m2.5 15a5 5 0 0 0-3-4.6',
  channel: 'M4 10v4h3l6 4V6L7 10H4Zm13-1.5a4 4 0 0 1 0 7',
  contacts: 'M12 12a3.5 3.5 0 1 0 0-7 3.5 3.5 0 0 0 0 7Zm-6 8a6 6 0 0 1 12 0M4 4h16v16H4z',
  calls: 'M6.5 3.5 9 3l1.5 4-2 1.5a10 10 0 0 0 5 5l1.5-2 4 1.5-.5 2.5a2 2 0 0 1-2 1.5A14 14 0 0 1 5 5.5a2 2 0 0 1 1.5-2Z',
  saved: 'M7 3h10v18l-5-4-5 4z',
  settings: 'M12 15a3 3 0 1 0 0-6 3 3 0 0 0 0 6Zm7.4-3a7.4 7.4 0 0 0-.1-1.3l2-1.6-2-3.4-2.4 1a7.5 7.5 0 0 0-2.2-1.3L14.3 3h-4l-.4 2.4a7.5 7.5 0 0 0-2.2 1.3l-2.4-1-2 3.4 2 1.6a7.4 7.4 0 0 0 0 2.6l-2 1.6 2 3.4 2.4-1a7.5 7.5 0 0 0 2.2 1.3l.4 2.4h4l.4-2.4a7.5 7.5 0 0 0 2.2-1.3l2.4 1 2-3.4-2-1.6c.1-.4.1-.9.1-1.3Z',
  forward: 'M14 5l7 7-7 7M21 12H9a6 6 0 0 0-6 6',
  night: 'M20 14.5A8 8 0 0 1 9.5 4 8 8 0 1 0 20 14.5Z',
  help: 'M12 21a9 9 0 1 0 0-18 9 9 0 0 0 0 18Zm-2.5-11.5a2.5 2.5 0 1 1 3.5 2.3c-.6.3-1 .8-1 1.5V14m0 3v.01',
  bolt: 'M13 3 5 13h6l-1 8 8-10h-6l1-8Z',
  reply: 'M10 7 4 12l6 5m-6-5h10a6 6 0 0 1 6 6v1',
  smile: 'M12 21a9 9 0 1 0 0-18 9 9 0 0 0 0 18Zm-3.5-7.5a4.5 4.5 0 0 0 7 0M9 9.5v.01M15 9.5v.01',
  copy: 'M9 9h11v11H9zM5 15H4V4h11v1',
  select: 'M12 21a9 9 0 1 0 0-18 9 9 0 0 0 0 18Zm-4-9 3 3 5-6',
  edit: 'M4 20h4L19 9l-4-4L4 16v4Zm9-13 4 4',
  trash: 'M4 7h16M9 7V4h6v3m-9 0 1 13h10l1-13',
  pin: 'M15 4l5 5-3 1-3 3 .5 3.5-1.5 1.5-3.5-3.5L5 19m4.5-6L6 9.5 7.5 8 11 8.5l3-3z',
  mute: 'M4 9h4l5-4v14l-5-4H4zm13 0 4 6m0-6-4 6',
  archive: 'M4 5h16v4H4zm1 4v10h14V9m-9 4h4',
  window: 'M4 5h16v14H4zm0 4h16',
  search: 'M11 18a7 7 0 1 0 0-14 7 7 0 0 0 0 14Zm5-2 4 4',
  chats: 'M4 5h16v11H9l-5 4V5Z',
  addAccount: 'M10 12a4 4 0 1 0 0-8 4 4 0 0 0 0 8Zm-7 8a7 7 0 0 1 11-5.7M18 14v6m-3-3h6'
}

export function Icon({ name, className = '' }: { name: keyof typeof PATHS | string; className?: string }) {
  return (
    <svg className={'tg-icon ' + className} viewBox="0 0 24 24" aria-hidden="true">
      <path d={PATHS[name] || PATHS.help} fill="none" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" strokeLinejoin="round" />
    </svg>
  )
}
