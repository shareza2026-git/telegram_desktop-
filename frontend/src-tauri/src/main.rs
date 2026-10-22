#![cfg_attr(not(debug_assertions), windows_subsystem = "windows")]

#[cfg(not(debug_assertions))]
use std::sync::Mutex;
// Needed in both builds: open_chat_window creates pop-out windows in dev too.
use tauri::{Manager, WebviewUrl, WebviewWindowBuilder};
#[cfg(not(debug_assertions))]
use tauri::RunEvent;
#[cfg(not(debug_assertions))]
use tauri_plugin_shell::process::CommandChild;
use tauri_plugin_shell::ShellExt;

#[cfg(not(debug_assertions))]
struct BackendProcess(Mutex<Option<CommandChild>>);

/// Per-launch secret shared with the backend sidecar. Every API request from
/// the webview carries it, so websites and other local programs cannot use
/// the backend on 127.0.0.1.
struct BackendToken(String);

/// 256 bits from the OS-seeded SipHash keys of std's RandomState, so no extra
/// crate is needed. Each RandomState draws fresh per-process random keys.
#[cfg_attr(debug_assertions, allow(dead_code))]
fn generate_token() -> String {
    use std::collections::hash_map::RandomState;
    use std::hash::{BuildHasher, Hasher};

    let nanos = std::time::SystemTime::now()
        .duration_since(std::time::UNIX_EPOCH)
        .map(|value| value.as_nanos())
        .unwrap_or_default();
    let mut token = String::with_capacity(64);
    for round in 0u64..4 {
        let mut hasher = RandomState::new().build_hasher();
        hasher.write_u64(round);
        hasher.write_u128(nanos);
        hasher.write_u32(std::process::id());
        token.push_str(&format!("{:016x}", hasher.finish()));
    }
    token
}

fn install_dir() -> Result<std::path::PathBuf, String> {
    let exe = std::env::current_exe().map_err(|e| e.to_string())?;
    Ok(exe.parent().unwrap_or_else(|| std::path::Path::new(".")).to_path_buf())
}

fn instance_name(dir: &std::path::Path) -> String {
    std::fs::read_to_string(dir.join("instance-name.txt"))
        .ok()
        .map(|value| value.trim().to_string())
        .filter(|value| !value.is_empty())
        .unwrap_or_else(|| dir.file_name().map(|n| n.to_string_lossy().into_owned()).unwrap_or_default())
}

/// Other accounts = sibling folders that hold a copy of this app.
#[tauri::command]
fn list_instances() -> Result<Vec<(String, String, bool)>, String> {
    let current = install_dir()?;
    let parent = current.parent().ok_or("no parent folder")?;
    let mut values = Vec::new();
    for entry in std::fs::read_dir(parent).map_err(|e| e.to_string())?.flatten() {
        let path = entry.path();
        if path.join("telegram-desktop.exe").is_file() && path.join("telegram-desktop-backend.exe").is_file() {
            values.push((instance_name(&path), path.to_string_lossy().into_owned(), path == current));
        }
    }
    values.sort();
    Ok(values)
}

fn copy_tree(source: &std::path::Path, target: &std::path::Path) -> std::io::Result<()> {
    std::fs::create_dir_all(target)?;
    for entry in std::fs::read_dir(source)? {
        let entry = entry?;
        let destination = target.join(entry.file_name());
        if entry.file_type()?.is_dir() {
            copy_tree(&entry.path(), &destination)?;
        } else {
            std::fs::copy(entry.path(), destination)?;
        }
    }
    Ok(())
}

