use std::{
    path::PathBuf,
    process::Command,
    sync::atomic::{AtomicU64, Ordering},
};
use tmuxx_core::{ClientContext, Engine};

pub struct Pair {
    oracle: PathBuf,
    socket: PathBuf,
    engine: Engine,
    context: ClientContext,
}
impl Pair {
    #[allow(dead_code)]
    pub fn feed(&mut self, target: &str, pane: u64, bytes: &[u8], chunk: usize) {
        use std::io::Write;
        use std::process::Stdio;
        let mut child = Command::new(&self.oracle)
            .arg("-S")
            .arg(&self.socket)
            .args(["display-message", "-I", "-t", target])
            .stdin(Stdio::piped())
            .stdout(Stdio::piped())
            .stderr(Stdio::piped())
            .spawn()
            .unwrap();
        child.stdin.take().unwrap().write_all(bytes).unwrap();
        let output = child.wait_with_output().unwrap();
        assert!(
            output.status.success(),
            "feed: {}",
            String::from_utf8_lossy(&output.stderr)
        );
        for bytes in bytes.chunks(chunk.max(1)) {
            self.engine.feed(pane, bytes);
        }
    }
    pub fn new() -> Self {
        let oracle = std::env::var_os("TMUXX_C_TMUX")
            .expect("set TMUXX_C_TMUX to the C reference executable")
            .into();
        static NEXT: AtomicU64 = AtomicU64::new(0);
        let socket = PathBuf::from(format!(
            "/tmp/tx-opt-{}-{}",
            std::process::id(),
            NEXT.fetch_add(1, Ordering::Relaxed)
        ));
        let mut pair = Self {
            oracle,
            socket,
            engine: Engine::default(),
            context: ClientContext::default(),
        };
        pair.run(&[
            "new-session",
            "-d",
            "-s",
            "main",
            "-n",
            "initial",
            "-x",
            "80",
            "-y",
            "24",
            "sleep 120",
        ]);
        pair
    }
    pub fn run(&mut self, args: &[&str]) {
        self.compare(args, None);
    }
    #[allow(dead_code)]
    pub fn diagnostic_difference(&mut self, args: &[&str], rust: &str, c: &[&str]) {
        self.compare(args, Some((rust, c)));
    }
    fn compare(&mut self, args: &[&str], diagnostics: Option<(&str, &[&str])>) {
        let expected = Command::new(&self.oracle)
            .env("SHELL", "/bin/sh")
            .env_remove("EDITOR")
            .env_remove("VISUAL")
            .arg("-S")
            .arg(&self.socket)
            .arg("-f")
            .arg("/dev/null")
            .args(args)
            .output()
            .unwrap();
        let command = tmuxx_command::parse_argv(args.iter().map(|s| s.as_bytes())).unwrap();
        let actual = self.engine.execute(&command[0], &mut self.context);
        let (success, stdout, stderr) = match actual {
            Ok(outcome) => (true, outcome.output, Vec::new()),
            Err(error) => (false, Vec::new(), format!("{error}\n").into_bytes()),
        };
        assert_eq!(
            success,
            expected.status.success(),
            "status {args:?}: {}",
            String::from_utf8_lossy(&expected.stderr)
        );
        if stdout != expected.stdout {
            let actual = String::from_utf8_lossy(&stdout);
            let wanted = String::from_utf8_lossy(&expected.stdout);
            let mismatch = actual
                .lines()
                .zip(wanted.lines())
                .position(|(a, b)| a != b)
                .unwrap_or_else(|| actual.lines().count().min(wanted.lines().count()));
            panic!(
                "stdout {args:?} at line {mismatch}: actual {:?}, expected {:?}; byte lengths {} and {}",
                actual.lines().nth(mismatch),
                wanted.lines().nth(mismatch),
                stdout.len(),
                expected.stdout.len()
            );
        }
        if let Some((rust, c)) = diagnostics {
            assert!(!success, "expected rejection: {args:?}");
            assert_eq!(stderr, rust.as_bytes());
            assert!(
                c.iter()
                    .any(|diagnostic| diagnostic.as_bytes() == expected.stderr),
                "C diagnostic for {args:?}: {:?}",
                String::from_utf8_lossy(&expected.stderr)
            );
        } else {
            assert_eq!(stderr, expected.stderr, "stderr {args:?}");
        }
    }
}
impl Drop for Pair {
    fn drop(&mut self) {
        let _ = Command::new(&self.oracle)
            .arg("-S")
            .arg(&self.socket)
            .arg("kill-server")
            .output();
    }
}
