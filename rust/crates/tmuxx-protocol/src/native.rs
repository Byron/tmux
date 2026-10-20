//! Explicitly selected native protocol; never send these records to a tmux socket.
//!
//! Transport framing is one JSON value per line. Endpoints must negotiate the
//! protocol version and impose their own byte limit before deserializing.

use serde::{Deserialize, Serialize};
mod snapshot;
pub use snapshot::{
    MAX_SNAPSHOT_BYTES, SNAPSHOT_CHUNK_BYTES, SnapshotAssembler, snapshot_bytes, write_snapshot,
};

pub const VERSION: u32 = 1;

/// The first record in each direction, before requests or server messages.
#[derive(Clone, Debug, Eq, PartialEq, Serialize, Deserialize)]
pub struct Hello {
    pub version: u32,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub cwd: Option<String>,
    #[serde(default, skip_serializing_if = "std::collections::BTreeMap::is_empty")]
    pub environment: std::collections::BTreeMap<String, String>,
    #[serde(default)]
    pub host_effects: bool,
    /// Opt into bounded, atomic snapshot streams instead of one large record.
    #[serde(default)]
    pub snapshot_stream: bool,
    /// Tagged control requests preserve source blocks and per-command guards.
    #[serde(default)]
    pub control_commands: bool,
}

impl Default for Hello {
    fn default() -> Self {
        Self {
            version: VERSION,
            cwd: None,
            environment: Default::default(),
            host_effects: false,
            snapshot_stream: true,
            control_commands: true,
        }
    }
}

#[derive(Clone, Debug, Eq, PartialEq, Serialize, Deserialize)]
pub struct Request {
    pub request_id: u64,
    pub argv: Vec<Vec<u8>>,
    /// File input for a command such as `load-buffer -`, including arbitrary bytes.
    /// Reply to `ServerMessage::Stdin` with argv `["tmuxx-stdin", original_id]`;
    /// use a fresh request ID, at most 65536 bytes per chunk, and None for EOF.
    /// Each chunk receives a Reply acknowledgement before the next is sent.
    #[serde(default)]
    pub stdin: Option<Vec<u8>>,
    #[serde(default)]
    pub subscribe: bool,
    #[serde(default)]
    pub control: bool,
}

/// Optional native transport bridge for C control-mode semantics. Ordinary
/// Request messages retain one aggregate Reply and literal argv semantics.
#[derive(Clone, Debug, Eq, PartialEq, Serialize, Deserialize)]
pub struct ControlRequest {
    pub request_id: u64,
    #[serde(default)]
    pub argv: Vec<Vec<u8>>,
    /// A source line, prepared in the owner before any of its commands execute.
    /// Source and nonempty argv are mutually exclusive.
    #[serde(default)]
    pub source: Option<Vec<u8>>,
    #[serde(default)]
    pub subscribe: bool,
}

#[derive(Clone, Debug, Eq, PartialEq, Serialize, Deserialize)]
#[serde(tag = "type", content = "request", rename_all = "snake_case")]
pub enum ClientMessage {
    Control(ControlRequest),
}

#[derive(Clone, Debug, Eq, PartialEq, Serialize, Deserialize)]
pub struct Response {
    pub request_id: u64,
    /// Shell-job process status, distinct from a command error or unchanged status.
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub status: Option<i32>,
    pub output: Vec<u8>,
    pub error: Option<String>,
}

#[derive(Clone, Debug, PartialEq, Serialize, Deserialize)]
#[serde(tag = "type", rename_all = "snake_case")]
pub enum ServerMessage {
    /// Internal Unix adapter transfer, issued after command validation and expansion.
    /// Native endpoints never emit this message.
    File {
        request_id: u64,
        path: Vec<u8>,
        data: Option<Vec<u8>>,
        append: bool,
    },
    /// The command waits for incremental stdin; finish it with an explicit EOF.
    Stdin {
        request_id: u64,
        pane_id: u64,
    },
    /// Client flag update; the Unix adapter sends the corresponding tmux MSG_FLAGS.
    ClientFlags {
        flags: String,
    },
    HostEffect {
        sequence: u64,
        pane_id: u64,
        event_id: u64,
        action: serde_json::Value,
    },
    Reply(Response),
    Snapshot {
        instance_id: String,
        sequence: u64,
        state: serde_json::Value,
    },
    SnapshotStart {
        instance_id: String,
        sequence: u64,
        bytes: u64,
    },
    SnapshotChunk {
        offset: u64,
        data: String,
    },
    SnapshotEnd {
        sequence: u64,
    },
    SnapshotAborted {
        instance_id: String,
        sequence: u64,
        error: String,
    },
    PaneOutput {
        sequence: u64,
        pane_id: u64,
        data: Vec<u8>,
    },
    Changed {
        sequence: u64,
    },
    /// Control wire bytes without the final LF. This may be a notification,
    /// a complete guarded command result, or deferred unframed server output.
    /// A control bridge writes these bytes followed by exactly one LF.
    Control {
        data: Vec<u8>,
    },
    Detached {
        session: String,
        hangup: bool,
    },
    Exit {
        reason: String,
    },
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn bytes_and_tag_round_trip() {
        let message = ServerMessage::Reply(Response {
            status: None,
            request_id: 12,
            output: vec![0, 255, b'\n'],
            error: None,
        });
        let json = serde_json::to_vec(&message).unwrap();
        assert_eq!(
            serde_json::from_slice::<ServerMessage>(&json).unwrap(),
            message
        );
        assert_eq!(
            serde_json::from_slice::<serde_json::Value>(&json).unwrap()["type"],
            "reply"
        );
    }

    #[test]
    fn subscription_is_opt_in() {
        let request: Request = serde_json::from_str(r#"{"request_id":1,"argv":[[255]]}"#).unwrap();
        assert!(!request.subscribe);
        assert!(!request.control);
        assert_eq!(request.argv, [vec![255]]);
    }
}
