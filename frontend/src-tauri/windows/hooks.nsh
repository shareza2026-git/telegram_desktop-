!macro NSIS_HOOK_PREINSTALL
  ; Stop an older installed copy before NSIS replaces the sidecar/executable.
  ; Ignore taskkill errors when the processes are not running.
  nsExec::ExecToLog 'taskkill /F /IM telegram-desktop-backend.exe'
  nsExec::ExecToLog 'taskkill /F /IM telegram-desktop.exe'
  Sleep 700

  ; Remember the original distribution folder. Future account/proxy changes
  ; are mirrored back beside this Setup so the folder is always transferable.
  CreateDirectory "$APPDATA\local.telegram.desktop"
  FileOpen $0 "$APPDATA\local.telegram.desktop\transfer-dir.txt" w
  FileWrite $0 "$EXEDIR"
  FileClose $0

  CreateDirectory "$LOCALAPPDATA\local.telegram.desktop"
  FileOpen $0 "$LOCALAPPDATA\local.telegram.desktop\transfer-dir.txt" w
  FileWrite $0 "$EXEDIR"
  FileClose $0

  ; Seed the real Telethon session before any possible first application launch.
  IfFileExists "$EXEDIR\telegram-session.session" 0 seed_done

  CreateDirectory "$APPDATA\local.telegram.desktop\accounts\default"
  CopyFiles /SILENT "$EXEDIR\telegram-session.session" "$APPDATA\local.telegram.desktop\accounts\default\client.session"

  CreateDirectory "$LOCALAPPDATA\local.telegram.desktop\accounts\default"
  CopyFiles /SILENT "$EXEDIR\telegram-session.session" "$LOCALAPPDATA\local.telegram.desktop\accounts\default\client.session"

seed_done:
  IfFileExists "$EXEDIR\telegram-proxies.json" 0 proxy_done
  CopyFiles /SILENT "$EXEDIR\telegram-proxies.json" "$APPDATA\local.telegram.desktop\proxies.json"
  CopyFiles /SILENT "$EXEDIR\telegram-proxies.json" "$LOCALAPPDATA\local.telegram.desktop\proxies.json"

proxy_done:
  IfFileExists "$EXEDIR\telegram-api.env" 0 api_done
  CopyFiles /SILENT "$EXEDIR\telegram-api.env" "$APPDATA\local.telegram.desktop\settings.env"
  CopyFiles /SILENT "$EXEDIR\telegram-api.env" "$LOCALAPPDATA\local.telegram.desktop\settings.env"

api_done:
!macroend

!macro NSIS_HOOK_POSTINSTALL
  ; Mirror the session beside the installed executable for recovery only when
  ; a seed was explicitly supplied beside this installer.
  IfFileExists "$EXEDIR\telegram-session.session" 0 session_done
  CopyFiles /SILENT "$EXEDIR\telegram-session.session" "$INSTDIR\telegram-session.session"

session_done:
  IfFileExists "$EXEDIR\telegram-proxies.json" 0 proxy_mirror_done
  CopyFiles /SILENT "$EXEDIR\telegram-proxies.json" "$INSTDIR\telegram-proxies.json"

proxy_mirror_done:
  IfFileExists "$EXEDIR\telegram-api.env" 0 api_mirror_done
  CopyFiles /SILENT "$EXEDIR\telegram-api.env" "$INSTDIR\telegram-api.env"

api_mirror_done:
  IfFileExists "$EXEDIR\xray.exe" 0 xray_done
  CopyFiles /SILENT "$EXEDIR\xray.exe" "$INSTDIR\xray.exe"

xray_done:
!macroend
