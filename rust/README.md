# tmuxx

A Rust tmux engine and control client for Rustty. The workspace separates command,
configuration, format and layout parsers, headless terminal state, the engine,
protocol codecs, client state, Unix IPC, process hosting and the clap CLI. It
does not link to C tmux; conformance runs the C executable as a separate process.

The engine provides the scoped command/control behavior and application terminal
state. Rustty renders native panes. Ordinary tty attachment is explicitly
unsupported. See the [architecture](ARCHITECTURE.md) for the contract and
[tested differences](conformance/differences.toml) for deliberate behavior changes.

## Build and use

Rust 1.95 or newer:

```sh
cd rust
cargo build --locked --release -p tmuxx-cli
target/release/tmuxx -L rustty-demo -f /dev/null new-session -d -s work
target/release/tmuxx -L rustty-demo list-panes -a
target/release/tmuxx -L rustty-demo split-window -h -t work:
```

Both `tmuxx` and an unmodified supported `tmux` client can control that daemon
using `-L rustty-demo`. `-S` chooses an explicit tmux command socket; its separate
native endpoint is the socket path plus `.native`. `-D` runs an owner in the
foreground, and `-N` prevents accidental server startup. `--native-stdio` bridges
to an existing native endpoint over SSH.

The [Rustty integration](integration/rustty/README.md) is applied to the sibling
checkout and also supplied as a patch with source hashes. Its launch modes are:

| Rustty argument | Owner |
| --- | --- |
| `--tmuxx=embedded` | This Rustty process |
| `--tmuxx=persistent` | Independent local native daemon |
| `--tmuxx=unix:/path/to/socket.native` | Existing local tmuxx daemon |
| `--tmuxx=ssh:host` | Remote tmuxx native endpoint |
| `--tmuxx=system-ssh:host` | Remote system tmux, using SSH control mode |

For embedding, `tmuxx_runtime::start(Options)` returns a `ServerHandle` with typed
local connections and optional Unix command access. Dropping the handle shuts
down its PTYs. `tmuxx-client` consumes and produces protocol bytes with
caller-owned I/O, so client-only consumers do not compile the engine.

Rustty includes the CLI in the same executable: `rustty tmux` (or
`rustty.exe tmux`) dispatches before opening a GUI. The callable
`tmuxx_cli::run_from(args, launcher_prefix)` preserves the subcommand when it
starts a daemon. Embedded callers default to the native endpoint; `-L` or `-S`
explicitly selects the compatible tmux command socket. Standalone `tmuxx`
retains its usual tmux socket defaults. `tmuxx_cli::default_native_endpoint()`
resolves `TMUXX_ENDPOINT`, otherwise the checked per-user
`/tmp/tmux-UID/default.native` path (`TMUX_TMPDIR` can replace `/tmp`), without
following an inherited `TMUX` variable.

For example, `rustty tmux new-session -d -s work` starts a native daemon if
needed; later CLI invocations attach to that same owner. Auto-started daemons
have their own process session and no controlling terminal. GUI hosts use the
same `tmuxx_cli::native_daemon_command(endpoint, launcher_prefix)` builder.
Explicit `rustty tmux --native-endpoint PATH -D` remains a foreground command.
Over SSH, `rustty tmux --native-stdio` bridges to an existing owner without
starting one. Rustty's `tmuxx-ssh-command` setting can select another remote
helper path or endpoint; its value is a remote shell command. SSH requires
noninteractive authentication and does not reconnect automatically. Command
dispatch is shared across platforms; Windows native endpoint/ConPTY hosting
remains unimplemented.

Choose the owner when launching panes. Standalone panes survive GUI exit;
app-owned panes end with the owner. Live PTY migration between those owners is
not implemented. Stock C reconnection reconstructs only the state
tmux exposes; complete atomic terminal checkpoints use the native protocol.

## Verify and rebase

```sh
cargo test --locked --offline --workspace --all-targets
cargo clippy --locked --offline --workspace --all-targets -- -D warnings
python3 conformance/runner.py inventory
python3 conformance/runner.py smoke --reference /path/to/image-enabled/tmux \
  --older-reference /path/to/tmux-3.7c \
  --candidate target/debug/tmuxx --suite all --report conformance/artifacts/c-rust.json
python3 conformance/runner.py gate --report conformance/artifacts/c-rust.json \
  --profile command-control
```

Build the debug candidate before collecting that report. Reference tests need
local socket, PTY and isolated SSH permissions. The gate checks exact named test
results, all required assertions, reviewed upstream changes, and source/binary
fingerprints. Passing unit tests alone does not certify a profile. The
[conformance guide](conformance/README.md) describes the other profile gates,
current/3.7c version checks, and required metadata review after every rebase.
C sources remain unchanged; the Rust workspace and CI workflow are additive.

On 2026-10-20, all six scoped macOS gates passed: command/control, system client,
native views, standalone, app-owned and Unix IPC. The frozen-source collection
passed 149 executable suites and all 430 scoped assertions, using current C tmux
and 3.7c. Workspace tests, strict Clippy, formatting, metadata checks and the
Python evidence tests also passed. These dated results do not qualify later
source changes; collect fresh evidence after changes or rebases.

Execution qualification is macOS-only. Linux and Windows execution are
user-deferred; Windows ConPTY/named-pipe hosting still needs implementation and
validation on a Windows machine.
