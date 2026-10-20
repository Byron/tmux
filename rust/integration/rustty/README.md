# Rustty integration patch

`rustty.patch` is the tested native integration applied to the neighboring
`ghostty-org/ghostty` Rustty checkout. `manifest.json` records its base revision
and every original/result file SHA-256. The patch changes Rust sources,
Cargo metadata, Windows packaging and the Rustty README; no Zig production sources.

The integration also carries Rustty commit
[`8ac4798bccc54d3916d829ea15e538842c28c251`](https://github.com/byron/ghostty/commit/8ac4798bccc54d3916d829ea15e538842c28c251),
the companion to tmuxx resize fix `edb75876d80425ed2f69e82096366a4089a26312`.
Older running owners can retain capture lengths wider than a shrunken row or
obsolete row IDs in an unknown capture cache. The adapter caps those used lengths
to the retained row widths and discards unknown-cache orphans before strict
snapshot restoration, allowing existing panes to reconnect without restarting
their processes. Tuple, unsigned-integer, duplicate-ID and allocation checks
remain mandatory, and orphan rows in known capture metadata are still rejected.
This change is applied on top of the recorded `cb67824` integration base; the
other Windows integration changes and dependency layout are preserved.

The backend supports app-owned tmuxx, existing native Unix endpoints, native
stdio over SSH, Windows per-user named pipes, and system C tmux over SSH. The
`rustty tmux` driver dispatches the shared tmuxx CLI before GUI/PTY initialization,
preserving OS arguments. `--tmuxx=persistent` explicitly connects to or starts an
independent owner through that driver; all attachment modes require an existing
owner. Concurrent initial GUI connections consume the exact session-creation
reply and reuse the winning session without replaying ambiguous commands.
Native server graph changes reconcile
into windows/tabs/split views, including duplicate links within one session.
Pane views have independent selection and scroll;
input and structural commands go back to the owner. One size client per native
window participates in server arbitration. The elected host-action recipient
performs clipboard policy/OS access and replies by event ID. Retention is an
explicit palette action for daemon-owned panes, with view claim/release leases.
Native typed key/IME and paste input is encoded by the owner for each synchronized
pane; mouse and protocol reports remain target-only. Focus, visibility and theme
aggregate across views/connections. Pane exit/respawn updates live view status and
clears stale selection when the process is replaced.

Agent status is retained alongside terminal state and reconciled into each native
view, including views opened after the report. Its latest value remains available
when an ordinary event queue is full. Respawn, exit and a new incarnation clear
stale reports. Restoring a report preserves its enclosing-command context without
fabricating command boundaries or replaying clipboard/notification/query effects.
The view owns presentation and acknowledgement of the retained report.

`tmuxx-ssh-command` (or `--tmuxx-ssh-command=COMMAND`) selects a trusted fixed remote
command, defaulting to `tmuxx --native-stdio`. It can invoke a shipped executable
with `rustty tmux --native-stdio`. Configuration preserves cmd.exe/PowerShell
quoting verbatim. The complete command is passed as one SSH exec argument, while
instance selection remains in the protocol hello; reconnect and per-window size
connections preserve both the command and the private SSH configuration.

Rustty aliases its workspace `rustty-vt` dependency to tmuxx's vendored VT;
native snapshot restore and output replay therefore use the owner's terminal
semantics. Ordinary local sessions leave the tmux profile disabled. Socket/SSH
snapshots use bounded chunks and private assembly before atomic publication;
the serialized cap is 8 GiB, with 1 GiB of restored graphics. Interrupted or
aborted transfers preserve the live view. Stable row IDs preserve image anchors
after resize/reflow. OSC133 markers preserve primary/secondary prompts, command
boundaries and exit status through history pruning, resize and reconnect; native
search and selection use the retained data and C output/newline semantics.
Pane content geometry includes border-status offsets;
floating clipping, stacking and modal policies use the server layout, and native
cell metrics include physical pixel dimensions.

Usage and limitations are in the patched `crates/rustty-app/README.md`.
An app-owned PTY cannot be migrated to a daemon by changing a retention flag.
Create panes in the standalone connection when they must survive GUI exit.
Stock C mouse/protocol reports use unique temporary buffers with `paste-buffer
-drS`; interrupted SSH can leave a temporary buffer, and ambiguous input is never
replayed. NUL reports are rejected. C owns all query replies; the stock GUI backend
currently lacks Rustty focus/bell/notification/clipboard routing.
Stock C tmux reconnect reconstruction is best effort; native tmuxx checkpoints
include parser continuation, screens/history, rendition and graphics uploads.

## Verification

The historical 2026-10-20 full macOS collection passed all 12 external Rustty suites and
their 28 named tests, including both C versions. All six scoped profile gates,
including native views, passed. `verification.json` records the report identity
and qualification; fresh evidence is required after either checkout changes.
The executable contract below documents those tests. From the actual Rustty
checkout, using Rust 1.95.0:

- `cargo +1.95.0 check --locked --offline -p rustty-app`.
- `cargo +1.95.0 test --locked --offline -p rustty --features sessions --lib tmuxx::tests:: -- --test-threads=1`:
  21 current tests: embedded/local shared panes and independent selection; focused host
  action election/no snapshot replay/clipboard event-ID replies; exit17/respawn
  with a new PID and selection reset; synchronized per-pane Up/paste encodings
  without mouse/reply broadcast; focus aggregation across views/connections,
  disconnect blur and disabled server focus option; atomic chunked snapshots of
  a 16 MiB RGBA image and abort preservation; row/image anchors after reflow;
  new server incarnation invalidating stale views and event identity; restored
  native history search and exact OSC133 output selection in independent views;
  wide cells, independent viewports, synchronized output and stationary cursor
  changes; detach closing views without signalling the GUI parent; retained agent
  status across late views, fragmentation, respawn and reattachment; malformed
  snapshot preservation; slow-view status reconciliation; and trusted SSH command
  separation from protocol selection; timed-out mutations completing once while
  asynchronous replies remain separate; legacy capture lengths after non-reflow
  shrinking, stale unknown capture rows after reflow, and malformed capture
  metadata rejection after compatibility normalization. New tests require fresh platform evidence;
  the historical macOS result predates them.
- `cargo +1.95.0 test --locked --offline -p rustty-app --lib tmuxx_workspace::tests:: -- --test-threads=1`:
  six tests covering linked-window identities and indexed targets, atomic
  malformed graph refusal, floating/modal/zoom membership and content offsets.
- Desktop binary-target suites exercise floating clipping/hit testing, modal
  input routing, bounded synchronized-output pacing, stationary-cursor/render
  damage, and two pane-cache tests covering viewports, selection and blinking.
  Renderer suites exercise SIXEL owner creation order and viewport selection
  painting. All run against the actual checkout; exact Cargo commands and test
  names are in `rust/conformance/rustty-evidence.toml`.
- `python3 rust/conformance/rustty_system_ssh.py --rustty PATH --reference C_TMUX`
  from the tmux checkout runs
  real loopback SSH with two sessions, a shared window, independent selection,
  live output, connection restart, dynamic pane creation/removal and capture.
  Stock mouse/reply tests use real terminal encoders under synchronized panes,
  reject NUL, preserve newline/semicolon reports, and prove temporary-buffer
  cleanup (including a vanished target) and preservation of user buffers.
  Duplicate same-session window links and active indices also survive discovery.
  Deferred unframed server text reaches the application without a fabricated
  request ID. The latest focused runs recorded 14 assertions with current C
  (`tmux next-3.9`) and 13 with Homebrew 3.7c; their binary/source hashes are in
  `verification.json`. These focused results do not replace the full gate.
- The hidden macOS Metal suite builds and renders two native panes, including
  one clipped floating pane, with no visible or focused native window. It
  verifies a fresh PNG in a temporary directory and records the state, frame
  dimensions and frame/executable hashes; it does not retain that PNG after the run.
- `cargo +1.95.0 clippy --locked --offline --no-deps -p rustty -p rustty-app --all-targets -- -D warnings -A clippy::nonminimal_bool -A clippy::collapsible_match`.
  Those two allowances cover pre-existing Rustty baseline lints; strict default
  clippy is not claimed clean.

The socket/PTY and SSH tests need ordinary OS process/socket permissions. Linux
server execution is active; see [Linux reproduction](../../LINUX.md) and its
fresh evidence reports. Portable Rustty adapter/workspace tests can run on the
Linux host, while renderer and desktop tests require a supported macOS/Windows
client. Windows execution is active, and qualification requires fresh Windows
profile evidence. The smoke exercises native composition and backend
attachment; it does not certify every UI gesture. Stock C capture reconstruction
remains best effort and live app-owned PTY migration remains unimplemented.

`rust/conformance/rustty-evidence.toml` and `version-evidence.toml` define the
external suites, including separate current-C and C3.7c SSH runs.
The runner validates the actual sibling checkout against `manifest.json`, then
runs its applicable exact named tests and real isolated SSH tests. A freshly
built hidden desktop smoke runs on its supported platform; Linux records that
requirement as blocked until actual client-host evidence is available. All sibling crate sources, Cargo manifests/lockfile, checkout
revision and the integration patch enter the fingerprint. Missing checkouts,
changed files, ignored/filtered tests and source changes during execution fail
the proof. `TMUXX_RUSTTY_ROOT` can point to another identically integrated checkout.
CI checks out the recorded base from `Byron/rustty` alongside tmux, applies the
patch and runs the same evidence suites. Historical JSON files in this directory
are inspection artifacts; they do not substitute for current executable proof.

To collect the complete tmuxx and Rustty contract from the tmux checkout:

```sh
cargo +1.95.0 build --manifest-path rust/Cargo.toml --locked --offline -p tmuxx-cli
python3 rust/conformance/runner.py smoke \
  --reference /path/to/image-enabled-current-tmux \
  --older-reference /path/to/tmux-3.7c \
  --candidate rust/target/debug/tmuxx --suite all \
  --report rust/conformance/artifacts/c-rust.json
python3 rust/conformance/runner.py gate \
  --report rust/conformance/artifacts/c-rust.json --profile native-views
```

The Python runner requires Python 3.11 or newer. Reuse a built Cargo target
directory for the SSH test, or first run
`cargo +1.95.0 test --locked --offline -p rustty --features sessions --no-run`
from the actual Rustty checkout so compilation does not consume its 120-second
SSH test deadline. `CARGO_TARGET_DIR` is inherited by both workspaces.

`verification.json` separates the current executable contract from historical
checks. The saved `system-ssh-*.json/.log`, `native-smoke.json/png`,
`floating-smoke.json`, `shell-reference-build.json` and
`images-reference-build.json` belong to earlier source/binary revisions.
The saved native image is historical, and the ordinary unprofiled `rustty --lib`
result of 49 passing tests is a historical baseline. The complete collector runs
the selected tmuxx integration tests, not that entire ordinary suite.

## Updating after rebase

Keep this patch tied to the recorded Rustty revision. Before applying it elsewhere,
compare the base hashes and run `git apply --check rustty.patch` from that checkout.
Resolve conflicts in the responsibility boundaries: VT snapshot extension,
Session attachment, connection manager, and workspace mapping. Re-run the tests
above, then regenerate the patch and manifest from the new clean Rustty base.
Do not overwrite uncommitted user changes with a copied staging tree.

## Windows execution

Preserve the sibling checkout layout, or deliberately update all Cargo dependency
paths together. Both owners use `rust/windows/conpty.json`: ConPTY package
`1.24.260710001`, x64, archive SHA-256
`175640566a3b59c4b132070ee96c2c77e5ab7edd2e92732a5eb3610bbf63d90e`.
Both member hashes are checked before portable-pty initializes, and open read
handles prevent replacement while loaded. The same vendored portable-pty binds
the verified DLL and starts panes inside kill-on-close Job Objects.

From the actual Windows Rustty checkout:

```powershell
./crates/rustty-app/build.ps1 -Offline
$env:TMUXX_CONPTY_RESOURCES = (Resolve-Path target/debug/Rustty/resources).Path
$env:RUSTTY_RESOURCES_DIR = $env:TMUXX_CONPTY_RESOURCES
$env:TMUXX_REMOTE_PYTHON = (python -c "import sys; print(sys.executable)").Trim()
cargo +1.95.0 test --locked --offline -p rustty --features sessions --lib tmuxx::tests:: --target x86_64-pc-windows-msvc -- --test-threads=1
cargo +1.95.0 test --locked --offline -p rustty --features sessions --lib config::tests:: --target x86_64-pc-windows-msvc -- --test-threads=1
cargo +1.95.0 test --locked --offline -p rustty-app --lib tmuxx_workspace::tests:: --target x86_64-pc-windows-msvc -- --test-threads=1
cargo +1.95.0 test --locked --offline -p rustty-app --lib tmuxx_launcher::tests:: --target x86_64-pc-windows-msvc -- --test-threads=1
cargo +1.95.0 test --locked --offline -p rustty-app --test tmuxx_driver --target x86_64-pc-windows-msvc -- --test-threads=1
cargo +1.95.0 test --locked --offline -p rustty-app --test windows_conpty --target x86_64-pc-windows-msvc -- --ignored
```

All 21 selected backend tests run on Windows. The 44 config tests include exact
remote-command quote preservation. The launcher test synchronizes two initial
clients against an empty real owner and verifies one session/pane/PID, existing
owner reuse, and process cleanup. The two Windows driver tests exercise the GUI
executable's early CLI dispatch, explicit missing-owner error, and one retained
process across local and stdio views. Use an actual Python interpreter path,
not a launcher shim, when asserting that the reported pane PID is the process PID.
The custom `windows_conpty` harness
emits `TMUXX_WINDOWS_CONPTY_RESULT` only after eight verified redraws, including
the bundled-runtime identity; ordinary libtest output cannot prove its result.
Build the standalone package with `rust/windows/build.ps1`, supplying the same
cached archive through `-ConPtyPackage` for offline operation. Keep the complete
resources folder beside each executable. Directory rename preserves the old
bundle if an active process prevents replacement.

The separate desktop fixture runs visible native windows and records every
rendered HWND view, server graph and pane PID. It exercises external session/tab/
split changes, shared windows and duplicate links, graceful and abrupt app-owner cleanup,
retained standalone panes across graceful and abrupt GUI restarts, and missing/corrupt runtime
members in both packaged executables:

```powershell
python rust/conformance/windows_native_views.py --gui PATH/TO/Rustty/rustty.exe --candidate rust/target/debug/tmuxx/tmuxx.exe --report rust/conformance/artifacts/windows-native-views.json
```

The desktop fixture checks held process handles through cleanup on failure and
timeout. It retains its private images, logs and graph records alongside the
report. It does not establish real keyboard/IME gestures, OS clipboard policy,
or cross-logon SSH identity. Those remain required parts of the Windows profile;
backend and rendering checks do not substitute for them. Historical macOS data
and development runs do not qualify the current checkout.

The separate `windows-desktop-ssh` suite launches a second real Windows Rustty
with `--tmuxx=ssh:HOST --tmuxx-instance=NAME`, private OpenSSH configuration, and
a restricted loopback-only bridge credential. It verifies native shared-window
reconciliation, unchanged pane PIDs, per-window resize connections, and both
graceful and abrupt SSH viewer exit while the desktop owner remains alive.
Native and system SSH adapters put helpers in kill-on-close jobs atomically at
process creation, suppress console windows, and keep binary stdout separate from
diagnostics. `RUSTTY_TMUXX_SSH_CONFIG` selects an explicit native or system SSH config file
without changing account-wide configuration. See `conformance/WINDOWS.md` for
credential prerequisites and exact bridge-process cleanup accounting.
