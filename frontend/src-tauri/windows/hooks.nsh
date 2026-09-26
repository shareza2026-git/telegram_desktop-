!macro NSIS_HOOK_PREINSTALL
  ; Stop an older installed copy before NSIS replaces the executable/sidecar.
  nsExec::ExecToLog 'taskkill /F /IM telegram-desktop-backend.exe'
  nsExec::ExecToLog 'taskkill /F /IM telegram-desktop.exe'
  Sleep 700

  CreateDirectory "$APPDATA\local.telegram.desktop"
  CreateDirectory "$LOCALAPPDATA\local.telegram.desktop"
  CreateDirectory "$APPDATA\local.telegram.desktop\accounts\default"
  CreateDirectory "$LOCALAPPDATA\local.telegram.desktop\accounts\default"

  ; Remember the installer folder for portable API/proxy mirrors only.
  FileOpen $0 "$APPDATA\local.telegram.desktop\transfer-dir.txt" w
  FileWrite $0 "$EXEDIR"
  FileClose $0
  FileOpen $0 "$LOCALAPPDATA\local.telegram.desktop\transfer-dir.txt" w
  FileWrite $0 "$EXEDIR"
  FileClose $0

  ; Detect an existing installed version. With the same Tauri identifier and a
  ; higher version, NSIS replaces the old application files in-place.
  StrCpy $9 "0"
  IfFileExists "$INSTDIR\telegram-desktop.exe" 0 update_detected_done
  StrCpy $9 "1"

update_detected_done:
  ; Upgrade-only migration fallback: preserve a legacy session that an older
  ; build stored beside its executable. Existing AppData sessions always win.
  StrCmp $9 "1" 0 session_migrate_done

  IfFileExists "$APPDATA\local.telegram.desktop\accounts\default\client.session" roaming_session_done
  IfFileExists "$INSTDIR\telegram-session.session" 0 roaming_session_done
  CopyFiles /SILENT "$INSTDIR\telegram-session.session" "$APPDATA\local.telegram.desktop\accounts\default\client.session"

roaming_session_done:
  IfFileExists "$LOCALAPPDATA\local.telegram.desktop\accounts\default\client.session" session_migrate_done
  IfFileExists "$INSTDIR\telegram-session.session" 0 session_migrate_done
  CopyFiles /SILENT "$INSTDIR\telegram-session.session" "$LOCALAPPDATA\local.telegram.desktop\accounts\default\client.session"

session_migrate_done:
  ; API/proxy bootstrap may come from beside Setup, but it never includes a
  ; Telegram session. Do not overwrite an existing user's private config.
  IfFileExists "$APPDATA\local.telegram.desktop\proxies.json" roaming_proxy_done
  IfFileExists "$EXEDIR\telegram-proxies.json" 0 roaming_proxy_done
  CopyFiles /SILENT "$EXEDIR\telegram-proxies.json" "$APPDATA\local.telegram.desktop\proxies.json"

roaming_proxy_done:
  IfFileExists "$LOCALAPPDATA\local.telegram.desktop\proxies.json" local_proxy_done
  IfFileExists "$EXEDIR\telegram-proxies.json" 0 local_proxy_done
  CopyFiles /SILENT "$EXEDIR\telegram-proxies.json" "$LOCALAPPDATA\local.telegram.desktop\proxies.json"

local_proxy_done:
  IfFileExists "$APPDATA\local.telegram.desktop\settings.env" roaming_api_done
  IfFileExists "$EXEDIR\telegram-api.env" 0 roaming_api_done
  CopyFiles /SILENT "$EXEDIR\telegram-api.env" "$APPDATA\local.telegram.desktop\settings.env"

roaming_api_done:
  IfFileExists "$LOCALAPPDATA\local.telegram.desktop\settings.env" api_done
  IfFileExists "$EXEDIR\telegram-api.env" 0 api_done
  CopyFiles /SILENT "$EXEDIR\telegram-api.env" "$LOCALAPPDATA\local.telegram.desktop\settings.env"

api_done:
!macroend

!macro NSIS_HOOK_POSTINSTALL
  ; Authorization must live only under the stable per-user AppData directory.
  ; Remove a legacy installed-folder session after it has had a chance to migrate.
  Delete "$INSTDIR\telegram-session.session"

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
