use super::*;

#[cfg(target_os = "macos")]
fn foreground(fd: libc::c_int) -> (Option<String>, Option<String>) {
    let pid = unsafe { libc::tcgetpgrp(fd) };
    if pid <= 0 {
        return (None, None);
    }
    fn info<T>(pid: libc::pid_t, flavor: libc::c_int) -> Option<T> {
        let mut data = std::mem::MaybeUninit::<T>::zeroed();
        let size = std::mem::size_of::<T>();
        let read = unsafe {
            libc::proc_pidinfo(
                pid,
                flavor,
                0,
                data.as_mut_ptr().cast(),
                size as libc::c_int,
            )
        };
        (read as usize == size).then(|| unsafe { data.assume_init() })
    }
    fn string(bytes: &[libc::c_char]) -> Option<String> {
        let bytes = bytes
            .iter()
            .take_while(|b| **b != 0)
            .map(|b| *b as u8)
            .collect();
        String::from_utf8(bytes).ok().filter(|s| !s.is_empty())
    }
    let name = info::<libc::proc_bsdshortinfo>(pid, libc::PROC_PIDT_SHORTBSDINFO)
        .and_then(|data| string(&data.pbsi_comm));
    let cwd = info::<libc::proc_vnodepathinfo>(pid, libc::PROC_PIDVNODEPATHINFO)
        .and_then(|data| string(data.pvi_cdir.vip_path.as_flattened()));
    (name, cwd)
}
#[cfg(target_os = "linux")]
fn foreground(fd: libc::c_int) -> (Option<String>, Option<String>) {
    let pid = unsafe { libc::tcgetpgrp(fd) };
    if pid <= 0 {
        return (None, None);
    }
    let name = std::fs::File::open(format!("/proc/{pid}/cmdline"))
        .ok()
        .and_then(|file| {
            let mut bytes = Vec::new();
            file.take(65536).read_to_end(&mut bytes).ok()?;
            String::from_utf8(bytes.split(|b| *b == 0).next()?.to_vec()).ok()
        });
    let cwd = std::fs::read_link(format!("/proc/{pid}/cwd"))
        .ok()
        .and_then(|p| p.into_os_string().into_string().ok());
    (name, cwd)
}

impl Host {
    pub(super) fn refresh_process_metadata(&mut self) {
        #[cfg(any(target_os = "macos", target_os = "linux"))]
        for (id, process) in &self.processes {
            if let Some(pane) = self.engine.panes.get_mut(id) {
                let (name, cwd) = process
                    .master
                    .as_raw_fd()
                    .map(foreground)
                    .unwrap_or_default();
                pane.current_command = name;
                pane.current_path = cwd;
            }
        }
    }
    pub(super) fn check_window_names(&mut self) {
        if Instant::now() < self.next_name_check {
            return;
        }
        self.next_name_check = Instant::now() + Duration::from_millis(500);
        self.refresh_process_metadata();
        let before = self.hook_snapshot();
        let out = self.engine.rename_automatic_windows();
        if out.changed {
            self.engine.sequence += 1;
            for data in out.notifications {
                self.broadcast_notification(data);
            }
            self.broadcast(ServerMessage::Changed {
                sequence: self.engine.sequence,
            });
            if let Some(before) = before {
                self.graph_hooks(before, false);
            }
        }
    }
}
