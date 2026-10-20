#![cfg(unix)]
use std::os::unix::fs::{FileTypeExt, symlink};
use std::{
    path::PathBuf,
    time::{Duration, Instant},
};
use tmuxx_protocol::native::{Request, Response, ServerMessage};
use tmuxx_runtime::LocalClient;

fn command(client: &LocalClient, argv: &[&str]) -> Response {
    client
        .send(Request {
            request_id: 1,
            argv: argv.iter().map(|arg| arg.as_bytes().to_vec()).collect(),
            stdin: None,
            subscribe: false,
            control: false,
        })
        .unwrap();
    let deadline = Instant::now() + Duration::from_secs(3);
    loop {
        if let Ok(ServerMessage::Reply(reply)) = client.try_recv() {
            return reply;
        }
        assert!(
            Instant::now() < deadline,
            "native owner stopped responding: {argv:?}"
        );
        std::thread::sleep(Duration::from_millis(1));
    }
}

#[test]
fn special_native_files_reject_without_blocking_owner_or_changing_buffers() {
    let root = PathBuf::from(format!("/tmp/tmuxx-native-files-{}", std::process::id()));
    std::fs::create_dir(&root).unwrap();
    let host = tmuxx_runtime::start(tmuxx_runtime::Options::new(root.join("native"))).unwrap();
    let client = host.connect().unwrap();
    assert_eq!(
        command(
            &client,
            &["new-session", "-d", "-s", "files", "sleep", "30"]
        )
        .error,
        None
    );
    let pid = command(&client, &["display-message", "-p", "#{pane_pid}"]).output;
    assert_eq!(
        command(&client, &["set-buffer", "-b", "kept", "original"]).error,
        None
    );
    let fifo = root.join("fifo");
    let encoded = std::ffi::CString::new(fifo.to_str().unwrap()).unwrap();
    // SAFETY: the path is NUL-terminated and belongs to this test's private directory.
    assert_eq!(unsafe { libc::mkfifo(encoded.as_ptr(), 0o600) }, 0);
    let link = root.join("fifo-link");
    symlink(&fifo, &link).unwrap();
    for path in [&fifo, &link, &PathBuf::from("/dev/zero")] {
        for args in [
            vec!["load-buffer", "-b", "kept", path.to_str().unwrap()],
            vec!["save-buffer", "-b", "kept", path.to_str().unwrap()],
            vec!["source-file", path.to_str().unwrap()],
        ] {
            let response = command(&client, &args);
            assert!(
                response
                    .error
                    .as_deref()
                    .is_some_and(|error| error.contains("unsupported native file type")),
                "{args:?}: {response:?}"
            );
            assert_eq!(
                command(&client, &["show-buffer", "-b", "kept"]).output,
                b"original"
            );
            assert_eq!(
                command(&client, &["display-message", "-p", "#{pane_pid}"]).output,
                pid
            );
        }
    }
    assert!(std::fs::metadata(&fifo).unwrap().file_type().is_fifo());
    let regular = root.join("regular");
    std::fs::write(&regular, b"regular\0\xff").unwrap();
    let regular_link = root.join("regular-link");
    symlink(&regular, &regular_link).unwrap();
    assert_eq!(
        command(
            &client,
            &["load-buffer", "-b", "kept", regular_link.to_str().unwrap()]
        )
        .error,
        None
    );
    assert_eq!(
        command(&client, &["show-buffer", "-b", "kept"]).output,
        b"regular\0\xff"
    );
    let saved = root.join("saved");
    assert_eq!(
        command(
            &client,
            &["save-buffer", "-b", "kept", saved.to_str().unwrap()]
        )
        .error,
        None
    );
    assert_eq!(std::fs::read(&saved).unwrap(), b"regular\0\xff");
    assert_eq!(
        command(&client, &["save-buffer", "-b", "kept", "/dev/null"]).error,
        None
    );
    assert_eq!(
        command(&client, &["load-buffer", "-b", "kept", "/dev/null"]).error,
        None
    );
    assert_eq!(
        command(&client, &["show-buffer", "-b", "kept"]).output,
        b"regular\0\xff"
    );
    host.shutdown().unwrap();
    std::fs::remove_dir_all(root).unwrap();
}
