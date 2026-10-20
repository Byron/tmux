# Linux server hosting and qualification

Linux can host ordinary C tmux for a remote Rustty control client, a standalone
tmuxx daemon, or an embedded tmuxx runtime. Rustty desktop runs on macOS and
Windows. No Linux desktop implementation is implied by portable Rustty library
tests. Ordinary tty presentation, pane migration, survival across daemon death
or reboot, and Windows hosting remain outside this Linux qualification.

The recorded local environment is Ubuntu 26.04.1 LTS, aarch64 GNU/Linux,
kernel 7.0.0-1012-azure, glibc 2.43, Rust 1.95.0, Python 3.14.4 and OpenSSH
10.2p1. [The environment record](conformance/linux-environment.json) includes
package versions, source verification, effective build flags and SHA-256 values.
Results apply to that target. CI also defines an Ubuntu 24.04 x86_64 GNU job;
its result must be collected separately. No musl or other architecture result
is inferred from either job.

## Dependencies and source layout

On Debian/Ubuntu, install `build-essential autoconf automake bison pkg-config
libevent-dev libncurses-dev libutf8proc-dev libpng-dev openssh-client
openssh-server python3`. Use Rust 1.95.0 with rustfmt and Clippy, and Python
3.11 or newer. Reuse Cargo caches with `cargo +1.95.0 fetch --locked`, then
build/test using `--locked --offline`.

Some distribution sshd builds require `/run/sshd` to exist. Provision that
directory with root ownership and mode 0755; the tests use their own loopback
ports, configuration files, keys and verified host keys. They do not alter the
machine's normal SSH configuration. The explicit different-UID access test uses
`sudo -n -u nobody /usr/bin/python3` and fails if this prerequisite is missing.
Normal tmuxx operation does not use sudo.

The local integrated checkout is
`/tmp/tmuxx-linux-sources/ghostty-org/ghostty` at
`cb67824a77fc00bd20e811cce40012893f79b999`.
`/tmp/tmuxx-linux-sources/tmux/tmux` points to the tmux checkout, preserving the
patch's sibling dependency layout. Set `TMUXX_RUSTTY_ROOT` to this Rustty path.
All twenty recorded base hashes and all twenty patched result hashes were
verified. For another checkout, follow
[the integration procedure](integration/rustty/README.md); never overwrite an
already modified checkout to make its hashes match.

## C references

Build separate source directories without installing over the distribution's
tmux. The recorded distribution binary is tmux 3.6 and is not either oracle.

| Reference | Revision | Effective configure flags | Local executable |
|---|---|---|---|
| next-3.9 | `22f34d3fa984e03719b0a1b2ac4677aaf61cd53d` | `--enable-utf8proc --enable-images` | `/tmp/tmuxx-linux-references/current/tmux` |
| 3.7c | `e476c1230b958df0cb12977517d24b3dc931375b` | `--enable-utf8proc --enable-sixel` | `/tmp/tmuxx-linux-references/3.7c/tmux` |

Run `sh autogen.sh`, configure with the flags above, and `make` in each source
directory. 3.7c does not recognize `--enable-images`: its equivalent image
feature is `--enable-sixel`. Verify `HAVE_UTF8PROC` and `ENABLE_IMAGES` or
`ENABLE_SIXEL` in effective build definitions, the exact `-V` output, revision,
and executable hash. Preserve configure/build logs. The Linux environment record
verifies every archived source file against its requested revision.

## Use existing owners

Start a standalone native owner explicitly:

```sh
rust/target/debug/tmuxx -D -f /dev/null --native-endpoint /private/path/native
```

Connect command clients with `--native-endpoint /private/path/native`. For C
command/control interoperability, use the tmux-compatible socket selected with
`-S /private/path/tmux`; keep it distinct from the native JSON socket. Supported
C command/control clients can use that socket. Ordinary tty attachment is
rejected explicitly.

