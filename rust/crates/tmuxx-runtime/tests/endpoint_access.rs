#![cfg(unix)]

use std::os::unix::fs::{FileTypeExt, MetadataExt, PermissionsExt, symlink};
use std::os::unix::net::UnixStream;
use std::path::{Path, PathBuf};
use std::time::{Duration, SystemTime, UNIX_EPOCH};

struct Directory(PathBuf);
impl Directory {
    fn new() -> Self {
        let path = PathBuf::from("/tmp").join(format!(
            "tmuxx-access-{}-{}",
            std::process::id(),
            SystemTime::now()
                .duration_since(UNIX_EPOCH)
                .unwrap()
                .as_nanos()
        ));
        std::fs::create_dir(&path).unwrap();
        Self(path)
    }
    fn path(&self, name: &str) -> PathBuf {
        self.0.join(name)
    }
}
impl Drop for Directory {
    fn drop(&mut self) {
        let _ = std::fs::remove_dir_all(&self.0);
    }
}

fn assert_private_socket(path: &Path) {
    let metadata = std::fs::symlink_metadata(path).unwrap();
    assert!(metadata.file_type().is_socket());
    assert_eq!(metadata.permissions().mode() & 0o777, 0o600);
    assert_eq!(metadata.uid(), unsafe { libc::geteuid() });
}

#[test]
fn native_and_ipc_endpoints_are_owner_private_and_lock_symlinks_are_rejected() {
    let directory = Directory::new();
    let native = directory.path("native");
    let ipc = directory.path("ipc");
    let mut options = tmuxx_runtime::Options::new(&native);
    options.tmux_endpoint = Some(ipc.clone());
    let host = tmuxx_runtime::start(options).unwrap();
    for path in [&native, &ipc] {
        assert_private_socket(path);
        let lock = std::fs::metadata(path.with_extension("lock")).unwrap();
        assert!(lock.is_file());
        assert_eq!(lock.permissions().mode() & 0o077, 0);
        assert_eq!(lock.uid(), unsafe { libc::geteuid() });
    }
    let mut peer = UnixStream::connect(&native).unwrap();
    peer.set_read_timeout(Some(Duration::from_secs(5))).unwrap();
    tmuxx_runtime::native_handshake(&mut peer).unwrap();
    drop(peer);
    host.shutdown().unwrap();
    assert!(!native.exists());
    assert!(!ipc.exists());

    let rejected = directory.path("rejected");
    let target = directory.path("unrelated");
    std::fs::write(&target, b"unchanged").unwrap();
    symlink(&target, rejected.with_extension("lock")).unwrap();
    assert!(tmuxx_runtime::start(tmuxx_runtime::Options::new(&rejected)).is_err());
    assert!(!rejected.exists());
    assert_eq!(std::fs::read(&target).unwrap(), b"unchanged");
    assert!(
        std::fs::symlink_metadata(rejected.with_extension("lock"))
            .unwrap()
            .file_type()
            .is_symlink()
    );
}
