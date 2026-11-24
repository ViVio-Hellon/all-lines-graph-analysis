//! Python(`bridge.py`)を子として起動し、標準入出力で要求を渡す。**ポートは使わない。**
//!
//! ```text
//! 要求  {"id": 7, "method": "POST", "path": "/api/x?a=1", "headers": [[k, v]], "len": 12}\n<本文>
//! 応答  {"id": 7, "status": 200, "headers": [[k, v]], "len": 345}\n<本文>
//! 知らせ {"event": "started" | "fatal", ...}\n
//! ```

use std::collections::{HashMap, VecDeque};
use std::io::{BufRead, BufReader, Read, Write};
use std::path::{Path, PathBuf};
use std::process::{Child, ChildStdin, Command, Stdio};
use std::sync::atomic::{AtomicU64, Ordering};
use std::sync::mpsc;
use std::sync::{Arc, Condvar, Mutex};
use std::thread;
use std::time::Duration;

use serde_json::{json, Value};

/// 1件の本文の上限(`bridge.py` の MAX_BODY と同じ)
pub const MAX_BODY: usize = 64 * 1024 * 1024;
/// 起動を待つ上限
const START_TIMEOUT: Duration = Duration::from_secs(60);
/// 1件の応答を待つ上限
const REPLY_TIMEOUT: Duration = Duration::from_secs(300);
const STDERR_LINES: usize = 40;

pub struct Reply {
    pub status: u16,
    pub headers: Vec<(String, String)>,
    pub body: Vec<u8>,
}

#[derive(Clone, Debug, PartialEq)]
pub enum Phase {
    Starting,
    Started,
    Failed(String),
}

type Pending = Arc<Mutex<HashMap<u64, mpsc::Sender<Reply>>>>;

pub struct Bridge {
    root: PathBuf,
    phase: Mutex<Phase>,
    changed: Condvar,
    stdin: Mutex<Option<ChildStdin>>,
    child: Mutex<Option<Child>>,
    pending: Pending,
    next_id: AtomicU64,
    stderr: Arc<Mutex<VecDeque<String>>>,
    python: Mutex<String>,
}

/// Python の候補(`ALG_PYTHON` → python → py -3)
fn candidates() -> Vec<(String, Vec<String>)> {
    let mut out = Vec::new();
    if let Ok(p) = std::env::var("ALG_PYTHON") {
        if !p.trim().is_empty() {
            out.push((p, vec![]));
        }
    }
    if cfg!(windows) {
        out.push(("python.exe".into(), vec![]));
        out.push(("py.exe".into(), vec!["-3".into()]));
    } else {
        out.push(("python3".into(), vec![]));
        out.push(("python".into(), vec![]));
    }
    out
}

impl Bridge {
    pub fn new(root: PathBuf) -> Arc<Self> {
        Arc::new(Self {
            root,
            phase: Mutex::new(Phase::Starting),
            changed: Condvar::new(),
            stdin: Mutex::new(None),
            child: Mutex::new(None),
            pending: Arc::new(Mutex::new(HashMap::new())),
            next_id: AtomicU64::new(1),
            stderr: Arc::new(Mutex::new(VecDeque::new())),
            python: Mutex::new(String::new()),
        })
    }

    pub fn root(&self) -> &Path {
        &self.root
    }

    fn set_phase(&self, phase: Phase) {
        *self.phase.lock().unwrap() = phase;
        self.changed.notify_all();
    }

    pub fn phase(&self) -> Phase {
        self.phase.lock().unwrap().clone()
    }

    /// Python を起こす。見つからなければ理由を Failed に入れる
    pub fn start(self: &Arc<Self>) {
        let script = self.root.join("bridge.py");
        let mut tried = Vec::new();
        for (exe, args) in candidates() {
            let mut cmd = Command::new(&exe);
            cmd.args(&args)
                .arg("-X")
                .arg("utf8")
                .arg(&script)
                .current_dir(&self.root)
                .stdin(Stdio::piped())
                .stdout(Stdio::piped())
                .stderr(Stdio::piped());
            #[cfg(windows)]
            {
                use std::os::windows::process::CommandExt;
                cmd.creation_flags(0x0800_0000); // CREATE_NO_WINDOW: 黒い窓を出さない
            }
            match cmd.spawn() {
                Ok(mut child) => {
                    *self.python.lock().unwrap() = format!("{exe} {}", args.join(" "));
                    let stdout = child.stdout.take().unwrap();
                    let stderr = child.stderr.take().unwrap();
                    *self.stdin.lock().unwrap() = child.stdin.take();
                    *self.child.lock().unwrap() = Some(child);
                    self.read_stderr(stderr);
                    self.read_stdout(stdout);
                    return;
                }
                Err(e) => tried.push(format!("{exe}: {e}")),
            }
        }
        self.set_phase(Phase::Failed(format!(
            "Python が見つかりません({})。Python を入れて「Add python.exe to PATH」にチェックを付けてください。",
            tried.join(" / ")
        )));
    }

    fn read_stderr(self: &Arc<Self>, stderr: impl Read + Send + 'static) {
        let tail = self.stderr.clone();
        thread::spawn(move || {
            for line in BufReader::new(stderr).lines().map_while(Result::ok) {
                let mut t = tail.lock().unwrap();
                if t.len() >= STDERR_LINES {
                    t.pop_front();
                }
                t.push_back(line);
            }
        });
    }

