# Conformance evidence

The Python 3.11+ runner separates **smoke observations** from the release gate.
The contract comes from the architecture and inspected upstream behavior, never
from `Engine::SUPPORTED_COMMANDS` or the commands the first implementation happens
to provide.

The 2026-10-20 macOS collection passed 149 executable suites and all 430 scoped
assertions; all six profile gates passed against that unchanged checkout.
Current C (`next-3.9`) and 3.7c interoperability/SSH evidence are both included.
C/C calibration passed all 12 scenarios, and the additional 3.7c differential
subset passed 12 suites. Four Windows obligations remain deferred and 18 entries
remain outside the profile. Recollect and gate after source or baseline changes.

The commands below assume `./tmux` was built from the pinned reference with
`--enable-images`. Substitute its path if that build lives elsewhere.

```sh
python3 rust/conformance/generate_command_metadata.py --check
python3 rust/conformance/generate_option_metadata.py --check
python3 rust/conformance/generate_format_metadata.py --check
python3 rust/conformance/runner.py inventory
python3 -m unittest discover -s rust/conformance -p 'test_*.py'

# Establish reproducibility using independently isolated C servers.
python3 rust/conformance/runner.py smoke \
  --reference ./tmux --candidate ./tmux --candidate-kind c \
  --report rust/conformance/artifacts/c-c.json

# Compare operations and collect exact named executable-suite evidence.
python3 rust/conformance/runner.py smoke \
  --reference ./tmux --candidate rust/target/debug/tmuxx \
  --older-reference /path/to/tmux-3.7c \
  --suite all \
  --report rust/conformance/artifacts/c-rust.json

# A profile requires complete, fresh evidence beyond smoke comparisons.
python3 rust/conformance/runner.py gate \
  --report rust/conformance/artifacts/c-rust.json --profile command-control
```

Twelve scenarios compare graph creation, shared window links/moves/removal,
split/resize geometry, formats, option rejection without mutation, configuration
preparation/include order, exact captures/ranges and raw-child literal input.
Each scenario earns evidence only for its exact assertion, not the whole command
or a broader scope group. `--scenario NAME` selects a focused rerun.

`*-evidence.toml` maps exact Cargo test names to scoped assertions. `--suite NAME`
selects one suite; `--suite all` includes native runtime, parser/config/format,
terminal/layout, wire codecs, four real C/R pairings and isolated SSH tests.
The complete run requires `--older-reference` pointing to C3.7c. Current and
older pairing/SSH suites run separately inside the same report, with each
executable's version and SHA-256 recorded alongside its exact test output.
The supported-version gate requires both references; missing, changed, wrong
or duplicate executables and ignored/filtered tests cannot satisfy the matrix.
The actual Rustty SSH suite also runs against both binaries. Update the pinned
suite versions deliberately when reviewing a new supported C baseline.
`--no-smoke` runs only selected suites. Every listed test must appear as `ok`
and Cargo must exit successfully; ignored, filtered or zero-test runs fail.
The runner preserves test output and never uses a narrow suite to pass a broad
scope group. Suite definitions enrich existing assertion IDs without duplication.

A reviewed `[[coverage]]` manifest entry can close one requirement or scoped
obligation using `obligation`, an ALL-of `assertions` list, and a `rationale`
explaining the coverage review. Every proof member must name an exact executable
assertion. All suites assigned to that assertion must run and pass; omitted tests,
missing members and any failure keep the obligation blocked. Proofs cannot depend
on other proofs or classify upstream changes. The gate recomputes proof status
from current mappings and recorded executable results, while source and binary
fingerprints still reject stale reports. No closure mappings are inferred from
file names, implemented commands or passing subsets. The manifest now records
reviewed mappings for configuration, observable format fields, terminal state and
images, native view rendering and snapshot recovery, PTY lifetime and access,
Rustty integration, UI policy and selected command/input contracts. Each remains
pending until every listed proof passes on the current checkout. Unreviewed
command flags, option semantics and transport obligations remain separate work;
these mappings cannot turn their narrower passing tests into a full profile pass.

Both sides use short private temporary endpoints, controlled shell/locale,
explicit fixture names and dimensions, bounded readiness polls and subprocess
timeouts. After startup, commands use `-N` so a dead server cannot be silently
replaced. Every subprocess transcript retains byte-preserving argv, stdout,
stderr and exit status. Reports record both executable paths, versions and
hashes, source revision, manifest hash and an implementation fingerprint that
includes the scope and difference ledgers. Failures remain failures.
The fingerprint also covers Cargo manifests/lockfile, vendored terminal/parser
sources and suite definitions. A source change during collection invalidates the
report. Rebuild the candidate before collecting evidence.

Each executable suite runs in a private Unix process session. Timeout cleanup
stops its surviving groups, bounds output draining and preserves stdout/stderr
in the failed report. The upstream script harness also stops its process group
on success, early failure and unwind, before reaping the leader. Detached fixture
servers have bounded command-socket shutdown and a verified peer-PID/start-time
fallback. Cleanup tests require flooded pane helpers to exit while an independent
server remains usable; native sockets and lock files are never command targets.

These are behavior comparisons between separate implementations. They do not
prove that a C client can speak to a Rust imsg server. The `unix-ipc` profile
requires actual client/server pairing evidence independently.

