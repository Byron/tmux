use std::ffi::{CStr, CString};
use std::mem::MaybeUninit;

fn local(timestamp: libc::time_t) -> Option<libc::tm> {
    let mut local = MaybeUninit::uninit();
    if unsafe { libc::localtime_r(&timestamp, local.as_mut_ptr()) }.is_null() {
        return None;
    }
    Some(unsafe { local.assume_init() })
}
fn strftime(format: &[u8], local: &libc::tm) -> Vec<u8> {
    let Ok(format) = CString::new(format) else {
        return Vec::new();
    };
    let mut result = vec![0u8; 8192];
    let len = super::locale::with(|| unsafe {
        libc::strftime(
            result.as_mut_ptr().cast(),
            result.len(),
            format.as_ptr(),
            local,
        )
    })
    .unwrap_or(0);
    result.truncate(len);
    result
}
pub(super) fn expand(format: &[u8], timestamp: libc::time_t) -> Vec<u8> {
    local(timestamp).map_or_else(Vec::new, |local| strftime(format, &local))
}
pub(super) fn now() -> libc::time_t {
    unsafe { libc::time(std::ptr::null_mut()) }
}

pub(super) fn format(value: &[u8], flags: &[u8], template: Option<&[u8]>) -> Vec<u8> {
    let Some(timestamp) = std::str::from_utf8(value)
        .ok()
        .and_then(|s| s.parse::<libc::time_t>().ok())
        .filter(|n| *n > 0)
    else {
        return Vec::new();
    };
    if flags.contains(&b'p') {
        let now = now().max(timestamp);
        let (Some(date), Some(today)) = (local(timestamp), local(now)) else {
            return Vec::new();
        };
        let age = now - timestamp;
        let format: &[u8] = if age < 86400 {
            b"%H:%M"
        } else if (date.tm_year == today.tm_year && date.tm_mon == today.tm_mon) || age < 28 * 86400
        {
            b"%a%d"
        } else if (date.tm_year == today.tm_year && date.tm_mon < today.tm_mon)
            || (date.tm_year == today.tm_year - 1 && date.tm_mon > today.tm_mon)
        {
            b"%d%b"
        } else {
            b"%h%y"
        };
        return strftime(format, &date);
    }
    if flags.contains(&b'r') {
        let age = now() - timestamp;
        if age < 0 {
            return Vec::new();
        }
        let units = [
            (age / 86400, "d"),
            ((age % 86400) / 3600, "h"),
            ((age % 3600) / 60, "m"),
            (age % 60, "s"),
        ];
        for (index, (value, suffix)) in units.iter().enumerate() {
            if *value != 0 {
                let mut text = format!("{value}{suffix}");
                if let Some((next, suffix)) = units.get(index + 1)
                    && *next != 0
                {
                    text.push_str(&format!("{next}{suffix}"));
                }
                return text.into_bytes();
            }
        }
        return b"0s".to_vec();
    }
    if flags.contains(&b'd') {
        return (now() - timestamp).to_string().into_bytes();
    }
    if flags.contains(&b'f')
        && let Some(template) = template
    {
        return expand(template, timestamp);
    }
    let mut result = [0 as libc::c_char; 32];
    if unsafe { libc::ctime_r(&timestamp, result.as_mut_ptr()) }.is_null() {
        return Vec::new();
    }
    let result = unsafe { CStr::from_ptr(result.as_ptr()) }.to_bytes();
    result.strip_suffix(b"\n").unwrap_or(result).to_vec()
}
