# Rustty integration patch

`rustty.patch` is the tested native integration applied to the neighboring
`ghostty-org/ghostty` Rustty checkout. `manifest.json` records its base revision
and every original/result file SHA-256. The patch changes only Rust sources,
Cargo metadata and the Rustty README; no Zig production sources or commits.

The backend supports app-owned tmuxx, existing native Unix endpoints, native
stdio over SSH, and system C tmux over SSH. Native server graph changes reconcile
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

The 2026-10-20 full macOS collection passed all 12 external Rustty suites and
their 28 named tests, including both C versions. All six scoped profile gates,
including native views, passed. `verification.json` records the report identity
and qualification; fresh evidence is required after either checkout changes.
The executable contract below documents those tests. From the actual Rustty
checkout, using Rust 1.95.0:

- `cargo +1.95.0 check --locked --offline -p rustty-app`.
- `cargo +1.95.0 test --locked --offline -p rustty --features sessions --lib tmuxx::tests:: -- --test-threads=1`:
  11 tests: embedded/Unix shared panes and independent selection; focused host
  action election/no snapshot replay/clipboard event-ID replies; exit17/respawn
  with a new PID and selection reset; synchronized per-pane Up/paste encodings
  without mouse/reply broadcast; focus aggregation across views/connections,
  disconnect blur and disabled server focus option; atomic chunked snapshots of
  a 16 MiB RGBA image and abort preservation; row/image anchors after reflow;
  new server incarnation invalidating stale views and event identity; restored
  native history search and exact OSC133 output selection in independent views;
  wide cells, independent viewports, synchronized output and stationary cursor
  changes; detach closing views without signalling the GUI parent.
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
and Windows execution remain deferred. The smoke exercises native composition and backend
attachment; it does not certify every UI gesture. Stock C capture reconstruction
remains best effort and live app-owned PTY migration remains unimplemented.

`rust/conformance/rustty-evidence.toml` and `version-evidence.toml` define 12
external suites, including separate current-C and C3.7c SSH runs.
The runner validates the actual sibling checkout against `manifest.json`, then
runs its exact named tests, real isolated SSH tests, and a freshly built hidden
desktop smoke. All sibling crate sources, Cargo manifests/lockfile, checkout
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
