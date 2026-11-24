//! ブラウザ版とデスクトップ版を同時に動かさない(どちらを後から開いても止まる)
//!
//! Python 側の `graphapp/instance_guard.py` と**同じ名前・同じ手順**で錠を扱う。
//! 食い違うと止め損ねるので、名前は試験で突き合わせている(`tests/test_desktop.py`)。
//!
//! 【錠は OS の名前付きの錠にする(ファイルにしない)】
//! Microsoft Store 版の Python は `%LOCALAPPDATA%` に書いたファイルを振り替えるので、
//! exe からは見えない。名前付きミューテックスは振り替えられない。
//! Windows 以外(開発機・試験)は、一時フォルダのファイルの錠で同じことをする。
//!
//! ```text
//! 1. 自分の種類の目印を作る(desktop)
//! 2. 本体の錠を作る
//!    ├─ 作れた                       → 起動してよい(終わるまで握る)
//!    └─ すでにあった
//!       ├─ 相手の目印(browser)がある → ブラウザ版が動いている。止まる
//!       └─ 無い                      → デスクトップ版が動いている(窓を前に出すのは single-instance)
//! ```

#[allow(dead_code)]
pub const BROWSER: &str = "browser";
#[allow(dead_code)]
pub const DESKTOP: &str = "desktop";

/// 錠の名前の頭(Python の `instance_guard.base_name` と同じ規則)
pub fn base_name(app_id: &str) -> String {
    let app_id = if app_id.trim().is_empty() { "all-lines-graph-analysis" } else { app_id.trim() };
    app_id
        .chars()
        .map(|c| if c.is_alphanumeric() || "._-".contains(c) { c } else { '_' })
        .collect()
}

pub struct Names {
    pub instance: String,
    pub desktop: String,
    pub browser: String,
}

pub fn names(app_id: &str) -> Names {
    let base = base_name(app_id);
    Names {
        instance: format!("{base}.instance"),
        desktop: format!("{base}.desktop"),
        browser: format!("{base}.browser"),
    }
}

#[derive(Debug, PartialEq)]
pub enum Outcome {
    /// 起動してよい(錠を握っている)
    Go,
    /// ブラウザ版が動いている
    BrowserRunning,
    /// デスクトップ版がもう動いている
    DesktopRunning,
}

/// 握っている錠(落とすと離す)
pub struct Held(#[allow(dead_code)] Vec<sys::Lock>);

pub fn acquire(app_id: &str) -> (Outcome, Option<Held>) {
    let n = names(app_id);
    let marker = sys::create(&n.desktop);
    match sys::create(&n.instance) {
        Some(instance) => {
            let mut locks = vec![instance];
            if let Some(m) = marker {
                locks.push(m);
            }
            (Outcome::Go, Some(Held(locks)))
        }
        None => {
            drop(marker);
            if sys::exists(&n.browser) {
                (Outcome::BrowserRunning, None)
            } else {
                (Outcome::DesktopRunning, None)
            }
        }
    }
}

#[cfg(windows)]
mod sys {
    use std::ffi::c_void;

    type Handle = *mut c_void;
    const ERROR_ALREADY_EXISTS: u32 = 183;
    const SYNCHRONIZE: u32 = 0x0010_0000;

    #[link(name = "kernel32")]
    extern "system" {
        fn CreateMutexW(attrs: *mut c_void, owner: i32, name: *const u16) -> Handle;
        fn OpenMutexW(access: u32, inherit: i32, name: *const u16) -> Handle;
        fn CloseHandle(h: Handle) -> i32;
        fn GetLastError() -> u32;
    }

    pub struct Lock(Handle);
    unsafe impl Send for Lock {}
    unsafe impl Sync for Lock {}
    impl Drop for Lock {
        fn drop(&mut self) {
            unsafe { CloseHandle(self.0) };
        }
    }

    fn wide(name: &str) -> Vec<u16> {
        format!("Local\\{name}").encode_utf16().chain(std::iter::once(0)).collect()
    }

    /// 作れたら錠を返す。すでにあれば None
    pub fn create(name: &str) -> Option<Lock> {
        let w = wide(name);
        unsafe {
            let h = CreateMutexW(std::ptr::null_mut(), 0, w.as_ptr());
            let existed = GetLastError() == ERROR_ALREADY_EXISTS;
            if h.is_null() {
                return None;
            }
            if existed {
                CloseHandle(h);
                return None;
            }
            Some(Lock(h))
        }
    }

    pub fn exists(name: &str) -> bool {
        let w = wide(name);
        unsafe {
            let h = OpenMutexW(SYNCHRONIZE, 0, w.as_ptr());
            if h.is_null() {
                false
            } else {
                CloseHandle(h);
                true
            }
        }
    }
}

#[cfg(not(windows))]
mod sys {
    use std::fs::{File, OpenOptions};
    use std::path::PathBuf;

    pub struct Lock(#[allow(dead_code)] File);

    fn dir() -> PathBuf {
        match std::env::var("ALG_LOCK_DIR") {
            Ok(d) if !d.trim().is_empty() => PathBuf::from(d),
            _ => std::env::temp_dir(),
        }
    }

    pub fn create(name: &str) -> Option<Lock> {
        let file = OpenOptions::new()
            .create(true)
            .append(true)
            .read(true)
            .open(dir().join(format!("{name}.lock")))
            .ok()?;
        match file.try_lock() {
            Ok(()) => Some(Lock(file)),
            Err(_) => None,
        }
    }

    pub fn exists(name: &str) -> bool {
        match create(name) {
            Some(lock) => {
                drop(lock);
                false
            }
            None => true,
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn names_match_python_rule() {
        let n = names("all-lines-graph-analysis");
        assert_eq!(n.instance, "all-lines-graph-analysis.instance");
        assert_eq!(base_name("a b/c"), "a_b_c");
    }

    #[test]
    fn second_desktop_is_refused_and_browser_is_detected() {
        let dir = std::env::temp_dir().join(format!("alg-lock-test-{}", std::process::id()));
        std::fs::create_dir_all(&dir).unwrap();
        std::env::set_var("ALG_LOCK_DIR", &dir);
        let id = "alg-test-app";
        let (first, held) = acquire(id);
        assert_eq!(first, Outcome::Go);
        assert_eq!(acquire(id).0, Outcome::DesktopRunning);
        drop(held);
        // ブラウザ版が握っている形を作る
        let n = names(id);
        let _browser = sys::create(&n.browser).unwrap();
        let _instance = sys::create(&n.instance).unwrap();
        assert_eq!(acquire(id).0, Outcome::BrowserRunning);
    }
}
