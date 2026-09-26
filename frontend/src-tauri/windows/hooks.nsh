!macro NSIS_HOOK_PREINSTALL
  ; Multi-instance installer: never kill, copy from, or mutate another instance.
  ; Remove only the legacy single-install registration left by <= 0.1.22 so it
  ; cannot trigger Windows maintenance behavior again. Existing files remain.
  DeleteRegKey HKCU "Software\Microsoft\Windows\CurrentVersion\Uninstall\Telegram Desktop"
!macroend

!macro NSIS_HOOK_POSTINSTALL
  ; Portable session/API/proxy state is created and maintained by this instance
  ; beside its own telegram-desktop.exe after first launch/login.
!macroend

!macro NSIS_HOOK_PREUNINSTALL
  ; The custom installer template removes only this instance's files/data.
!macroend

!macro NSIS_HOOK_POSTUNINSTALL
!macroend
