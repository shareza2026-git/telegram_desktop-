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
    let builder = tauri::Builder::default()
        .plugin(tauri_plugin_shell::init())
        .invoke_handler(tauri::generate_handler![open_chat_window]);

    #[cfg(not(debug_assertions))]
    let builder = builder.setup(|app| {
        let data_root = app.path().app_data_dir()?;
        std::fs::create_dir_all(&data_root)?;

        let executable = std::env::current_exe()?;
        let executable_dir = executable
            .parent()
            .unwrap_or_else(|| std::path::Path::new("."))
            .to_path_buf();

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
