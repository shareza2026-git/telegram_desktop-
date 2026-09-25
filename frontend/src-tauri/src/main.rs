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

        // Keep account/session state outside the installed binaries so upgrades
        // can replace the application without replacing the user's Telegram state.
        let portable_dir = data_root.join("portable");
        std::fs::create_dir_all(&portable_dir)?;
        let canonical_portable = portable_dir.join("telegram-portable.json");

        // A bundle beside the installed executable is treated as a portable
        // bootstrap/mirror. Import it only when this Windows profile has no
        // canonical bundle yet; afterwards AppData is authoritative.
        let executable = std::env::current_exe()?;
        let external_portable = executable
            .parent()
            .unwrap_or_else(|| std::path::Path::new("."))
            .join("telegram-portable.json");
        if !canonical_portable.is_file() && external_portable.is_file() {
            std::fs::copy(&external_portable, &canonical_portable)?;
        }

        let data_root_arg = data_root.to_string_lossy().into_owned();
        let canonical_arg = canonical_portable.to_string_lossy().into_owned();
        let external_arg = external_portable.to_string_lossy().into_owned();

        let mut args = vec![
            "--data-root".to_string(),
            data_root_arg,
            "--portable-config".to_string(),
            canonical_arg,
        ];
        if external_portable.is_file() {
            args.push("--portable-mirror".to_string());
            args.push(external_arg);
        }

        let sidecar = app
            .shell()
            .sidecar("telegram-desktop-backend")?
            .args(args);
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
