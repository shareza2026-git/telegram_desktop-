from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_packaged_runtime_uses_only_executable_folder_for_portable_state():
    main_rs = (ROOT / "frontend" / "src-tauri" / "src" / "main.rs").read_text(encoding="utf-8")
    portable = (ROOT / "app" / "telegram" / "portable.py").read_text(encoding="utf-8")

    assert 'executable_dir.join("telegram-api.env")' in main_rs
    assert 'executable_dir.join("telegram-proxies.json")' in main_rs
    assert 'executable_dir.join("telegram-session.session")' in main_rs
    assert 'let transfer_dir_arg = executable_dir.to_string_lossy().into_owned();' in main_rs
    assert "transfer-dir.txt" not in main_rs
    assert "std::env::current_dir()" not in main_rs
    assert 'profile.join("Downloads")' not in main_rs
    assert 'profile.join("Desktop")' not in main_rs
    assert "Path.cwd()" not in portable
    assert "settings.project_root / PORTABLE_FILE_NAME" not in portable


def test_windows_install_keeps_three_portable_files_beside_installed_exe():
    hooks = (ROOT / "frontend" / "src-tauri" / "windows" / "hooks.nsh").read_text(encoding="utf-8")
    tauri_config = (ROOT / "frontend" / "src-tauri" / "tauri.conf.json").read_text(encoding="utf-8")
    windows_config = (ROOT / "frontend" / "src-tauri" / "tauri.windows.conf.json").read_text(encoding="utf-8")

    assert '$INSTDIR\\telegram-session.session' in hooks
    assert '$INSTDIR\\telegram-api.env' in hooks
    assert '$INSTDIR\\telegram-proxies.json' in hooks
    assert 'Delete "$INSTDIR\\telegram-session.session"' not in hooks
    assert '$APPDATA\\local.telegram.desktop\\accounts\\default\\client.session' in hooks
    assert '"binaries/xray"' in windows_config
    assert '"identifier": "local.telegram.desktop"' in tauri_config
    assert '"version": "0.1.20"' in tauri_config
