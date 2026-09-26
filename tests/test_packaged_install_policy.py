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
    assert '"version": "0.1.22"' in tauri_config


def test_each_executable_folder_gets_isolated_runtime_state():
    main_rs = (ROOT / "frontend" / "src-tauri" / "src" / "main.rs").read_text(encoding="utf-8")
    desktop = (ROOT / "app" / "desktop.py").read_text(encoding="utf-8")
    frontend_main = (ROOT / "frontend" / "src" / "main.tsx").read_text(encoding="utf-8")
    app_tsx = (ROOT / "frontend" / "src" / "App.tsx").read_text(encoding="utf-8")
    tauri_config = (ROOT / "frontend" / "src-tauri" / "tauri.conf.json").read_text(encoding="utf-8")

    assert 'shared_root.join("instances").join(&instance_id)' in main_rs
    assert 'choose_backend_port(instance_hash)' in main_rs
    assert '"--port"' in main_rs
    assert 'parser.add_argument("--port"' in desktop
    assert 'port=args.port' in desktop
    assert "runtime_backend_port" in frontend_main
    assert "runtime_instance_id" in frontend_main
    assert "instanceStorageKey" in app_tsx
    assert "http://127.0.0.1:*" in tauri_config
    assert "ws://127.0.0.1:*" in tauri_config


def test_windows_installer_is_true_multi_instance():
    windows_config = (ROOT / "frontend" / "src-tauri" / "tauri.windows.conf.json").read_text(encoding="utf-8")
    template = (ROOT / "frontend" / "src-tauri" / "windows" / "installer-multi-instance.nsi").read_text(encoding="utf-8")
    hooks = (ROOT / "frontend" / "src-tauri" / "windows" / "hooks.nsh").read_text(encoding="utf-8")

    assert '"template": "./windows/installer-multi-instance.nsi"' in windows_config
    assert "PageReinstall" not in template
    assert "alreadyInstalledLong" not in template
    assert 'CreateShortcut "$DESKTOP\\$InstanceName.lnk"' in template
    assert 'CreateShortcut "$SMPROGRAMS\\$InstanceName.lnk"' in template
    assert 'StrCpy $INSTDIR "$LOCALAPPDATA\\Telegram Desktop Instances\\$InstanceName"' in template
    assert "taskkill" not in hooks.lower()
    assert "accounts\\default\\client.session" not in hooks
    assert "proxies.json" not in hooks
    assert "settings.env" not in hooks
