use std::fs::{File, Metadata, OpenOptions};
use std::io;
use std::path::Path;

fn supported(metadata: &Metadata) -> bool {
    if metadata.is_file() {
        return true;
    }
    #[cfg(unix)]
    {
        use std::os::unix::fs::{FileTypeExt, MetadataExt};
        if metadata.file_type().is_char_device() {
            return std::fs::metadata("/dev/null").is_ok_and(|null| null.rdev() == metadata.rdev());
        }
    }
    false
}

fn validate(metadata: &Metadata) -> io::Result<()> {
    if supported(metadata) {
        Ok(())
    } else {
        Err(io::Error::new(
            io::ErrorKind::Unsupported,
            "unsupported native file type: only regular files and /dev/null are supported",
        ))
    }
}

/// The owner may perform bounded regular I/O, but must never wait for a FIFO peer.
pub(super) fn open(options: &mut OpenOptions, path: &Path) -> io::Result<File> {
    match std::fs::metadata(path) {
        Ok(metadata) => validate(&metadata)?,
        Err(error) if error.kind() == io::ErrorKind::NotFound => {}
        Err(error) => return Err(error),
    }
    #[cfg(unix)]
    {
        use std::os::unix::fs::OpenOptionsExt;
        options.custom_flags(libc::O_NONBLOCK | libc::O_NOCTTY);
    }
    let file = options.open(path)?;
    validate(&file.metadata()?)?;
    Ok(file)
}