A dedicated SSH native channel runs `tmuxx --native-stdio --native-endpoint PATH`
with `ssh -T`. It attaches to the existing native owner and fails if it is absent.
For system tmux, SSH exec runs the selected C binary with `-N -C` against the
existing C daemon. Use shell quoting for executable/socket paths, separate
stderr, and verified host keys. An ambiguous mutation is observed after
reconnect rather than replayed. Persistence requires keeping the standalone
owner alive and acknowledging retention for each pane; closing clients does not
replace the pane's process.

Linux ownership requires pidfd syscalls including `waitid(P_PIDFD)` (Linux 5.4+),
`TIOCGPTPEER` and accessible `/proc` in
the host PID namespace. The spawn broker owns children before exec, retains
exited leader identities, watches the original owner's pidfd even if a forked
worker holds the channel, and cleans registered sessions after SIGKILL of an
embedded host or daemon. Independent `setsid` sessions remain outside that
boundary. See [architecture](ARCHITECTURE.md) for limits and lifetime semantics.

## Collect fresh evidence

Commit implementation/metadata changes first, then rebuild. A changed checkout,
source, reference or candidate invalidates earlier evidence.

```sh
export RUSTUP_TOOLCHAIN=1.95.0
export TMUXX_RUSTTY_ROOT=/tmp/tmuxx-linux-sources/ghostty-org/ghostty
export TMUXX_C_CURRENT=/tmp/tmuxx-linux-references/current/tmux
export TMUXX_C_OLDER=/tmp/tmuxx-linux-references/3.7c/tmux
cargo +1.95.0 fmt --manifest-path rust/Cargo.toml --all -- --check
cargo +1.95.0 build --manifest-path rust/Cargo.toml --locked --offline --workspace
cargo +1.95.0 test --manifest-path rust/Cargo.toml --locked --offline --workspace --all-targets
cargo +1.95.0 clippy --manifest-path rust/Cargo.toml --locked --offline --workspace --all-targets -- -D warnings
python3 -m unittest discover -s rust/conformance -p 'test_*.py'
python3 rust/conformance/generate_command_metadata.py --check
python3 rust/conformance/generate_option_metadata.py --check
python3 rust/conformance/generate_format_metadata.py --check
python3 rust/conformance/runner.py inventory
python3 -u rust/conformance/runner.py smoke \
  --reference "$TMUXX_C_CURRENT" --candidate "$TMUXX_C_CURRENT" --candidate-kind c \
  --report rust/conformance/artifacts/linux-c-c.json
python3 -u rust/conformance/runner.py smoke \
  --reference "$TMUXX_C_CURRENT" --older-reference "$TMUXX_C_OLDER" \
  --candidate rust/target/debug/tmuxx --suite all \
  --report rust/conformance/artifacts/linux-c-rust.json
for profile in command-control system-client native-views standalone app-owned unix-ipc; do
  python3 rust/conformance/runner.py gate \
    --report rust/conformance/artifacts/linux-c-rust.json --profile "$profile"
done
```

The additional 3.7c differential subset is recorded in
`.github/workflows/tmuxx-conformance.yml`; use its exact suite selection with the
absolute older reference and preserve a separate report. Exact ignored tests
must be explicitly executed by their suite definitions: a filtered, missing or
zero-test invocation earns no evidence.

Linux `--suite all` records unavailable desktop suites as blocked and returns
nonzero. Existing `command-control` layout composition and `native-views`
desktop obligations require an actual supported Rustty viewer connected to this
Linux server, including both hosts' source/executable identities. A portable
library run or historical macOS report cannot supply this evidence. Finish and
gate the independent server profiles while preserving those blockers. CI
deliberately runs all six gates and preserves passing and failing reports.

GNU aarch64 uses unsigned plain C `char`; high-byte pending captures and the C
source parser therefore differ from historical signed-char macOS observations.
The tests compare exact target-ABI behavior. Linux signal names follow C's
numeric `sig2name` fallback. Cleanup tests cover session/group nesting,
reparenting, early script exit, timeouts and unresponsive socket owners, with
pidfd or process-start identity protection and an independent server kept alive.
