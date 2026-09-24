#![cfg_attr(not(debug_assertions), windows_subsystem = "windows")]

#[cfg(not(debug_assertions))]
use std::sync::Mutex;
#[cfg(not(debug_assertions))]
use tauri::{Manager, RunEvent};
#[cfg(not(debug_assertions))]
use tauri_plugin_shell::{process::CommandChild, ShellExt};

#[cfg(not(debug_assertions))]
struct BackendProcess(Mutex<Option<CommandChild>>);

fn main() {
    let builder = tauri::Builder::default().plugin(tauri_plugin_shell::init());

    #[cfg(not(debug_assertions))]
    let builder = builder.setup(|app| {
        let data_root = app.path().app_data_dir()?;
        std::fs::create_dir_all(&data_root)?;
        let data_root_arg = data_root.to_string_lossy().into_owned();
        let sidecar = app
            .shell()
            .sidecar("telegram-desktop-backend")?
            .args(["--data-root", data_root_arg.as_str()]);
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
            }
        }
    });
}
