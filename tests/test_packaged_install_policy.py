from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_packaged_build_requires_phone_when_private_session_is_missing():
    desktop = (ROOT / "app" / "desktop.py").read_text(encoding="utf-8")
    main_rs = (ROOT / "frontend" / "src-tauri" / "src" / "main.rs").read_text(encoding="utf-8")
    hooks = (ROOT / "frontend" / "src-tauri" / "windows" / "hooks.nsh").read_text(encoding="utf-8")

    assert 'os.environ["TELEGRAM_SOURCE_SESSION_PATH"] = ""' in desktop
    assert 'os.environ["TELEGRAM_AUTO_IMPORT_SOURCE"] = "false"' in desktop
    assert "$EXEDIR\\telegram-session.session" not in hooks
    assert "Seed the private Telethon session" not in main_rs


def test_windows_upgrade_preserves_private_session_and_replaces_old_app():
    hooks = (ROOT / "frontend" / "src-tauri" / "windows" / "hooks.nsh").read_text(encoding="utf-8")
    tauri_config = (ROOT / "frontend" / "src-tauri" / "tauri.conf.json").read_text(encoding="utf-8")

    assert '$INSTDIR\\telegram-desktop.exe' in hooks
    assert '$INSTDIR\\telegram-session.session' in hooks
    assert '$APPDATA\\local.telegram.desktop\\accounts\\default\\client.session' in hooks
    assert 'Delete "$INSTDIR\\telegram-session.session"' in hooks
    assert '"identifier": "local.telegram.desktop"' in tauri_config
    assert '"version": "0.1.17"' in tauri_config