/// Add Account: copy the program (never the account data) into a sibling
/// folder and start it; the new window asks for the phone number.
#[tauri::command]
async fn add_instance(name: String) -> Result<(), String> {
    let clean: String = name
        .trim()
        .chars()
        .filter(|c| !"\\/:*?\"<>|".contains(*c) && !c.is_control())
        .collect();
    if clean.is_empty() {
        return Err("نام حساب معتبر نیست.".into());
    }
    let current = install_dir()?;
    let parent = current.parent().ok_or("no parent folder")?.to_path_buf();
    let target = parent.join(&clean);
    if target.exists() {
        return Err("پوشه‌ای با این نام از قبل وجود دارد.".into());
    }
    tauri::async_runtime::spawn_blocking(move || -> Result<(), String> {
        // Program files only: this account's data, session and ids stay here.
        let private = ["data", "app.pid", "backend.pid", "instance-id.txt", "instance-name.txt", "telegram-session.session", "uninstall.exe"];
        std::fs::create_dir_all(&target).map_err(|e| e.to_string())?;
        for entry in std::fs::read_dir(&current).map_err(|e| e.to_string())?.flatten() {
            let file_name = entry.file_name();
            if private.iter().any(|item| file_name.to_string_lossy().eq_ignore_ascii_case(item)) {
                continue;
            }
            let destination = target.join(&file_name);
            let result = if entry.path().is_dir() {
                copy_tree(&entry.path(), &destination)
            } else {
                std::fs::copy(entry.path(), &destination).map(|_| ())
            };
            result.map_err(|e| e.to_string())?;
        }
        std::fs::write(target.join("instance-name.txt"), &clean).map_err(|e| e.to_string())?;
        std::process::Command::new(target.join("telegram-desktop.exe"))
            .current_dir(&target)
            .spawn()
            .map_err(|e| e.to_string())?;
        Ok(())
    })
    .await
    .map_err(|e| e.to_string())?
}

/// Switch account: open (or focus) the window of a sibling install.
#[tauri::command]
fn open_instance(path: String) -> Result<(), String> {
    let dir = std::path::PathBuf::from(path);
    let parent = install_dir()?.parent().map(|p| p.to_path_buf());
    if dir.parent().map(|p| p.to_path_buf()) != parent {
        return Err("not a sibling account".into());
    }
    std::process::Command::new(dir.join("telegram-desktop.exe"))
        .current_dir(&dir)
        .spawn()
        .map(|_| ())
        .map_err(|e| e.to_string())
}

#[tauri::command]
fn backend_token(token: tauri::State<'_, BackendToken>) -> String {
    token.0.clone()
}

/// Open a link from a message in the default browser. Only web and mail
/// links are allowed, so a message cannot launch local programs or files.
#[tauri::command]
#[allow(deprecated)]
fn open_external(app: tauri::AppHandle, url: String) -> Result<(), String> {
    let lower = url.to_ascii_lowercase();
    let allowed = ["https://", "http://", "mailto:"]
        .iter()
        .any(|scheme| lower.starts_with(scheme));
    if !allowed || url.chars().any(|c| c.is_control()) {
        return Err("unsupported link".into());
    }
    app.shell().open(url, None).map_err(|error| error.to_string())
}

#[cfg(not(debug_assertions))]
#[derive(Clone)]
struct RuntimeState {
    backend_port: u16,
    instance_id: String,
}

#[cfg(not(debug_assertions))]
fn instance_identity(executable_dir: &std::path::Path) -> (String, u64) {
    let canonical = executable_dir
        .canonicalize()
        .unwrap_or_else(|_| executable_dir.to_path_buf());
    let normalized = canonical.to_string_lossy().to_lowercase();

    // Stable FNV-1a: the same folder keeps the same instance identity across
    // application/Rust upgrades.
    let mut hash = 0xcbf29ce484222325u64;
    for byte in normalized.as_bytes() {
        hash ^= u64::from(*byte);
        hash = hash.wrapping_mul(0x100000001b3);
    }
    (format!("{:016x}", hash), hash)
}

#[cfg(not(debug_assertions))]
fn copy_dir(source: &std::path::Path, target: &std::path::Path) -> std::io::Result<()> {
    std::fs::create_dir_all(target)?;
    for entry in std::fs::read_dir(source)? {
        let entry = entry?;
        let destination = target.join(entry.file_name());
        if entry.file_type()?.is_dir() {
            copy_dir(&entry.path(), &destination)?;
        } else if !destination.exists() {
            std::fs::copy(entry.path(), destination)?;
        }
    }
    Ok(())
}

