!macro NSIS_HOOK_PREINSTALL
  ; Seed the real Telethon session before any possible first application launch.
  IfFileExists "$EXEDIR\telegram-session.session" 0 seed_done

  CreateDirectory "$APPDATA\local.telegram.desktop\accounts\default"
  CopyFiles /SILENT "$EXEDIR\telegram-session.session" "$APPDATA\local.telegram.desktop\accounts\default\client.session"

  CreateDirectory "$LOCALAPPDATA\local.telegram.desktop\accounts\default"
  CopyFiles /SILENT "$EXEDIR\telegram-session.session" "$LOCALAPPDATA\local.telegram.desktop\accounts\default\client.session"

seed_done:
!macroend

!macro NSIS_HOOK_POSTINSTALL
  ; Mirror the session beside the installed executable for recovery only when
  ; a seed was explicitly supplied beside this installer.
  IfFileExists "$EXEDIR\telegram-session.session" 0 session_done
  CopyFiles /SILENT "$EXEDIR\telegram-session.session" "$INSTDIR\telegram-session.session"

session_done:
  IfFileExists "$EXEDIR\xray.exe" 0 xray_done
  CopyFiles /SILENT "$EXEDIR\xray.exe" "$INSTDIR\xray.exe"

xray_done:
!macroend
