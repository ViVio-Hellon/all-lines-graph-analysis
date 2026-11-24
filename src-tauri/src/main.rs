//! 全ライン グラフ分析 デスクトップ版の外枠(Rust/Tauri)
//!
//! 担当は「OS の窓とプロセス」だけ。業務の処理(集計CSV・式・保存・設定・ログ)は Python
//! (`bridge.py` → `graphapp/`)が持ち、画面は今までの HTML/JS をそのまま使う。
//!
//! ```text
//! 窓(WebView) ──app://localhost/…──▶ この外枠 ──標準入力──▶ bridge.py(Python)
//!             ◀──────────────────────        ◀──標準出力──
//! ```
//!
//! - **ポートを使わない**: 画面の要求は独自の宛先(`app://`、Windows の WebView2 では
//!   `http://app.localhost/`)で受ける。ネットワークを通らない
//! - **同時に動かさない**: ブラウザ版が動いていれば理由を出して閉じる。2つ目の exe は開かず、
//!   開いている窓を前に出す(`instance.rs`・single-instance)
//! - **閉じるとき**: 保存していない変更があれば画面に訊く。exe が終われば Python も終わる
#![cfg_attr(not(debug_assertions), windows_subsystem = "windows")]

mod bridge;
mod instance;

use std::sync::atomic::{AtomicBool, Ordering};
use std::sync::Arc;
use std::thread;
use std::time::Duration;

use tauri::http::{Response, StatusCode};
use tauri::{AppHandle, Manager, State, WebviewUrl, WebviewWindowBuilder, WindowEvent};

const APP_ID: &str = "all-lines-graph-analysis";
const TITLE: &str = "全ライン グラフ分析";

#[cfg(windows)]
const START_URL: &str = "http://app.localhost/dashboard";
#[cfg(not(windows))]
const START_URL: &str = "app://localhost/dashboard";

struct Shared {
    bridge: Arc<bridge::Bridge>,
    /// 窓の × を画面が受け取ったか
    close_acked: AtomicBool,
}

/// 起動前に出す知らせ(窓がまだ無いので OS の窓で)
fn notice(text: &str) {
    eprintln!("{text}");
    // ALG_QUIET=1 は窓を出さない(押す人のいない自動の確認で止まらないように)
    if std::env::var("ALG_QUIET").map(|v| !v.trim().is_empty()).unwrap_or(false) {
        return;
    }
    #[cfg(windows)]
    unsafe {
        #[link(name = "user32")]
        extern "system" {
            fn MessageBoxW(hwnd: *mut std::ffi::c_void, text: *const u16, caption: *const u16, kind: u32) -> i32;
        }
        let t: Vec<u16> = text.encode_utf16().chain(std::iter::once(0)).collect();
        let c: Vec<u16> = TITLE.encode_utf16().chain(std::iter::once(0)).collect();
        MessageBoxW(std::ptr::null_mut(), t.as_ptr(), c.as_ptr(), 0x40);
    }
}

fn error_page(message: &str, root: &str) -> Vec<u8> {
    let esc = |s: &str| s.replace('&', "&amp;").replace('<', "&lt;").replace('>', "&gt;");
    format!(
        "<!doctype html><meta charset=\"utf-8\"><title>{TITLE}</title>\
         <body style=\"font-family:'Yu Gothic UI',Meiryo,sans-serif;padding:32px;max-width:760px\">\
         <h1 style=\"font-size:20px\">起動できませんでした</h1>\
         <pre style=\"white-space:pre-wrap;background:#fdecea;color:#c62828;padding:12px;border-radius:6px\">{}</pre>\
         <p>次にすること:</p><ul>\
         <li>Python が入っているか確かめてください(コマンドプロンプトで <code>python --version</code>)。</li>\
         <li>理由が分からないときは、予備のブラウザ版(<code>start.bat</code>)を開くと経過が表示されます。</li>\
         <li>起動の記録は <code>%LOCALAPPDATA%\\AllLinesGraph\\logs\\all_lines_graph</code> にあります。</li></ul>\
         <p style=\"color:#5d6675\">アプリのフォルダ: <code>{}</code></p></body>",
        esc(message),
        esc(root)
    )
    .into_bytes()
}

#[tauri::command]
fn close_ack(shared: State<'_, Arc<Shared>>) {
    shared.close_acked.store(true, Ordering::SeqCst);
}

#[tauri::command]
fn quit(app: AppHandle, shared: State<'_, Arc<Shared>>) {
    shared.bridge.stop();
    app.exit(0);
}