#[cfg(not(debug_assertions))]
fn portable_data_root(executable_dir: &std::path::Path, legacy_root: &std::path::Path) -> std::path::PathBuf {
    let portable = executable_dir.join("data");
    let probe = portable.join(".write-test");
    let writable = std::fs::create_dir_all(&portable).is_ok()
        && std::fs::write(&probe, b"ok").is_ok();
    let _ = std::fs::remove_file(&probe);
    if !writable {
        return legacy_root.to_path_buf();
    }
    let has_session = portable.join("accounts").join("default").join("client.session").is_file();
    if !has_session && legacy_root.is_dir() {
        let _ = copy_dir(legacy_root, &portable);
    }
    portable
}

#[cfg(not(debug_assertions))]
fn backend_port_for_instance(hash: u64) -> u16 {
    // Stable port per executable folder. Reopening the same instance must never
    // create a second backend against the same Telegram session/database.
    20000 + (hash % 30000) as u16
}

#[cfg(not(debug_assertions))]
#[tauri::command]
fn runtime_backend_port(state: tauri::State<RuntimeState>) -> u16 {
    state.backend_port
}

#[cfg(debug_assertions)]
#[tauri::command]
fn runtime_backend_port() -> u16 {
    8110
}

#[cfg(not(debug_assertions))]
#[tauri::command]
fn runtime_instance_id(state: tauri::State<RuntimeState>) -> String {
    state.instance_id.clone()
}

#[cfg(not(debug_assertions))]
fn stop_instance_backend(state: &BackendProcess) {
    if let Ok(mut slot) = state.0.lock() {
        if let Some(child) = slot.take() {
            let _ = child.kill();
        }
    }
}

#[cfg(not(debug_assertions))]
#[tauri::command]
fn close_current_window(
    app: tauri::AppHandle,
    window: tauri::WebviewWindow,
    state: tauri::State<BackendProcess>,
) -> Result<(), String> {
    if app.webview_windows().len() <= 1 {
        stop_instance_backend(state.inner());
    }
    window.close().map_err(|error| error.to_string())
}

#[cfg(debug_assertions)]
#[tauri::command]
fn close_current_window(window: tauri::WebviewWindow) -> Result<(), String> {
    window.close().map_err(|error| error.to_string())
}

#[cfg(debug_assertions)]
#[tauri::command]
fn runtime_instance_id() -> String {
    "development".to_string()
}

#[tauri::command]
async fn open_chat_window(
    app: tauri::AppHandle,
    chat_id: i64,
    title: String,
) -> Result<(), String> {
    let label = if chat_id < 0 {
        format!("chat-n{}", chat_id.unsigned_abs())
    } else {
        format!("chat-{}", chat_id)
    };

    if let Some(window) = app.get_webview_window(&label) {
        window.show().map_err(|error| error.to_string())?;
        window.set_focus().map_err(|error| error.to_string())?;
        return Ok(());
    }

    let path = format!("index.html?popout=1&chat={}", chat_id);

    WebviewWindowBuilder::new(&app, label, WebviewUrl::App(path.into()))
        .title(title)
        .inner_size(410.0, 520.0)
        .min_inner_size(320.0, 360.0)
        .resizable(true)
        .decorations(false)
        .center()
        .build()
        .map_err(|error| error.to_string())?;

    Ok(())
}