`scope.json` records the reviewed assertion responsibilities for all 299 upstream
regression scripts, 92 command entries, 189 options and 218 format-table fields
at the pinned reference. Its 21 groups explicitly enumerate their surface,
required behavior and presentation exclusions. Source hashes also cover shared
regression helpers and golden fixtures. This is a reviewed scope map, **not a
claim that 299 C regression scripts have been ported or passed**.

The groups preserve graph/process/config/format/terminal/input/image behavior.
Mixed C tests are split by assertion responsibility: retained pixels and image
placements stay required, while the tty SIXEL re-encoding bytes are excluded;
window geometry stays required, while ANSI border glyphs are excluded. Native
snapshot/damage assertions replace observations made through an attached tty.
Chooser/copy/prompt/binding/clock paths need documented native effects or an
explicit unsupported error with no mutation. Pure presentation options also
require an explicit policy; storing an inert value is not conformance. Border
footprint options remain required geometry even though native views paint them.

Format callbacks are also scoped: graph, terminal and control-client
identification state remain required; tmux widget-specific contexts may be
absent. Remote C format values remain byte-preserving client data regardless of
whether the Rust engine implements the callback. Regex/substitution, timestamps and session/window/pane loops now have exact C-backed subsets.
Options/environment/client loops, activity ordering, timestamp relations, runtime
format-job caching and style-aware width/trim have exact scoped comparisons.
Graph identities and link insertion order, client identification and sorted lists,
per-link alerts, silence timers and shell-event payload snapshots have separate
current-C tests. OS PID/socket/user fields use exact identity or relation checks.
All 192 named C callbacks have a source-derived context audit against their C
handlers and Rust dispatch. The no-graph comparison covers 184 context-dependent
or global-default callbacks; eight OS/time/version globals have identity, clock
or explicit implementation-difference proofs. Positive graph/client/process/
terminal contexts have separate all-of mappings. Every proof must pass before
the field-value requirement closes; this audit alone does not certify every
format-language operator or command.

`tmuxx-command::registry` is generated from the registered C command table and
shared by engine validation, scheduler aliases/hooks, CLI startup and
`list-commands`. `inventory` and the Python tests reject metadata drift. After
reviewing a rebase, run `generate_command_metadata.py` and review its checked
Rust diff together with command behavior tests. Syntax metadata never grants
implementation coverage for unsupported presentation commands.

`generate_option_metadata.py` similarly derives the complete option schemas,
defaults and hook scopes. The runtime consumes this hook registry; global option
and hook enumeration is compared with an image-enabled C oracle. Both generators
must pass `--check` after rebases. Startup shell/editor/key defaults are separately
compared through C and Rust executables under controlled environments.

`generate_format_metadata.py` derives the named callback inventory from C for
the no-graph context audit. Its `--check` mode and `inventory` reject callback
metadata drift. Regenerate it only after reviewing callback changes and their
positive-context proofs; generated names alone never grant behavior coverage.

`resource-bounds.toml` records the contextual format depth/output limits, and
`differences.toml` links them to exact C/R outcomes and rejection tests.

After rebasing:

1. Run `inventory`. A new/removed command, option, format or script, or a changed
   source/helper/golden, produces a blocking `review:` entry. A test report cannot
   mark classification work as passed.
2. Inspect the upstream diff, amend the affected group's assertions or add an
   exact scenario, and keep intentional differences in `differences.toml` with
   both sides' tested outcomes. Update source hashes only after that review.
3. Update both baseline revisions, rebuild the reference and candidate, rerun
   C/C when the reference/harness changed, and collect fresh C/R evidence.
4. Run each claimed profile gate. Required pending/missing/deferred assertions,
   stale source/implementation/binaries, and unreviewed changes all block release.

Linux and Windows execution are user-deferred; macOS evidence certifies neither.
The manifest records each platform execution status, reports preserve that matrix,
and gates reject evidence collected for a deferred platform. Required source
responsibilities remain unchanged. CI currently executes macOS only.
Ordinary terminal presentation is the product exclusion; it does not exclude
application terminal state, queries, captures, images, shared input or lifetime.

Parser/preparation/format differential tests run independently:

```sh
cd rust
TMUXX_C_ORACLE="$(pwd)/../tmux" cargo test --offline -p tmuxx-config \
  --test c_reference -- --ignored
```

The C executable tests cover parsing/argv, preparation timing and assignments,
job suppression/boolean short circuit, over fifty format expressions, and two
intentional differences: preservation of literal high bytes and rejection of
NUL/unterminated source quotes. Unit tests cover source errors and resource limits.
The C oracle always runs separately; no C tmux code is linked into Rust. Process
tests need temporary sockets and PTYs. The difference ledger is not an allowlist
for arbitrary mismatches or a normalization layer.

The [CI workflow](../../.github/workflows/tmuxx-conformance.yml) builds separate C
head/3.7c oracles, checks Rust on macOS and gates all six scoped profiles. It
uploads exact evidence even on failure. Missing required assertions, stale
fingerprints or unreviewed upstream changes block those gates; passing smoke or
a subset of named suites is insufficient. Linux and Windows execution remain
deferred.

Current and older C behavior sometimes differ. The [version observations](compatibility-versions.md)
record those differences and their exact tests; older-version CI selects only
shared contracts instead of normalizing changed behavior.