fn main() {
    // 1. 同時に動かさない(ブラウザ版・2つ目の exe)
    let (outcome, held) = instance::acquire(APP_ID);
    match outcome {
        instance::Outcome::BrowserRunning => {
            notice("ブラウザ版(Start.vbs / start.bat)が動いています。\nブラウザ版を終えてから開いてください。");
            return;
        }
        instance::Outcome::DesktopRunning | instance::Outcome::Go => {}
    }
    let _held = held; // 終わるまで握る(DesktopRunning のときは single-instance が前に出して終わる)

    // 2. Python(bridge.py)を起こす
    let Some(root) = bridge::find_root() else {
        notice("bridge.py が見つかりません。exe はアプリのフォルダ(Start.vbs と同じ所)に置いてください。");
        return;
    };
    let bridge = bridge::Bridge::new(root);
    if outcome == instance::Outcome::Go {
        bridge.start();
    }
    let shared = Arc::new(Shared { bridge: bridge.clone(), close_acked: AtomicBool::new(false) });

    let for_protocol = bridge.clone();
    let app = tauri::Builder::default()
        // 2つ目の exe: 開かずに、開いている窓を前に出す
        .plugin(tauri_plugin_single_instance::init(|app, _args, _cwd| {
            if let Some(w) = app.get_webview_window("main") {
                let _ = w.unminimize();
                let _ = w.show();
                let _ = w.set_focus();
            }
        }))
        .manage(shared.clone())
        .invoke_handler(tauri::generate_handler![close_ack, quit])
        // 画面の要求を Python へ(ポートを使わない)
        .register_asynchronous_uri_scheme_protocol("app", move |_ctx, request, responder| {
            let bridge = for_protocol.clone();
            thread::spawn(move || {
                let uri = request.uri();
                let path = uri.path_and_query().map(|p| p.as_str().to_string()).unwrap_or_else(|| "/".into());
                let headers: Vec<(String, String)> = request
                    .headers()
                    .iter()
                    .filter_map(|(k, v)| Some((k.as_str().to_string(), v.to_str().ok()?.to_string())))
                    .collect();
                let method = request.method().as_str().to_string();
                let response = match bridge.request(&method, &path, headers, request.body()) {
                    Ok(reply) => {
                        let mut b = Response::builder().status(StatusCode::from_u16(reply.status).unwrap_or(StatusCode::OK));
                        for (k, v) in reply.headers {
                            b = b.header(k, v);
                        }
                        b.body(reply.body).unwrap()
                    }
                    Err(msg) => Response::builder()
                        .status(StatusCode::OK)
                        .header("Content-Type", "text/html; charset=utf-8")
                        .body(error_page(&msg, &bridge.root().display().to_string()))
                        .unwrap(),
                };
                responder.respond(response);
            });
        })
        .setup(move |app| {
            if outcome == instance::Outcome::DesktopRunning {
                // single-instance が前に出せなかった環境でも、2つ目の窓は開かない
                notice("全ライン グラフ分析はもう開いています。開いている窓を使ってください。");
                std::process::exit(0);
            }
            let url = START_URL.parse().expect("URL");
            WebviewWindowBuilder::new(app, "main", WebviewUrl::CustomProtocol(url))
                .title(TITLE)
                .inner_size(1400.0, 900.0)
                .min_inner_size(900.0, 600.0)
                .build()?;
            Ok(())
        })
        .on_window_event(|window, event| {
            if let WindowEvent::CloseRequested { api, .. } = event {
                // 画面に訊く(保存していない変更があれば確かめる)。画面が受けなければ、そのまま閉じる
                api.prevent_close();
                let app = window.app_handle().clone();
                let shared = app.state::<Arc<Shared>>().inner().clone();
                shared.close_acked.store(false, Ordering::SeqCst);
                if let Some(w) = app.get_webview_window("main") {
                    let _ = w.eval("window.ALGDesktop ? window.ALGDesktop.closeRequested() : window.__TAURI__.core.invoke('quit')");
                }
                thread::spawn(move || {
                    thread::sleep(Duration::from_millis(2500));
                    if !shared.close_acked.load(Ordering::SeqCst) {
                        shared.bridge.stop();
                        app.exit(0);
                    }
                });
            }
        })
        .build(tauri::generate_context!())
        .expect("窓を作れませんでした");

    app.run(move |_app, event| {
        if let tauri::RunEvent::Exit = event {
            shared.bridge.stop(); // 取り残さない
        }
    });
}
