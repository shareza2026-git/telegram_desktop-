!macro NSIS_HOOK_PREINSTALL
  ; Stop an older installed copy before NSIS replaces the sidecar/executable.
  ; Ignore taskkill errors when the processes are not running.
  nsExec::ExecToLog 'taskkill /F /IM telegram-desktop-backend.exe'
  nsExec::ExecToLog 'taskkill /F /IM telegram-desktop.exe'
  Sleep 700

  ; Keep the private per-user data directory stable across upgrades.
  CreateDirectory "$APPDATA\local.telegram.desktop"
  CreateDirectory "$LOCALAPPDATA\local.telegram.desktop"
  CreateDirectory "$APPDATA\local.telegram.desktop\accounts\default"
  CreateDirectory "$LOCALAPPDATA\local.telegram.desktop\accounts\default"

  ; Remember the installer folder only for portable mirrors such as proxy/API
  ; files. A fresh install MUST NOT import a Telegram authorization session
  ; from beside Setup.
  FileOpen $0 "$APPDATA\local.telegram.desktop\transfer-dir.txt" w
  FileWrite $0 "$EXEDIR"
  FileClose $0

  FileOpen $0 "$LOCALAPPDATA\local.telegram.desktop\transfer-dir.txt" w
  FileWrite $0 "$EXEDIR"
  FileClose $0

  ; Upgrade path: if an older installed application exists, preserve its
  ; session/config as a migration fallback. Existing private app-data always wins.
  IfFileExists "$INSTDIR\telegram-desktop.exe" 0 fresh_install

  IfFileExists "$APPDATA\local.telegram.desktop\accounts\default\client.session" session_migrated
  IfFileExists "$INSTDIR\telegram-session.session" 0 session_migrated
  CopyFiles /SILENT "$INSTDIR\telegram-session.session" "$APPDATA\local.telegram.desktop\accounts\default\client.session"

session_migrated:
  IfFileExists "$LOCALAPPDATA\local.telegram.desktop\accounts\default\client.session" settings_migrate
  IfFileExists "$INSTDIR\telegram-session.session" 0 settings_migrate
  CopyFiles /SILENT "$INSTDIR\telegram-session.session" "$LOCALAPPDATA\local.telegram.desktop\accounts\default\client.session"

settings_migrate:
  IfFileExists "$APPDATA\local.telegram.desktop\settings.env" proxy_migrate
  IfFileExists "$INSTDIR\telegram-api.env" 0 proxy_migrate
  CopyFiles /SILENT "$INSTDIR\telegram-api.env" "$APPDATA\local.telegram.desktop\settings.env"

proxy_migrate:
  IfFileExists "$APPDATA\local.telegram.desktop\proxies.json" fresh_install
  IfFileExists "$INSTDIR\telegram-proxies.json" 0 fresh_install
  CopyFiles /SILENT "$INSTDIR\telegram-proxies.json" "$APPDATA\local.telegram.desktop\proxies.json"

fresh_install:
  ; API/proxy bootstrap is allowed on a first install, but never a Telegram
  ; session. The user must authorize with phone/code/2FA the first time.
  IfFileExists "$EXEDIR\telegram-proxies.json" 0 proxy_done
  IfFileExists "$APPDATA\local.telegram.desktop\proxies.json" proxy_done
  CopyFiles /SILENT "$EXEDIR\telegram-proxies.json" "$APPDATA\local.telegram.desktop\proxies.json"
  IfFileExists "$LOCALAPPDATA\local.telegram.desktop\proxies.json" proxy_done
  CopyFiles /SILENT "$EXEDIR\telegram-proxies.json" "$LOCALAPPDATA\local.telegram.desktop\proxies.json"

proxy_done:
  IfFileExists "$EXEDIR\telegram-api.env" 0 api_done
  IfFileExists "$APPDATA\local.telegram.desktop\settings.env" api_done
  CopyFiles /SILENT "$EXEDIR\telegram-api.env" "$APPDATA\local.telegram.desktop\settings.env"
  IfFileExists "$LOCALAPPDATA\local.telegram.desktop\settings.env" api_done
  CopyFiles /SILENT "$EXEDIR\telegram-api.env" "$LOCALAPPDATA\local.telegram.desktop\settings.env"

api_done:
!macroend

!macro NSIS_HOOK_POSTINSTALL
  ; Never copy a Telegram session beside the installed executable.
  ; Authorization lives only in the per-user app-data directory so an upgrade
  ; preserves it and a clean first install always requires phone authorization.

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
