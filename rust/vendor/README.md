# Vendored Rustty terminal libraries

`rustty-parser` and `rustty-vt` are copied from the neighboring Rustty/Ghostty checkout at revision `cb67824a77fc00bd20e811cce40012893f79b999`. Original source SHA-256 hashes are in `rustty-source.json`; license notices are retained in each crate. These are standalone Rust implementations and do not link Ghostty or C tmux.

Local packaging changes: explicit Cargo dependencies, omitted app-specific example/benchmark targets, and relocated RGB/snapshot/parser-corpus resources with updated include paths. Source tests and Unicode regeneration tools are retained. Unicode tables follow the upstream pinned uucode/Unicode policy documented in `rustty-vt/src/unicode.rs`.

Passing Rustty tests is not evidence of C tmux conformance. `tmuxx-terminal` owns that integration boundary and its documented differences.

`rustty-vt::modes::Modes::iter()` is a local additive API exposing supported mode keys for the tmuxx JSON read model.

Packages are named `tmuxx-vendored-rustty-{parser,vt}` (library names unchanged) so an application can depend on its own Rustty checkout alongside tmuxx. The VT serde dependency enables `rc` for shared graphics pixels.

Additive VT APIs: `Graphics::{view_snapshot,from_view_snapshot}` serialize and validate image/frame pixels, placements, animation state, pending uploads, limits and allocation counters. `Terminal::restore_view_graphics` imports them without emitting host effects. GHOSTSNP retains terminal/parser state; graphics are a separately bounded extension. Native mirrors must suppress application replies and apply a deliberate host-effect recipient policy.

The tmuxx wrapper opts into C OSC52 selector/base64 parsing. Core server policies implement `set-clipboard` and `get-clipboard`; denied OSC52 requests remain silent. Kitty clipboard is a Rustty host extension and retains the native host policy path.

The wrapper also opts into tmux graphics reply/chunk handling and the C fallback 8×16 cell geometry. The image-enabled C reply suite compares 34 upload/query/placement cases with fragmented delivery. Separate suites compare retained pixels, clipping/crops, deletion, alternate-screen ownership, resize/reflow, respawn, SIXEL decoding/overlap and global/per-image quotas; lifecycle cases also check native checkpoint restore. See [terminal-evidence.toml](../conformance/terminal-evidence.toml), especially `graphics-c-reference`, `graphics-pixels`, `graphics-global-quota`, `sixel-retained-state` and `sixel-global-quota`. These are executable contracts; current-source results come from the conformance report and profile gate. Image numbers and nonzero layers remain tested Rustty extensions, with explicit differences rather than C parity claims.
