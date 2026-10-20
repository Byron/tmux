use std::ffi::CStr;
use tmuxx_core::Engine;

pub(super) fn apply(engine: &mut Engine) {
    engine
        .identity
        .insert("pid".into(), std::process::id().to_string());
    engine
        .identity
        .insert("uid".into(), unsafe { libc::getuid() }.to_string());
    if let Some(user) = user_name() {
        engine.identity.insert("user".into(), user);
    }
    let mut host = vec![0u8; 256];
    if unsafe { libc::gethostname(host.as_mut_ptr().cast(), host.len()) } == 0 {
        host.truncate(host.iter().position(|b| *b == 0).unwrap_or(host.len()));
        engine
            .identity
            .insert("host".into(), String::from_utf8_lossy(&host).into_owned());
    }

    let shell = engine
        .environment
        .get("SHELL")
        .filter(|shell| super::scheduler::suitable_shell(shell.as_bytes()))
        .cloned()
        .or_else(login_shell)
        .unwrap_or_else(|| "/bin/sh".into());
    engine.options.insert("default-shell".into(), shell);
    if let Some(editor) = engine
        .environment
        .get("VISUAL")
        .or_else(|| engine.environment.get("EDITOR"))
    {
        engine
            .server_options
            .insert("editor".into(), editor.clone());
        let keys = if editor.rsplit('/').next().unwrap_or_default().contains("vi") {
            "vi"
        } else {
            "emacs"
        };
        engine.options.insert("status-keys".into(), keys.into());
        engine
            .global_window_options
            .insert("mode-keys".into(), keys.into());
    }
}

pub(super) fn user_name() -> Option<String> {
    String::from_utf8(account_field(b"", |entry| entry.pw_name)?).ok()
}

fn login_shell() -> Option<String> {
    let shell = account_field(b"", |entry| entry.pw_shell)?;
    super::scheduler::suitable_shell(&shell)
        .then(|| String::from_utf8(shell).ok())
        .flatten()
}

pub(super) fn user_home(name: &[u8]) -> Option<Vec<u8>> {
    account_field(name, |entry| entry.pw_dir)
}

fn account_field(name: &[u8], field: fn(&libc::passwd) -> *const libc::c_char) -> Option<Vec<u8>> {
    let name = std::ffi::CString::new(name).ok()?;
    let mut size = 1024;
    loop {
        let mut buffer = vec![0u8; size];
        let mut entry = std::mem::MaybeUninit::<libc::passwd>::uninit();
        let mut found = std::ptr::null_mut();
        // The reentrant lookup keeps concurrent embedded hosts independent.
        let status = unsafe {
            if name.as_bytes().is_empty() {
                libc::getpwuid_r(
                    libc::getuid(),
                    entry.as_mut_ptr(),
                    buffer.as_mut_ptr().cast(),
                    buffer.len(),
                    &mut found,
                )
            } else {
                libc::getpwnam_r(
                    name.as_ptr(),
                    entry.as_mut_ptr(),
                    buffer.as_mut_ptr().cast(),
                    buffer.len(),
                    &mut found,
                )
            }
        };
        if status == libc::ERANGE && size < 1024 * 1024 {
            size *= 2;
            continue;
        }
        if status != 0 || found.is_null() {
            return None;
        }
        let entry = unsafe { entry.assume_init() };
        let value = field(&entry);
        if value.is_null() {
            return None;
        }
        return Some(unsafe { CStr::from_ptr(value) }.to_bytes().to_vec());
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn editor_precedence_uses_basename_and_preserves_empty_visual() {
        for (visual, editor, expected, keys) in [
            (None, None, "/usr/bin/vi", "emacs"),
            (None, Some("/usr/bin/vim -f"), "/usr/bin/vim -f", "vi"),
            (Some(""), Some("vim"), "", "emacs"),
            (
                Some("/vi/path/emacs"),
                Some("vi"),
                "/vi/path/emacs",
                "emacs",
            ),
            (Some("/bin/VI"), None, "/bin/VI", "emacs"),
        ] {
            let mut engine = Engine::default();
            engine.environment.insert("SHELL".into(), "/bin/sh".into());
            if let Some(value) = visual {
                engine.environment.insert("VISUAL".into(), value.into());
            }
            if let Some(value) = editor {
                engine.environment.insert("EDITOR".into(), value.into());
            }
            apply(&mut engine);
            assert_eq!(engine.server_options["editor"], expected);
            assert_eq!(engine.options["status-keys"], keys);
            assert_eq!(engine.global_window_options["mode-keys"], keys);
            assert_eq!(engine.options["default-shell"], "/bin/sh");
        }
    }
}