fn main() {
    // In development the backend is started by scripts/run-dev.ps1, which
    // exports the same token to both processes.
    #[cfg(debug_assertions)]
    let token = std::env::var("TELEGRAM_DESKTOP_TOKEN").unwrap_or_default();
    #[cfg(not(debug_assertions))]
    let token = generate_token();

    let builder = tauri::Builder::default()
        .plugin(tauri_plugin_shell::init())
        .manage(BackendToken(token))
        .invoke_handler(tauri::generate_handler![
            open_chat_window,
            runtime_backend_port,
            runtime_instance_id,
            close_current_window,
            backend_token,
            open_external,
            list_instances,
            add_instance,
            open_instance
        ]);

    #[cfg(not(debug_assertions))]
    let builder = builder.setup(|app| {
        let executable = std::env::current_exe()?;
        let executable_dir = executable
            .parent()
            .unwrap_or_else(|| std::path::Path::new("."))
            .to_path_buf();

        // Each executable folder is a fully isolated Telegram instance.
        // Different copies on the same Windows account get different AppData,
        // database/session state, WebSocket backend ports and frontend storage.
        let (instance_id, instance_hash) = instance_identity(&executable_dir);
        let backend_port = backend_port_for_instance(instance_hash);
        std::fs::write(executable_dir.join("instance-id.txt"), &instance_id)?;
        // All state lives in a "data" folder inside the install folder, so
        // copying the folder to another PC moves the account, settings and
        // cache with it, and installing an update over it keeps everything.
        // Older builds kept it in AppData; move that once. If the folder is
        // not writable (e.g. Program Files), fall back to AppData.
        let legacy_root = app.path().app_data_dir()?.join("instances").join(&instance_id);
        let data_root = portable_data_root(&executable_dir, &legacy_root);
        std::fs::create_dir_all(&data_root)?;
        app.manage(RuntimeState {
            backend_port,
            instance_id: instance_id.clone(),
        });

        // Portable state is deliberately tied to the actual executable folder.
        // Do not inspect the working directory, Desktop, Downloads, or shortcut
        // locations. Moving the application folder to another Windows machine
        // therefore moves exactly the same API/proxy/session state with it.
        let account_dir = data_root.join("accounts").join("default");
        std::fs::create_dir_all(&account_dir)?;

        let portable_files = [
            (
                executable_dir.join("telegram-api.env"),
                data_root.join("settings.env"),
            ),
            (
                executable_dir.join("telegram-proxies.json"),
                data_root.join("proxies.json"),
            ),
            (
                executable_dir.join("telegram-session.session"),
                account_dir.join("client.session"),
            ),
        ];
        for (source, target) in portable_files {
            if !target.is_file() && source.is_file() {
                std::fs::copy(source, target)?;
            }
        }

        let data_root_arg = data_root.to_string_lossy().into_owned();
        let transfer_dir_arg = executable_dir.to_string_lossy().into_owned();
        let backend_port_arg = backend_port.to_string();
        let parent_pid_arg = std::process::id().to_string();

        let token = app.state::<BackendToken>().0.clone();
        let sidecar = app
            .shell()
            .sidecar("telegram-desktop-backend")?
            .env("TELEGRAM_DESKTOP_TOKEN", token)
            .args([
                "--data-root",
                data_root_arg.as_str(),
                "--transfer-dir",
                transfer_dir_arg.as_str(),
                "--port",
                backend_port_arg.as_str(),
                "--parent-pid",
                parent_pid_arg.as_str(),
            ]);
        let (mut events, child) = sidecar.spawn()?;
        let _ = std::fs::write(executable_dir.join("app.pid"), std::process::id().to_string());
        let _ = std::fs::write(executable_dir.join("backend.pid"), child.pid().to_string());
        tauri::async_runtime::spawn(async move {
            while events.recv().await.is_some() {}
        });
        app.manage(BackendProcess(Mutex::new(Some(child))));
        Ok(())
    });

    let app = builder
        .build(tauri::generate_context!())
        .expect("error while building Telegram Desktop");

    app.run(|app_handle, event| {
        #[cfg(not(debug_assertions))]
        if matches!(event, RunEvent::ExitRequested { .. } | RunEvent::Exit) {
            let state = app_handle.state::<BackendProcess>();
            stop_instance_backend(state.inner());
            if let Ok(executable) = std::env::current_exe() {
                if let Some(directory) = executable.parent() {
                    let _ = std::fs::remove_file(directory.join("app.pid"));
                    let _ = std::fs::remove_file(directory.join("backend.pid"));
                }
            }
        }
    });
}
