!macro NSIS_HOOK_POSTINSTALL
  ; Import a portable Telegram bundle placed beside the installer itself.
  ; This runs before the installed application can be launched from the
  ; installer's finish page, so the backend is configured on first start.
  IfFileExists "$EXEDIR\telegram-portable.json" 0 portable_done

  CreateDirectory "$APPDATA\local.telegram.desktop\portable"
  CopyFiles /SILENT "$EXEDIR\telegram-portable.json" "$APPDATA\local.telegram.desktop\portable\telegram-portable.json"

  ; Keep a second copy under LocalAppData for compatibility with Windows/Tauri
  ; path differences and mirror one beside the installed executable.
  CreateDirectory "$LOCALAPPDATA\local.telegram.desktop\portable"
  CopyFiles /SILENT "$EXEDIR\telegram-portable.json" "$LOCALAPPDATA\local.telegram.desktop\portable\telegram-portable.json"
  CopyFiles /SILENT "$EXEDIR\telegram-portable.json" "$INSTDIR\telegram-portable.json"

portable_done:
  IfFileExists "$EXEDIR\xray.exe" 0 xray_done
  CopyFiles /SILENT "$EXEDIR\xray.exe" "$INSTDIR\xray.exe"

xray_done:
!macroend
