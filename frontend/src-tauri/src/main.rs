#![cfg_attr(not(debug_assertions), windows_subsystem = "windows")]

#[cfg(not(debug_assertions))]
use std::sync::Mutex;
use tauri::{Manager, WebviewUrl, WebviewWindowBuilder};
#[cfg(not(debug_assertions))]
use tauri::RunEvent;
#[cfg(not(debug_assertions))]
use tauri_plugin_shell::{process::CommandChild, ShellExt};

#[cfg(not(debug_assertions))]
struct BackendProcess(Mutex<Option<CommandChild>>);

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

    let encoded_title = urlencoding::encode(&title);
    let path = format!(
        "index.html?popout=1&chat={}&title={}",
        chat_id, encoded_title
    );

    WebviewWindowBuilder::new(&app, label, WebviewUrl::App(path.into()))
        .title(title)
        .inner_size(760.0, 720.0)
        .min_inner_size(520.0, 420.0)
        .resizable(true)
        .decorations(false)
        .center()
        .build()
        .map_err(|error| error.to_string())?;

    Ok(())
}

fn main() {
    let builder = tauri::Builder::default()
        .plugin(tauri_plugin_shell::init())
        .invoke_handler(tauri::generate_handler![open_chat_window]);

    #[cfg(not(debug_assertions))]
    let builder = builder.setup(|app| {
        let data_root = app.path().app_data_dir()?;
        std::fs::create_dir_all(&data_root)?;

        // Seed the private Telethon session independently from API credentials.
        // A local telegram-session.session beside the installed executable,
        // working directory, Downloads or Desktop is copied only when the
        // per-user client session does not already exist.
        let session_dir = data_root.join("accounts").join("default");
        std::fs::create_dir_all(&session_dir)?;
        let target_session = session_dir.join("client.session");

        if !target_session.is_file() {
            let executable = std::env::current_exe()?;
            let executable_dir = executable
                .parent()
                .unwrap_or_else(|| std::path::Path::new("."))
                .to_path_buf();

            let mut candidates = vec![
                executable_dir.join("telegram-session.session"),
            ];
            if let Ok(current_dir) = std::env::current_dir() {
                candidates.push(current_dir.join("telegram-session.session"));
            }
            if let Some(profile) = std::env::var_os("USERPROFILE") {
                let profile = std::path::PathBuf::from(profile);
                candidates.push(profile.join("Downloads").join("telegram-session.session"));
                candidates.push(profile.join("Desktop").join("telegram-session.session"));
            }

            if let Some(source) = candidates.into_iter().find(|path| path.is_file()) {
                std::fs::copy(source, &target_session)?;
            }
        }

        // Seed proxy routes from a local release package when available.
        // This keeps proxy credentials out of Git while allowing a locally built
        // package to carry the working routes to another Windows profile.
        let target_proxies = data_root.join("proxies.json");
        if !target_proxies.is_file() {
            let executable = std::env::current_exe()?;
            let executable_dir = executable
                .parent()
                .unwrap_or_else(|| std::path::Path::new("."))
                .to_path_buf();

            let mut proxy_candidates = vec![
                executable_dir.join("telegram-proxies.json"),
            ];
            if let Ok(current_dir) = std::env::current_dir() {
                proxy_candidates.push(current_dir.join("telegram-proxies.json"));
            }
            if let Some(profile) = std::env::var_os("USERPROFILE") {
                let profile = std::path::PathBuf::from(profile);
                proxy_candidates.push(profile.join("Downloads").join("telegram-proxies.json"));
                proxy_candidates.push(profile.join("Desktop").join("telegram-proxies.json"));
            }

            if let Some(source) = proxy_candidates.into_iter().find(|path| path.is_file()) {
                std::fs::copy(source, &target_proxies)?;
            }
        }

        // Seed API settings from a local release package when available.
        let target_settings = data_root.join("settings.env");
        if !target_settings.is_file() {
            let executable = std::env::current_exe()?;
            let executable_dir = executable
                .parent()
                .unwrap_or_else(|| std::path::Path::new("."))
                .to_path_buf();

            let mut api_candidates = vec![
                executable_dir.join("telegram-api.env"),
            ];
            if let Ok(current_dir) = std::env::current_dir() {
                api_candidates.push(current_dir.join("telegram-api.env"));
            }
            if let Some(profile) = std::env::var_os("USERPROFILE") {
                let profile = std::path::PathBuf::from(profile);
                api_candidates.push(profile.join("Downloads").join("telegram-api.env"));
                api_candidates.push(profile.join("Desktop").join("telegram-api.env"));
            }

            if let Some(source) = api_candidates.into_iter().find(|path| path.is_file()) {
                std::fs::copy(source, &target_settings)?;
            }
        }

        let data_root_arg = data_root.to_string_lossy().into_owned();
        let executable = std::env::current_exe()?;

        // Prefer the folder the installer was originally launched from so
        // telegram-session.session / telegram-api.env / telegram-proxies.json
        // beside Setup stay current after account changes.
        let transfer_marker = data_root.join("transfer-dir.txt");
        let transfer_dir = std::fs::read_to_string(&transfer_marker)
            .ok()
            .map(|value| std::path::PathBuf::from(value.trim()))
            .filter(|path| path.is_dir())
            .unwrap_or_else(|| {
                executable
                    .parent()
                    .unwrap_or_else(|| std::path::Path::new("."))
                    .to_path_buf()
            });
        let transfer_dir_arg = transfer_dir.to_string_lossy().into_owned();

        let sidecar = app
            .shell()
            .sidecar("telegram-desktop-backend")?
            .args([
                "--data-root",
                data_root_arg.as_str(),
                "--transfer-dir",
                transfer_dir_arg.as_str(),
            ]);
        let (mut events, child) = sidecar.spawn()?;
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
        if let RunEvent::Exit = event {
            let state = app_handle.state::<BackendProcess>();
            if let Ok(mut slot) = state.0.lock() {
                if let Some(child) = slot.take() {
                    let _ = child.kill();
                }
            };
        }
    });
}
