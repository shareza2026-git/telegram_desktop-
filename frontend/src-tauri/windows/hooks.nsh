!macro NSIS_HOOK_PREINSTALL
  ; Multi-instance update: stop only processes whose executable lives in the
  ; selected $INSTDIR. Sibling Telegram instances in other folders stay alive.
  FileOpen $0 "$TEMP\telegram-stop-instance.ps1" w
  FileWrite $0 "$$root = [System.IO.Path]::GetFullPath('$INSTDIR')$$
"
  FileWrite $0 "$$names = @('telegram-desktop','telegram-desktop-backend','xray')$$
"
  FileWrite $0 "Get-Process -Name $$names -ErrorAction SilentlyContinue | ForEach-Object {$$
"
  FileWrite $0 "  try {$$
"
  FileWrite $0 "    $$path = [System.IO.Path]::GetFullPath($$_.Path)$$
"
  FileWrite $0 "    if ([System.IO.Path]::GetDirectoryName($$path) -ieq $$root) { Stop-Process -Id $$_.Id -Force -ErrorAction SilentlyContinue }$$
"
  FileWrite $0 "  } catch {}$$
"
  FileWrite $0 "}$$
"
  FileClose $0
  nsExec::ExecToLog 'powershell.exe -NoProfile -NonInteractive -ExecutionPolicy Bypass -File "$TEMP\telegram-stop-instance.ps1"'
  Delete "$TEMP\telegram-stop-instance.ps1"
  Sleep 700

  ; Remove only the legacy single-install registration left by <= 0.1.22.
  DeleteRegKey HKCU "Software\Microsoft\Windows\CurrentVersion\Uninstall\Telegram Desktop"
  Delete "$DESKTOP\Telegram Desktop.lnk"
  Delete "$SMPROGRAMS\Telegram Desktop.lnk"
!macroend

!macro NSIS_HOOK_POSTINSTALL
  ; Portable state is maintained by this instance beside its own executable.
!macroend

!macro NSIS_HOOK_PREUNINSTALL
  ; Stop only this instance before removing its files.
  FileOpen $0 "$TEMP\telegram-stop-instance.ps1" w
  FileWrite $0 "$$root = [System.IO.Path]::GetFullPath('$INSTDIR')$$
"
  FileWrite $0 "$$names = @('telegram-desktop','telegram-desktop-backend','xray')$$
"
  FileWrite $0 "Get-Process -Name $$names -ErrorAction SilentlyContinue | ForEach-Object {$$
"
  FileWrite $0 "  try {$$
"
  FileWrite $0 "    $$path = [System.IO.Path]::GetFullPath($$_.Path)$$
"
  FileWrite $0 "    if ([System.IO.Path]::GetDirectoryName($$path) -ieq $$root) { Stop-Process -Id $$_.Id -Force -ErrorAction SilentlyContinue }$$
"
  FileWrite $0 "  } catch {}$$
"
  FileWrite $0 "}$$
"
  FileClose $0
  nsExec::ExecToLog 'powershell.exe -NoProfile -NonInteractive -ExecutionPolicy Bypass -File "$TEMP\telegram-stop-instance.ps1"'
  Delete "$TEMP\telegram-stop-instance.ps1"
  Sleep 700
!macroend

!macro NSIS_HOOK_POSTUNINSTALL
!macroend
