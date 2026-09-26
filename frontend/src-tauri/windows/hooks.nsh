!macro NSIS_HOOK_PREINSTALL
  ; Stop an older installed copy before NSIS replaces the executable/sidecars.
  nsExec::ExecToLog 'taskkill /F /IM telegram-desktop-backend.exe'
  nsExec::ExecToLog 'taskkill /F /IM telegram-desktop.exe'
  Sleep 700

  CreateDirectory "$APPDATA\local.telegram.desktop"
  CreateDirectory "$LOCALAPPDATA\local.telegram.desktop"
  CreateDirectory "$APPDATA\local.telegram.desktop\accounts\default"
  CreateDirectory "$LOCALAPPDATA\local.telegram.desktop\accounts\default"

  ; Upgrade fallback for very old builds that kept the session beside the EXE.
  IfFileExists "$APPDATA\local.telegram.desktop\accounts\default\client.session" roaming_session_ready
  IfFileExists "$INSTDIR\telegram-session.session" 0 roaming_session_ready
  CopyFiles /SILENT "$INSTDIR\telegram-session.session" "$APPDATA\local.telegram.desktop\accounts\default\client.session"

roaming_session_ready:
  IfFileExists "$LOCALAPPDATA\local.telegram.desktop\accounts\default\client.session" local_session_ready
  IfFileExists "$INSTDIR\telegram-session.session" 0 local_session_ready
  CopyFiles /SILENT "$INSTDIR\telegram-session.session" "$LOCALAPPDATA\local.telegram.desktop\accounts\default\client.session"

local_session_ready:
  ; A packaged portable set may sit beside Setup. Import it only during install;
  ; runtime lookup after installation is intentionally EXE-folder-only.
  IfFileExists "$APPDATA\local.telegram.desktop\accounts\default\client.session" setup_session_roaming_done
  IfFileExists "$EXEDIR\telegram-session.session" 0 setup_session_roaming_done
  CopyFiles /SILENT "$EXEDIR\telegram-session.session" "$APPDATA\local.telegram.desktop\accounts\default\client.session"

setup_session_roaming_done:
  IfFileExists "$LOCALAPPDATA\local.telegram.desktop\accounts\default\client.session" setup_session_done
  IfFileExists "$EXEDIR\telegram-session.session" 0 setup_session_done
  CopyFiles /SILENT "$EXEDIR\telegram-session.session" "$LOCALAPPDATA\local.telegram.desktop\accounts\default\client.session"

setup_session_done:
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
  ; Keep the three portable state files beside the actual installed executable.
  ; Prefer the current private AppData copy, with Setup-side files as fallback.

  IfFileExists "$APPDATA\local.telegram.desktop\accounts\default\client.session" 0 session_from_local
  CopyFiles /SILENT "$APPDATA\local.telegram.desktop\accounts\default\client.session" "$INSTDIR\telegram-session.session"
  Goto session_done

session_from_local:
  IfFileExists "$LOCALAPPDATA\local.telegram.desktop\accounts\default\client.session" 0 session_from_setup
  CopyFiles /SILENT "$LOCALAPPDATA\local.telegram.desktop\accounts\default\client.session" "$INSTDIR\telegram-session.session"
  Goto session_done

session_from_setup:
  IfFileExists "$EXEDIR\telegram-session.session" 0 session_done
  CopyFiles /SILENT "$EXEDIR\telegram-session.session" "$INSTDIR\telegram-session.session"

session_done:
  IfFileExists "$APPDATA\local.telegram.desktop\proxies.json" 0 proxy_from_local
  CopyFiles /SILENT "$APPDATA\local.telegram.desktop\proxies.json" "$INSTDIR\telegram-proxies.json"
  Goto proxy_done

proxy_from_local:
  IfFileExists "$LOCALAPPDATA\local.telegram.desktop\proxies.json" 0 proxy_from_setup
  CopyFiles /SILENT "$LOCALAPPDATA\local.telegram.desktop\proxies.json" "$INSTDIR\telegram-proxies.json"
  Goto proxy_done

proxy_from_setup:
  IfFileExists "$EXEDIR\telegram-proxies.json" 0 proxy_done
  CopyFiles /SILENT "$EXEDIR\telegram-proxies.json" "$INSTDIR\telegram-proxies.json"

proxy_done:
  IfFileExists "$APPDATA\local.telegram.desktop\settings.env" 0 api_from_local
  CopyFiles /SILENT "$APPDATA\local.telegram.desktop\settings.env" "$INSTDIR\telegram-api.env"
  Goto api_done_post

api_from_local:
  IfFileExists "$LOCALAPPDATA\local.telegram.desktop\settings.env" 0 api_from_setup
  CopyFiles /SILENT "$LOCALAPPDATA\local.telegram.desktop\settings.env" "$INSTDIR\telegram-api.env"
  Goto api_done_post

api_from_setup:
  IfFileExists "$EXEDIR\telegram-api.env" 0 api_done_post
  CopyFiles /SILENT "$EXEDIR\telegram-api.env" "$INSTDIR\telegram-api.env"

api_done_post:
  ; Local release packages may also carry Xray beside Setup. CI builds bundle
  ; xray.exe directly, so this is only a compatibility fallback.
  IfFileExists "$EXEDIR\xray.exe" 0 xray_done
  CopyFiles /SILENT "$EXEDIR\xray.exe" "$INSTDIR\xray.exe"

xray_done:
!macroend