    fn read_stdout(self: &Arc<Self>, stdout: impl Read + Send + 'static) {
        let me = self.clone();
        thread::spawn(move || {
            let mut reader = BufReader::new(stdout);
            loop {
                let mut line = String::new();
                match reader.read_line(&mut line) {
                    Ok(0) | Err(_) => break,
                    Ok(_) => {}
                }
                let head: Value = match serde_json::from_str(line.trim_end()) {
                    Ok(v) => v,
                    Err(_) => break, // 区切りが分からなくなった
                };
                if let Some(event) = head.get("event").and_then(Value::as_str) {
                    match event {
                        "started" => me.set_phase(Phase::Started),
                        "fatal" => me.set_phase(Phase::Failed(
                            head.get("message").and_then(Value::as_str).unwrap_or("起動できませんでした").to_string(),
                        )),
                        _ => {}
                    }
                    continue;
                }
                let len = head.get("len").and_then(Value::as_u64).unwrap_or(0) as usize;
                if len > MAX_BODY {
                    break;
                }
                let mut body = vec![0u8; len];
                if reader.read_exact(&mut body).is_err() {
                    break;
                }
                let id = head.get("id").and_then(Value::as_u64).unwrap_or(0);
                let headers = head
                    .get("headers")
                    .and_then(Value::as_array)
                    .map(|a| {
                        a.iter()
                            .filter_map(|p| Some((p.get(0)?.as_str()?.to_string(), p.get(1)?.as_str()?.to_string())))
                            .collect()
                    })
                    .unwrap_or_default();
                let reply = Reply { status: head.get("status").and_then(Value::as_u64).unwrap_or(500) as u16, headers, body };
                if let Some(tx) = me.pending.lock().unwrap().remove(&id) {
                    let _ = tx.send(reply);
                }
            }
            // 居なくなった(落ちた・終わった)。待っている要求は断る
            me.pending.lock().unwrap().clear();
            if me.phase() != Phase::Started {
                let tail: Vec<String> = me.stderr.lock().unwrap().iter().cloned().collect();
                me.set_phase(Phase::Failed(format!("Python が起動の途中で終わりました。\n{}", tail.join("\n"))));
            } else {
                me.set_phase(Phase::Failed("Python が途中で終わりました。窓を閉じて、もう一度開いてください。".into()));
            }
        });
    }

    /// 起動し終えるまで待つ
    pub fn wait_started(&self) -> Phase {
        let guard = self.phase.lock().unwrap();
        let (guard, _) = self
            .changed
            .wait_timeout_while(guard, START_TIMEOUT, |p| *p == Phase::Starting)
            .unwrap();
        guard.clone()
    }

    /// 要求1件を渡して、応答を待つ
    pub fn request(&self, method: &str, path: &str, headers: Vec<(String, String)>, body: &[u8]) -> Result<Reply, String> {
        if let Phase::Failed(msg) = self.wait_started() {
            return Err(msg);
        }
        if body.len() > MAX_BODY {
            return Err("送るものが大きすぎます".into());
        }
        let id = self.next_id.fetch_add(1, Ordering::SeqCst);
        let (tx, rx) = mpsc::channel();
        self.pending.lock().unwrap().insert(id, tx);
        let head = json!({"id": id, "method": method, "path": path,
                          "headers": headers.iter().map(|(k, v)| vec![k.clone(), v.clone()]).collect::<Vec<_>>(),
                          "len": body.len()});
        let mut data = serde_json::to_vec(&head).unwrap();
        data.push(b'\n');
        data.extend_from_slice(body);
        {
            let mut stdin = self.stdin.lock().unwrap();
            let ok = stdin.as_mut().map(|s| s.write_all(&data).and_then(|_| s.flush()).is_ok()).unwrap_or(false);
            if !ok {
                self.pending.lock().unwrap().remove(&id);
                return Err("Python に渡せませんでした".into());
            }
        }
        rx.recv_timeout(REPLY_TIMEOUT).map_err(|_| {
            self.pending.lock().unwrap().remove(&id);
            "応答がありません".to_string()
        })
    }

    /// どの Python で動いているか(診断用)
    #[allow(dead_code)]
    pub fn python(&self) -> String {
        self.python.lock().unwrap().clone()
    }

    /// 終わる: 標準入力を閉じれば Python も終わる。3秒待って残っていれば止める
    pub fn stop(&self) {
        self.stdin.lock().unwrap().take();
        if let Some(mut child) = self.child.lock().unwrap().take() {
            for _ in 0..30 {
                if let Ok(Some(_)) = child.try_wait() {
                    return;
                }
                thread::sleep(Duration::from_millis(100));
            }
            let _ = child.kill();
            let _ = child.wait();
        }
    }
}

/// exe の置き場所から、`bridge.py` のあるフォルダを探す(上の階層もたどる)。`ALG_ROOT` で指定もできる
pub fn find_root() -> Option<PathBuf> {
    if let Ok(r) = std::env::var("ALG_ROOT") {
        let p = PathBuf::from(r);
        if p.join("bridge.py").is_file() {
            return Some(p);
        }
    }
    let exe = std::env::current_exe().ok()?;
    let mut dir = exe.parent();
    while let Some(d) = dir {
        if d.join("bridge.py").is_file() {
            return Some(d.to_path_buf());
        }
        dir = d.parent();
    }
    None
}
