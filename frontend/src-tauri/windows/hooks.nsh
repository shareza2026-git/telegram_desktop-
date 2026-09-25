!macro NSIS_HOOK_PREINSTALL
  ; Seed the portable bundle before any possible first application launch.
  IfFileExists "$EXEDIR\telegram-portable.json" 0 pre_xray

  CreateDirectory "$APPDATA\local.telegram.desktop\portable"
  CopyFiles /SILENT "$EXEDIR\telegram-portable.json" "$APPDATA\local.telegram.desktop\portable\telegram-portable.json"

  CreateDirectory "$LOCALAPPDATA\local.telegram.desktop\portable"
  CopyFiles /SILENT "$EXEDIR\telegram-portable.json" "$LOCALAPPDATA\local.telegram.desktop\portable\telegram-portable.json"

pre_xray:
!macroend

!macro NSIS_HOOK_POSTINSTALL
  ; Mirror again after installation and also keep a copy beside the app.
  IfFileExists "$EXEDIR\telegram-portable.json" 0 portable_done

  CreateDirectory "$APPDATA\local.telegram.desktop\portable"
  CopyFiles /SILENT "$EXEDIR\telegram-portable.json" "$APPDATA\local.telegram.desktop\portable\telegram-portable.json"

  CreateDirectory "$LOCALAPPDATA\local.telegram.desktop\portable"
  CopyFiles /SILENT "$EXEDIR\telegram-portable.json" "$LOCALAPPDATA\local.telegram.desktop\portable\telegram-portable.json"

  CopyFiles /SILENT "$EXEDIR\telegram-portable.json" "$INSTDIR\telegram-portable.json"

portable_done:
  IfFileExists "$EXEDIR\xray.exe" 0 xray_done
  CopyFiles /SILENT "$EXEDIR\xray.exe" "$INSTDIR\xray.exe"

xray_done:
!macroend
