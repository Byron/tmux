#!/usr/bin/env python3
"""Exact executable C/C, C/R and named-suite evidence; complete profiles gate separately."""

from __future__ import annotations

import argparse
import base64
import collections
import hashlib
import json
import os
from pathlib import Path
import platform
import re
import signal
import subprocess
import sys
import tempfile
import time
import tomllib

import generate_command_metadata
import generate_option_metadata
import generate_format_metadata


HERE = Path(__file__).resolve().parent
ROOT = HERE.parent.parent
MANIFEST = HERE / "manifest.toml"
SCOPE = HERE / "scope.json"
RUSTTY_INTEGRATION = ROOT / "rust/integration/rustty"
UNIX_PLATFORMS = ("darwin", "linux")


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def rustty_root():
    return Path(os.environ.get("TMUXX_RUSTTY_ROOT", ROOT.parent.parent / "ghostty-org/ghostty")).resolve()


def rustty_sources(root):
    paths = [root / "Cargo.toml", root / "Cargo.lock"]
    paths += [path for path in (root / "crates").rglob("*")
              if path.is_file() and not {"target", ".git"}.intersection(path.relative_to(root).parts)]
    return sorted(set(paths))


def rustty_identity():
    root = rustty_root()
    if not (root / "Cargo.toml").is_file():
        raise ValueError(f"Rustty checkout missing: {root}; set TMUXX_RUSTTY_ROOT to the integrated checkout")
    integration = json.loads((RUSTTY_INTEGRATION / "manifest.json").read_text())
    revision = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=root, text=True).strip()
    if revision != integration["base_revision"]:
        raise ValueError("Rustty base revision changed; review and regenerate the integration manifest")
    for name, hashes in integration["files"].items():
        path = root / name
        if not path.is_file() or digest(path) != hashes["result_sha256"]:
            raise ValueError(f"Rustty integration source missing or changed: {name}")
    sources = {str(path.relative_to(root)): digest(path) for path in rustty_sources(root)}
    return {"root": str(root), "revision": revision, "sources": sources,
            "manifest_sha256": digest(RUSTTY_INTEGRATION / "manifest.json"),
            "patch_sha256": digest(RUSTTY_INTEGRATION / "rustty.patch")}


def implementation_fingerprint():
    paths = list((ROOT / "rust/crates").rglob("*.rs"))
    paths += list((ROOT / "rust/crates").rglob("Cargo.toml"))
    paths += [path for path in (ROOT / "rust/vendor").rglob("*") if path.is_file() and not {"target", ".git"}.intersection(path.parts)]
    paths += [ROOT / "rust/Cargo.toml", ROOT / "rust/Cargo.lock", SCOPE]
    paths += list(HERE.glob("*.toml")) + list(HERE.glob("*.py"))
    paths += [RUSTTY_INTEGRATION / name for name in ("manifest.json", "rustty.patch")]
    hasher = hashlib.sha256()
    for path in sorted(paths):
        hasher.update(str(path.relative_to(ROOT)).encode())
        hasher.update(path.read_bytes())
    external = rustty_root()
    hasher.update(b"rustty-sources")
    try:
        hasher.update(subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=external, stderr=subprocess.DEVNULL))
    except (OSError, subprocess.SubprocessError):
        hasher.update(b"missing-checkout-revision")
    for path in rustty_sources(external):
        hasher.update(str(path.relative_to(external)).encode())
        hasher.update(path.read_bytes() if path.is_file() else b"missing")
    return hasher.hexdigest()


def manifest():
    return tomllib.loads(MANIFEST.read_text())


def suites():
    found = {}
    for path in sorted(HERE.glob("*-evidence.toml")):
        for suite in tomllib.loads(path.read_text())["suites"]:
            identifier = suite["id"]
            if identifier in found:
                raise ValueError(f"duplicate evidence suite: {identifier}")
            if not suite["assertions"] or any(not assertion["tests"] for assertion in suite["assertions"]):
                raise ValueError(f"suite {identifier} needs exact named tests for every assertion")
            allowed = suite.get("platforms", list(UNIX_PLATFORMS))
            if not allowed or len(allowed) != len(set(allowed)) or set(allowed) - {"darwin", "linux", "win32"}:
                raise ValueError(f"suite {identifier} has invalid execution platforms")
            found[identifier] = {**suite, "source": str(path.relative_to(ROOT))}
    return found


def suite_platforms(suite):
    return suite.get("platforms", list(UNIX_PLATFORMS))


def select_suites(requested, host_platform):
    """Keep unavailable executable obligations visible without running zero tests."""
    available = suites()
    selected = available if "all" in requested else {name: available[name] for name in requested}
    runnable, blocked = {}, {}
    for name, suite in selected.items():
        if host_platform in suite_platforms(suite):
            runnable[name] = suite
        elif any(host_platform in assertion.get("platforms", [host_platform]) for assertion in suite["assertions"]):
            blocked[name] = {"status": "blocked", "platform": host_platform,
                             "execution_platforms": suite_platforms(suite), "completed_tests": {},
                             "reason": "Required client execution is unavailable on this host; supported desktop/client evidence remains required."}
        elif "all" not in requested:
            raise ValueError(f"suite {name} does not apply to {host_platform}")
    return runnable, blocked


def host_identity():
    def version(command):
        try:
            result = subprocess.run(command, capture_output=True, timeout=5)
            return {"argv": command, "status": result.returncode,
                    "output": (result.stdout + result.stderr).decode("utf-8", "replace").strip()}
        except (OSError, subprocess.SubprocessError) as error:
            return {"argv": command, "error": str(error)}
    rust = version(["rustc", "+1.95.0", "-vV"])
    target = re.search(r"^host: (.+)$", rust.get("output", ""), re.MULTILINE)
    distribution = {}
    if sys.platform == "linux":
        try:
            distribution = platform.freedesktop_os_release()
        except OSError:
            pass
    return {"platform": sys.platform, "architecture": platform.machine(), "kernel": platform.release(),
            "distribution": distribution, "libc": list(platform.libc_ver()),
            "rust": rust, "rust_host_target": target.group(1) if target else None,
            "cargo_build_target": os.environ.get("CARGO_BUILD_TARGET"),
            "python": {"executable": sys.executable, "version": sys.version},
            "openssh_client": version(["ssh", "-V"]), "openssh_server": version(["/usr/sbin/sshd", "-V"])}


def source_revision():
    return subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip()


def inventory(config=None, host_platform=None):
    if generate_command_metadata.OUTPUT.read_text() != generate_command_metadata.generate():
        raise ValueError("C command metadata changed; regenerate and review metadata.rs and parity coverage")
    if generate_format_metadata.OUTPUT.read_text() != generate_format_metadata.generate():
        raise ValueError("C format callbacks changed; regenerate and review format metadata and conformance")
    if generate_option_metadata.OUTPUT.read_text() != generate_option_metadata.generate():
        raise ValueError("C option metadata changed; regenerate and review options_metadata.rs and parity coverage")
    config = config or manifest()
    host_platform = host_platform or sys.platform
    entries = []
    for assertion in config["assertions"]:
        entries.append({**assertion, "requirement": "required", "status": "pending"})
    for group in config["requirements"]:
        for identifier in group["ids"]:
            deferred = all(config["profiles"][p].get("execution") == "deferred" for p in group["profiles"])
            entries.append({"id": identifier, "profiles": group["profiles"], "requirement": "required",
                            "status": "deferred" if deferred else "pending"})
    entries.extend(scope_inventory(config))
    by_id = {entry["id"]: entry for entry in entries}
    for suite in suites().values():
        if any(profile not in config["profiles"] for profile in suite["profiles"]):
            raise ValueError(f"unknown profile in suite {suite['id']}")
        for assertion in suite["assertions"]:
            identifier = assertion["id"]
            if identifier.startswith(("scope:", "review:", "outside:")):
                raise ValueError("narrow suite evidence cannot certify a scope group or classification")
            applicability = assertion.get("platforms")
            if applicability is not None and (not applicability or set(applicability) - set(suite_platforms(suite))):
                raise ValueError(f"assertion {identifier} has invalid applicability platforms")
            if identifier in by_id:
                entry = by_id[identifier]
                if entry.get("platforms") != applicability:
                    raise ValueError(f"assertion {identifier} has inconsistent applicability platforms")
                entry["profiles"] = sorted(set(entry["profiles"]) | set(suite["profiles"]))
                entry.setdefault("description", assertion["description"])
                entry.setdefault("suites", []).append(suite["id"])
            else:
                entry = {"id": identifier, "profiles": suite["profiles"], "requirement": "required", "status": "pending",
                         "description": assertion["description"], "suites": [suite["id"]]}
                if applicability is not None:
                    entry["platforms"] = applicability
                by_id[identifier] = entry
                entries.append(entry)
    for exclusion in config["exclusions"]:
        for identifier in exclusion["assertions"]:
            entries.append({"id": identifier, "profiles": ["presentation"], "requirement": "outside-profile",
                            "status": "outside-profile", "reason": exclusion["reason"]})
    identifiers = [entry["id"] for entry in entries]
    if len(identifiers) != len(set(identifiers)):
        raise ValueError("duplicate conformance assertion IDs")
    obligations = {identifier for group in config["requirements"] for identifier in group["ids"]}
    obligations.update(identifier for identifier in by_id if identifier.startswith("scope:"))
    covered = set()
    for coverage in config.get("coverage", []):
        identifier = coverage["obligation"]
        proof = coverage.get("assertions", [])
        platform_proofs = coverage.get("platform_assertions", {})
        if identifier not in obligations or identifier in covered:
            raise ValueError(f"unknown or duplicate coverage obligation: {identifier}")
        if by_id[identifier].get("suites") or by_id[identifier].get("scenario"):
            raise ValueError(f"coverage {identifier} already has direct evidence; split exact assertions before adding a proof")
        if not proof or len(proof) != len(set(proof)) or not coverage.get("rationale", "").strip():
            raise ValueError(f"coverage {identifier} needs distinct exact assertions and a review rationale")
        applicable = {target for profile in by_id[identifier]["profiles"] for target in config["profiles"][profile]["platforms"]}
        if platform_proofs and set(platform_proofs) != applicable:
            raise ValueError(f"coverage {identifier} needs an exact proof mapping for every applicable platform")
        for target, additions in platform_proofs.items():
            if not additions or len(proof + additions) != len(set(proof + additions)):
                raise ValueError(f"coverage {identifier} has empty or duplicate {target} proof members")
            for source in additions:
                if target not in by_id.get(source, {}).get("platforms", [target]):
                    raise ValueError(f"coverage {identifier} uses an inapplicable {target} proof: {source}")
        all_sources = proof + [source for additions in platform_proofs.values() for source in additions]
        for source in all_sources:
            entry = by_id.get(source, {})
            if source == identifier or source.startswith(("scope:", "review:", "outside:")) or not (entry.get("suites") or entry.get("scenario")):
                raise ValueError(f"coverage {identifier} has no exact executable proof: {source}")
        by_id[identifier]["proof"] = proof + platform_proofs.get(host_platform, [])
        if platform_proofs:
            by_id[identifier]["platform_proofs"] = platform_proofs
        by_id[identifier]["coverage_review"] = coverage["rationale"]
        covered.add(identifier)
    if any(source in covered for identifier in covered for source in by_id[identifier]["proof"]):
        raise ValueError("coverage proofs must be executable assertions, not other derived obligations")
    for entry in entries:
        if host_platform not in entry.get("platforms", [host_platform]):
            entry["status"] = "not-applicable"
    return entries


def discovered(config):
    regressions = {str(path.relative_to(ROOT)) for path in ROOT.glob(config["discovery"]["regressions"])}
    commands = {name for path in ROOT.glob(config["discovery"]["commands"])
                for name in re.findall(r'\.name\s*=\s*"([^"]+)"', path.read_text())}
    options = set(re.findall(r'\.name\s*=\s*"([^"]+)"', (ROOT / config["discovery"]["options"]).read_text()))
    source = (ROOT / config["discovery"]["formats"]).read_text()
    table = source.split("static const struct format_table_entry format_table[] = {", 1)[1].split("\n};", 1)[0]
    formats = set(re.findall(r'\{\s*"([^"]+)"\s*,\s*FORMAT_TABLE_', table))
    return dict(regressions=regressions, commands=commands, options=options, formats=formats)


def scope_inventory(config):
    scope = json.loads(SCOPE.read_text())
    found = discovered(config)
    mapped = {kind: set() for kind in found}
    entries = []
    for group in scope["groups"]:
        for kind in found:
            for name in group[kind]:
                if name in mapped[kind]:
                    raise ValueError(f"duplicate scope mapping: {kind}:{name}")
                mapped[kind].add(name)
        sources = group["regressions"]
        surface = {kind: group[kind] for kind in ("commands", "options", "formats") if group[kind]}
        for number, description in enumerate(group["required"], 1):
            entries.append({"id": f"scope:{group['id']}:{number}", "profiles": group["profiles"],
                            "requirement": "required", "status": "pending", "description": description,
                            "sources": sources, "surface": surface})
        for number, description in enumerate(group["outside"], 1):
            entries.append({"id": f"outside:{group['id']}:{number}", "profiles": ["presentation"],
                            "requirement": "outside-profile", "status": "outside-profile", "reason": description,
                            "sources": sources, "surface": surface})
    for kind in found:
        for name in sorted(found[kind] ^ mapped[kind]):
            entries.append({"id": f"review:{kind}:{name}", "profiles": ["classification"],
                            "requirement": "required", "status": "pending",
                            "reason": "New or removed upstream surface needs explicit assertion disposition."})
    paths = {str(path.relative_to(ROOT)) for path in (ROOT / "regress").rglob("*") if path.is_file()}
    paths |= {str(path.relative_to(ROOT)) for path in ROOT.glob(config["discovery"]["commands"])
              if re.search(r'\.name\s*=', path.read_text())}
    paths |= {config["discovery"]["options"], config["discovery"]["formats"]}
    tracked = subprocess.check_output(
        ["git", "ls-files", "-z", "--", "*.c", "*.h", "*.y", "*.l", "*.ac", "*.am"], cwd=ROOT)
    paths |= {os.fsdecode(path) for path in tracked.split(b"\0") if path}
    reviewed = scope["source_sha256"]
    for path in sorted(paths | reviewed.keys()):
        if path not in paths or path not in reviewed or digest(ROOT / path) != reviewed[path]:
            entries.append({"id": "review:source:" + path, "profiles": ["classification"],
                            "requirement": "required", "status": "pending",
                            "reason": "Source, fixture or shared helper changed; re-review mapped assertions before updating its hash."})
    if scope["reference_revision"] != config["reference_revision"]:
        entries.append({"id": "review:scope-baseline", "profiles": ["classification"],
                        "requirement": "required", "status": "pending",
                        "reason": "Manifest and reviewed assertion scope name different reference revisions."})
    return entries


def counts(entries):
    return dict(sorted(collections.Counter(entry["status"] for entry in entries).items()))


def apply_observations(entries, observations):
    by_id = {entry["id"]: entry for entry in entries}
    for observation in observations:
        identifier = observation["assertion"]
        if identifier not in by_id:
            raise ValueError(f"undeclared assertion: {identifier}")
        if identifier.startswith(("review:", "scope:")) or "proof" in by_id[identifier]:
            raise ValueError("classification requires scope review, not test evidence")
        if by_id[identifier]["requirement"] != "required" or by_id[identifier]["status"] == "not-applicable":
            raise ValueError(f"cannot turn an exclusion into a passing assertion: {identifier}")
        results = by_id[identifier].setdefault("observation_results", {})
        source = observation["scenario"]
        if results.get(source) != "failure":
            results[source] = observation["status"]
        by_id[identifier].setdefault("evidence", []).append(observation["scenario"])
    derive_statuses(entries)
    return entries


def derive_statuses(entries):
    """Require every declared executable source, then every reviewed proof member."""
    by_id = {entry["id"]: entry for entry in entries}
    passing = {"pass", "intentional-difference"}
    for entry in entries:
        if entry["requirement"] != "required" or entry["status"] in ("deferred", "not-applicable") or "proof" in entry:
            continue
        results = entry.get("observation_results", {})
        required = {"suite:" + suite for suite in entry.get("suites", [])}
        if entry.get("scenario"):
            required.add(entry["scenario"])
        entry["status"] = "failure" if "failure" in results.values() else (
            "pass" if required and all(results.get(source) in passing for source in required) else "pending")
    for entry in entries:
        if "proof" not in entry or entry["status"] == "deferred":
            continue
        statuses = [by_id.get(source, {}).get("status") for source in entry["proof"]]
        entry["status"] = "failure" if "failure" in statuses else (
            "pass" if statuses and all(status in passing for status in statuses) else "pending")


def b64(value):
    return base64.b64encode(value).decode("ascii")


class Server:
    def __init__(self, executable, kind):
        self.executable = str(Path(executable).resolve(strict=True))
        self.kind = kind
        # Keep socket names short enough for macOS sockaddr_un.
        self.directory = tempfile.TemporaryDirectory(prefix="txc-", dir="/tmp")
        self.endpoint = Path(self.directory.name) / "s"
        self.trace = []
        self.started = False
        self.base = [self.executable, "-f", "/dev/null"]
        self.base += ["-S" if kind == "c" else "--native-endpoint", str(self.endpoint)]
        self.env = {"PATH": "/usr/bin:/bin", "LC_ALL": "C.UTF-8", "TERM": "screen", "SHELL": "/bin/sh"}

    def command(self, *args, check=True):
        result = subprocess.run(self.base + (["-N"] if self.started else []) + list(args), env=self.env, cwd=ROOT,
                                capture_output=True, timeout=8)
        self.trace.append({"argv_base64": [b64(os.fsencode(arg)) for arg in args],
                           "status": result.returncode, "stdout_base64": b64(result.stdout),
                           "stderr_base64": b64(result.stderr)})
        if check and result.returncode:
            raise AssertionError(f"{args!r}: status {result.returncode}; stdout={result.stdout!r}; stderr={result.stderr!r}")
        return result

    def start(self, child="exec sleep 60"):
        self.command("new-session", "-d", "-s", "parity", "-n", "first", "-x", "80", "-y", "24", child)
        self.started = True
        self.command("has-session", "-t", "parity")
        if not self.endpoint.exists():
            raise AssertionError("chosen implementation did not create its isolated endpoint")

    def wait_capture(self, marker):
        deadline = time.monotonic() + 8
        while True:
            result = self.command("capture-pane", "-p", "-t", "parity:0.0")
            if marker in result.stdout:
                return result.stdout
            if time.monotonic() >= deadline:
                raise AssertionError(f"pane did not emit {marker!r}; last capture={result.stdout!r}")
            time.sleep(0.01)

    def close(self):
        try:
            self.command("kill-server", check=False)
        except (OSError, subprocess.TimeoutExpired):
            pass
        self.directory.cleanup()


def graph(server):
    server.start()
    server.command("split-window", "-h", "-d", "-t", "parity:0", "exec sleep 60")
    server.command("new-window", "-d", "-t", "parity", "-n", "second", "exec sleep 60")
    server.command("rename-window", "-t", "parity:1", "renamed")
    return {
        "sessions": server.command("list-sessions", "-F", "#{session_id}:#{session_name}:#{session_windows}").stdout,
        "windows": server.command("list-windows", "-t", "parity", "-F", "#{window_id}:#{window_index}:#{window_name}:#{window_panes}").stdout,
        "panes": server.command("list-panes", "-s", "-t", "parity", "-F", "#{window_id}:#{pane_id}:#{pane_index}").stdout,
    }


def formats(server):
    server.start()
    server.command("set-option", "-g", "@label", "value with spaces")
    expressions = ["#{session_name}:#{window_name}:#{pane_id}", "#{@label}",
                   "#{?#{==:#{session_name},parity},yes#,please,no}", "#{&&:1,0}",
                   "#S:#D:##:#,", "#{l:#{session_name}}"]
    return {expression: server.command("display-message", "-p", "-t", "parity:0.0", expression).stdout
            for expression in expressions}


def capture(server):
    server.start("printf 'ALPHA\\n\\033[31mRED\\033[0m\\nCAPTURE-READY'; exec sleep 60")
    return {"capture": server.wait_capture(b"CAPTURE-READY")}


def literal_input(server):
    server.start("stty raw -echo; printf INPUT-READY; exec cat")
    server.wait_capture(b"INPUT-READY")
    server.command("send-keys", "-l", "-t", "parity:0.0", "roundtrip-literal-$-semicolon\\;")
    return {"capture": server.wait_capture(b"roundtrip-literal-$-semicolon;")}


def linked_graph(server):
    server.start()
    server.command("new-session", "-d", "-s", "other", "-n", "second", "-x", "80", "-y", "24", "exec sleep 60")
    server.command("link-window", "-d", "-s", "parity:0", "-t", "other:5")
    graph_format = "#{session_name}:#{window_index}:#{window_id}:#{window_name}:#{window_panes}"
    result = {"linked": server.command("list-windows", "-a", "-F", graph_format).stdout}
    server.command("rename-window", "-t", "other:5", "shared")
    result["shared-rename"] = server.command("list-windows", "-a", "-F", graph_format).stdout
    server.command("move-window", "-d", "-s", "other:0", "-t", "parity:3")
    result["moved"] = server.command("list-windows", "-a", "-F", graph_format).stdout
    server.command("unlink-window", "-t", "other:5")
    result["unlinked"] = server.command("list-windows", "-a", "-F", graph_format).stdout
    result["surviving-sessions"] = server.command("list-sessions", "-F", "#{session_name}:#{session_windows}").stdout
    return result


def geometry(server):
    server.start()
    server.command("split-window", "-d", "-h", "-b", "-l", "20", "-t", "parity:0.0", "exec sleep 60")
    server.command("split-window", "-d", "-v", "-l", "5", "-t", "parity:0.0", "exec sleep 60")
    fields = "#{pane_id}:#{pane_index}:#{pane_left}:#{pane_top}:#{pane_width}:#{pane_height}:#{pane_active}"
    result = {"split": server.command("list-panes", "-t", "parity:0", "-F", fields).stdout}
    server.command("resize-window", "-t", "parity:0", "-x", "100", "-y", "30")
    result["resized"] = server.command("list-panes", "-t", "parity:0", "-F", fields).stdout
    return result


def nested_geometry(server):
    server.start()
    fields = "#{pane_id}:#{pane_left}:#{pane_top}:#{pane_width}:#{pane_height}:#{pane_active}"
    snapshot = lambda: server.command("list-panes", "-t", "parity:0", "-F", fields).stdout
    server.command("split-window", "-d", "-h", "-t", "parity:0", "exec sleep 60")
    result = {"default-split-80": snapshot()}
    server.command("resize-window", "-t", "parity:0", "-x", "100", "-y", "30")
    result["default-split-100"] = snapshot()
    server.command("split-window", "-d", "-v", "-t", "%0", "exec sleep 60")
    layout = b"100x30,0,0{30x30,0,0[30x9,0,0,0,30x20,0,10,2],69x30,31,0,1}"
    checksum = 0
    for byte in layout:
        checksum = (((checksum >> 1) | ((checksum & 1) << 15)) + byte) & 0xffff
    server.command("select-layout", "-t", "parity:0", f"{checksum:04x}," + layout.decode())
    result["custom-ratios"] = snapshot()
    server.command("resize-pane", "-t", "%2", "-y", "8")
    server.command("resize-pane", "-t", "%1", "-x", "40")
    result["last-pane-resize"] = snapshot()
    server.command("resize-pane", "-Z", "-t", "%2")
    result["zoom"] = snapshot()
    server.command("resize-pane", "-Z", "-t", "%2")
    result["unzoom"] = snapshot()
    server.command("kill-pane", "-t", "%2")
    result["remove-neighbor"] = snapshot()
    server.command("new-window", "-d", "-t", "parity:1", "-n", "before", "exec sleep 60")
    server.command("resize-window", "-t", "parity:1", "-x", "80", "-y", "24")
    server.command("split-window", "-d", "-b", "-h", "-t", "parity:1", "exec sleep 60")
    result["before-split"] = server.command("list-panes", "-t", "parity:1", "-F", fields).stdout
    return result


def option_validation(server):
    server.start()
    result = {}
    for name, valid, invalid in [("history-limit", "10", "-1"), ("base-index", "2", "invalid"),
                                  ("remain-on-exit", "on", "nonsense")]:
        server.command("set-option", "-g", name, valid)
        before = server.command("show-options", "-gqv", name).stdout
        rejected = server.command("set-option", "-g", name, invalid, check=False)
        after = server.command("show-options", "-gqv", name).stdout
        # Exact diagnostics remain in the trace; here the assertion is rejection
        # with no mutation, independent of source-path prefixes in an error.
        result[name] = str(rejected.returncode).encode() + b":" + before + b":" + after
    server.command("set-option", "-g", "@value", "a")
    server.command("set-option", "-ga", "@value", "b")
    result["user-option-append"] = server.command("show-options", "-gqv", "@value").stdout
    return result


def config_order(server):
    server.start()
    directory = Path(server.directory.name)
    child = directory / "child.conf"
    child.write_text("set-option -g @included included\n")
    source = directory / "main.conf"
    source.write_text("TMUXX_VALUE=early\nset-environment -g TMUXX_VALUE late\n"
                      "set-option -g @flag 1\n%if #{@flag}\nset-option -g @branch wrong\n"
                      "%else\nset-option -g @branch prepared\n%endif\n"
                      "set-option -g @value \"$TMUXX_VALUE\"\n"
                      f"source-file {child}\nset-option -gF @after '#{{@included}}'\n")
    server.command("set-option", "-g", "@flag", "0")
    server.command("source-file", str(source))
    return {name: server.command("show-options", "-gqv", name).stdout
            for name in ("@branch", "@value", "@included", "@after")}


def capture_ranges(server):
    server.start("printf 'FIRST\\nSECOND\\nTHIRD\\nCAPTURE-READY'; exec sleep 60")
    server.wait_capture(b"CAPTURE-READY")
    return {"bounded": server.command("capture-pane", "-p", "-t", "parity:0.0", "-S", "1", "-E", "2").stdout,
            "joined": server.command("capture-pane", "-pJ", "-t", "parity:0.0", "-S", "0", "-E", "2").stdout}


def environment(server):
    server.start()
    server.command("set-environment", "-g", "TMUXX_GLOBAL", "old")
    server.command("set-environment", "-g", "TMUXX_GLOBAL", "updated")
    server.command("set-environment", "-t", "parity", "TMUXX_GONE", "removed")
    server.command("set-environment", "-rt", "parity", "TMUXX_GONE")
    server.command("set-environment", "-ht", "parity", "TMUXX_HIDDEN", "hidden-value")
    server.command("set-environment", "-t", "parity", "TMUXX_QUOTE", 'a"$`\\z')
    result = {
        "removed": server.command("show-environment", "-t", "parity", "TMUXX_GONE").stdout,
        "hidden-filter": server.command("show-environment", "-t", "parity", "TMUXX_HIDDEN").stdout,
        "hidden": server.command("show-environment", "-ht", "parity", "TMUXX_HIDDEN").stdout,
        "quoted": server.command("show-environment", "-st", "parity", "TMUXX_QUOTE").stdout,
        "format-hidden": server.command("display-message", "-p", "-t", "parity:0", "#{TMUXX_HIDDEN}").stdout,
    }
    server.command("new-window", "-d", "-t", "parity", "-n", "environment",
                   "printf 'ENV:%s:%s:%s:END' \"${TMUXX_GLOBAL-unset}\" \"${TMUXX_GONE-unset}\" \"${TMUXX_HIDDEN-unset}\"; exec sleep 60")
    deadline = time.monotonic() + 5
    while True:
        data = server.command("capture-pane", "-pt", "parity:environment").stdout
        if b":END" in data:
            result["child"] = data
            break
        if time.monotonic() >= deadline:
            raise AssertionError(f"environment child did not start: {data!r}")
        time.sleep(0.01)
    return result


def scoped_options(server):
    server.start()
    server.command("set-option", "-t", "parity:0", "remain-on-exit", "on")
    server.command("set-option", "-t", "parity", "history-limit", "3")
    result = {
        "inferred-window-scope": server.command("show-window-options", "-vt", "parity:0", "remain-on-exit").stdout,
        "session-local": server.command("show-options", "-vt", "parity", "history-limit").stdout,
        "global-unchanged": server.command("show-options", "-gv", "history-limit").stdout,
        "absent-local": server.command("show-options", "-vt", "parity", "base-index").stdout,
        "inherited": server.command("show-options", "-Avt", "parity", "base-index").stdout,
    }
    server.command("set-option", "-ut", "parity", "history-limit")
    result["unset-local"] = server.command("show-options", "-vt", "parity", "history-limit").stdout
    result["unset-inherits"] = server.command("show-options", "-Avt", "parity", "history-limit").stdout
    server.command("set-option", "-gt", "parity", "history-limit", "17")
    server.command("set-option", "-gu", "history-limit")
    result["reset-global"] = server.command("show-options", "-gv", "history-limit").stdout
    return result


SCENARIOS = {"graph": graph, "format": formats, "capture": capture, "input": literal_input,
             "linked-graph": linked_graph, "geometry": geometry, "options": option_validation,
             "config-order": config_order, "capture-ranges": capture_ranges, "nested-geometry": nested_geometry,
             "environment": environment, "scoped-options": scoped_options}


def run_side(executable, kind, scenario):
    server = Server(executable, kind)
    try:
        observations = SCENARIOS[scenario](server)
        return {"status": "pass", "observations": {key: b64(value) for key, value in observations.items()},
                "trace": server.trace}
    except (AssertionError, OSError, subprocess.TimeoutExpired) as error:
        return {"status": "failure", "error": str(error), "trace": server.trace}
    finally:
        server.close()


def executable_identity(path):
    path = Path(path).resolve(strict=True)
    result = subprocess.run([str(path), "-V"], capture_output=True, timeout=5)
    if result.returncode:
        raise ValueError(f"cannot identify executable {path}: {result.stderr!r}")
    return {"path": str(path), "sha256": digest(path), "version": result.stdout.decode("utf-8", "replace").strip()}


def suite_reference(suite, references):
    role = suite.get("reference", "current")
    if role not in ("current", "older"):
        raise ValueError(f"unknown reference role in {suite['id']}: {role}")
    identity = references.get(role)
    if not identity:
        raise ValueError(f"{suite['id']} requires --older-reference")
    expected = suite.get("reference_version")
    if expected and identity.get("version") != expected:
        raise ValueError(f"{suite['id']} requires {expected}, got {identity.get('version')}")
    if role == "older" and identity.get("sha256") == (references.get("current") or {}).get("sha256"):
        raise ValueError("current and older references must be different C executables")
    return identity


def suite_observations(suite, returncode, output):
    completed = {name: result for name, result in re.findall(r"^test (\S+) \.\.\. (ok|FAILED|ignored)(?:[ \t].*)?$", output, re.MULTILINE)}
    observations = []
    for assertion in suite["assertions"]:
        passed = returncode == 0 and all(completed.get(name) == "ok" for name in assertion["tests"])
        observations.append({"assertion": assertion["id"], "scenario": "suite:" + suite["id"], "status": "pass" if passed else "failure"})
    return observations, completed


def stop_suite_session(process):
    """Stop only live process groups in the Unix session created for this suite."""
    errors = []
    if os.name == "posix":
        for _ in range(3):
            groups = {}
            try:
                rows = subprocess.check_output(["ps", "-axo", "pid=,pgid=,stat="], timeout=2)
                for row in rows.splitlines():
                    pid, group, state = row.split()
                    pid, group = int(pid), int(group)
                    try:
                        if not state.startswith(b"Z") and os.getsid(pid) == process.pid:
                            groups[group] = pid
                    except ProcessLookupError:
                        pass
            except (OSError, ValueError, subprocess.SubprocessError) as error:
                errors.append(f"could not enumerate suite session: {error}")
                groups[process.pid] = process.pid
            for group, pid in groups.items():
                try:
                    # Revalidate the representative immediately before signalling.
                    if os.getsid(pid) == process.pid and os.getpgid(pid) == group:
                        os.killpg(group, signal.SIGKILL)
                except ProcessLookupError:
                    pass
                except OSError as error:
                    errors.append(f"could not stop suite process group {group}: {error}")
            if not groups:
                break
            time.sleep(0.02)
    try:
        process.kill()
    except ProcessLookupError:
        pass
    except OSError as error:
        errors.append(f"could not stop suite child: {error}")
    return errors


def run_suite_process(command, *, cwd, env, timeout):
    process = subprocess.Popen(command, cwd=cwd, env=env, stdout=subprocess.PIPE,
                               stderr=subprocess.PIPE, start_new_session=os.name == "posix")
    try:
        stdout, stderr = process.communicate(timeout=timeout)
    except subprocess.TimeoutExpired as error:
        cleanup_errors = stop_suite_session(process)
        try:
            stdout, stderr = process.communicate(timeout=2)
        except subprocess.TimeoutExpired as drain:
            # A separately detached process may still hold inherited pipe writers.
            stdout, stderr = drain.output or error.output or b"", drain.stderr or error.stderr or b""
            process.stdout.close()
            process.stderr.close()
            cleanup_errors.append("suite output pipes remained open after session cleanup")
            try:
                process.wait(timeout=2)
            except subprocess.TimeoutExpired:
                cleanup_errors.append("suite child could not be reaped within cleanup timeout")
        error.output, error.stderr = stdout, stderr
        error.cleanup_errors = cleanup_errors
        raise
    return subprocess.CompletedProcess(command, process.returncode, stdout, stderr)


def run_suite(suite, reference):
    command = ["cargo", *suite["args"]]
    cwd = ROOT / "rust"
    env = os.environ.copy()
    env.update({key: str(reference) if value == "$reference" else value for key, value in suite.get("env", {}).items()})
    env["CARGO_TERM_COLOR"] = "never"
    try:
        if sys.platform not in suite_platforms(suite):
            raise ValueError(f"suite {suite['id']} requires execution on {suite_platforms(suite)}, not {sys.platform}")
        external = None
        if suite.get("kind") in ("rustty-cargo", "rustty-system-ssh", "rustty-desktop-smoke"):
            external = rustty_identity()
            cwd = Path(external["root"])
            if suite["kind"] == "rustty-system-ssh":
                command = [sys.executable, str(HERE / "rustty_system_ssh.py"), "--rustty", str(cwd), "--reference", str(reference)]
            elif suite["kind"] == "rustty-desktop-smoke":
                command = [sys.executable, str(HERE / "rustty_desktop_smoke.py"), "--rustty", str(cwd)]
        elif suite.get("kind", "cargo") != "cargo":
            raise ValueError(f"unknown suite kind: {suite['kind']}")
        result = run_suite_process(command, cwd=cwd, env=env, timeout=suite.get("timeout", 300))
        output = result.stdout.decode("utf-8", "replace")
        observations, completed = suite_observations(suite, result.returncode, output)
        details = {"argv": command, "cwd": str(cwd), "env": {key: env[key] for key in suite.get("env", {})}, "status": result.returncode,
                   "stdout_base64": b64(result.stdout), "stderr_base64": b64(result.stderr), "completed_tests": completed}
        if external:
            details["rustty"] = external
            if external != rustty_identity():
                raise ValueError("Rustty sources changed during suite execution")
    except subprocess.TimeoutExpired as error:
        stdout, stderr = error.output or b"", error.stderr or b""
        observations, completed = suite_observations(suite, -1, stdout.decode("utf-8", "replace"))
        details = {"argv": command, "cwd": str(cwd), "status": -1, "error": str(error),
                   "stdout_base64": b64(stdout), "stderr_base64": b64(stderr), "completed_tests": completed,
                   "cleanup_errors": getattr(error, "cleanup_errors", [])}
    except (ValueError, OSError, subprocess.SubprocessError) as error:
        observations, _ = suite_observations(suite, -1, "")
        details = {"argv": command, "status": -1, "error": str(error)}
    details["platform"] = sys.platform
    return observations, details


def smoke(args):
    config = manifest()
    fingerprint = implementation_fingerprint()
    reference = executable_identity(args.reference)
    if not reference["version"].startswith("tmux "):
        raise ValueError("reference must identify as C tmux")
    older = executable_identity(args.older_reference) if args.older_reference else None
    if older and not older["version"].startswith("tmux "):
        raise ValueError("older reference must identify as C tmux")
    references = {"current": reference, "older": older}
    observations = []
    details = {}
    selected, suite_details = select_suites(args.suite or [], sys.platform)
    blocked_suites = list(suite_details)
    for name in blocked_suites:
        print(f"suite {name}: blocked ({suite_details[name]['reason']})", flush=True)
    if selected and args.candidate_kind != "rust":
        raise ValueError("Rust executable suites cannot be attached to C/C evidence")
    selected_references = {name: suite_reference(suite, references) for name, suite in selected.items()}
    for name, suite in selected.items():
        evidence, suite_details[name] = run_suite(suite, selected_references[name]["path"])
        suite_details[name]["reference"] = selected_references[name]
        observations.extend(evidence)
        passed = all(item["status"] == "pass" for item in evidence)
        print(f"suite {name}: {'pass' if passed else 'failure'}", flush=True)
        if not passed:
            failed = suite_details[name]
            print(f"  {failed.get('error', 'status ' + str(failed['status']))}", flush=True)
            for key in ("stdout_base64", "stderr_base64"):
                if failed.get(key):
                    print(base64.b64decode(failed[key]).decode("utf-8", "replace")[-8000:], flush=True)
    candidate = executable_identity(args.candidate)
    if args.candidate_kind == "rust" and not candidate["version"].startswith("tmuxx "):
        raise ValueError("Rust candidate must identify as tmuxx; refusing accidental C/C evidence")
    assertions = {entry["scenario"]: entry["id"] for entry in config["assertions"]}
    for scenario in ([] if args.no_smoke else args.scenario or SCENARIOS):
        left = run_side(args.reference, "c", scenario)
        right = run_side(args.candidate, args.candidate_kind, scenario)
        passed = left["status"] == right["status"] == "pass" and left["observations"] == right["observations"]
        status = "pass" if passed else "failure"
        observations.append({"assertion": assertions[scenario], "scenario": scenario, "status": status})
        details[scenario] = {"reference": left, "candidate": right}
        print(f"{scenario}: {status}")
        if not passed:
            print(f"  reference: {left.get('error', left.get('observations'))}")
            print(f"  candidate: {right.get('error', right.get('observations'))}")
    entries = apply_observations(inventory(config, sys.platform), observations)
    changed = fingerprint != implementation_fingerprint()
    references_changed = any(identity and (not Path(identity["path"]).is_file() or digest(identity["path"]) != identity["sha256"]) for identity in references.values())
    report = {"schema_version": 2, "kind": "exact-assertion-evidence", "candidate_kind": args.candidate_kind,
              "checkout_revision": source_revision(), "reference_revision": config["reference_revision"], "manifest_sha256": digest(MANIFEST),
              "implementation_fingerprint": fingerprint, "source_changed_during_run": changed, "platform": sys.platform, "host": host_identity(), "platform_execution": config["platform_execution"],
              "reference": reference, "older_reference": older, "references_changed_during_run": references_changed,
              "candidate": candidate, "summary": counts(entries),
              "entries": entries, "scenarios": details, "suites": suite_details, "blocked_suites": blocked_suites, "profile_release_ready": False}
    destination = Path(args.report)
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(json.dumps(report, indent=2) + "\n")
    print(f"Exact assertions only. Full inventory: {report['summary']}. No profile certified.")
    print(f"Evidence: {destination}")
    if changed:
        print("Source changed during evidence collection; rerun before using this report.")
    if references_changed:
        print("C reference changed during evidence collection; rerun before using this report.")
    return 0 if observations and not blocked_suites and not changed and not references_changed and all(item["status"] == "pass" for item in observations) else 1


def blockers(report, profile, config=None):
    config = config or manifest()
    if profile not in config["profiles"]:
        raise ValueError(f"unknown profile {profile}")
    problems = []
    if report.get("candidate_kind") != "rust":
        problems.append("C/C establishes the reference harness, not Rust conformance")
    if report.get("manifest_sha256") != digest(MANIFEST):
        problems.append("manifest changed since evidence was collected")
    if report.get("checkout_revision") != source_revision():
        problems.append("checkout revision changed since evidence was collected")
    if report.get("reference_revision") != config["reference_revision"]:
        problems.append("reviewed C baseline changed since evidence was collected")
    if report.get("implementation_fingerprint") != implementation_fingerprint():
        problems.append("implementation changed since evidence was collected")
    if report.get("source_changed_during_run"):
        problems.append("source changed during evidence collection")
    if report.get("references_changed_during_run"):
        problems.append("C reference changed during evidence collection")
    baseline = subprocess.run(["git", "merge-base", "--is-ancestor", config["reference_revision"], "HEAD"],
                              cwd=ROOT, capture_output=True)
    if baseline.returncode:
        problems.append("reviewed C baseline is missing or not an ancestor; review the upstream history")
    for role in ("reference", "candidate", *(["older_reference"] if report.get("older_reference") else [])):
        recorded = report.get(role, {})
        path = recorded.get("path")
        if not path or not Path(path).is_file() or digest(path) != recorded.get("sha256"):
            problems.append(f"{role} executable is missing or changed since evidence was collected")
    if config.get("platform_execution", {}).get(report.get("platform"), {}).get("status") == "deferred":
        problems.append(f"{report.get('platform')} execution is user-deferred, not certified")
    if report.get("platform") not in config["profiles"][profile]["platforms"]:
        problems.append(f"report platform does not certify {profile}")
    host = report.get("host", {})
    if host.get("platform") != report.get("platform"):
        problems.append("report lacks matching host-platform identity")
    if report.get("platform") == "linux":
        if not host.get("architecture") or not host.get("kernel") or not host.get("distribution", {}).get("ID"):
            problems.append("GNU/Linux evidence requires distribution, kernel and architecture identity")
        if (host.get("libc") or [None])[0] != "glibc" or not (host.get("rust_host_target") or "").endswith("-linux-gnu"):
            problems.append("this Linux qualification requires an identified GNU target and glibc host")
        if host.get("cargo_build_target") not in (None, host.get("rust_host_target")):
            problems.append("cross-compiled test targets require separate executable qualification")
    current_entries = inventory(config, report.get("platform"))
    evidence = {entry["id"]: entry for entry in report.get("entries", [])}
    for entry in current_entries:
        entry["observation_results"] = dict(evidence.get(entry["id"], {}).get("observation_results", {}))
    required = {entry["id"] for entry in current_entries if entry["status"] != "not-applicable" and
                (profile in entry["profiles"] or "classification" in entry["profiles"])}
    required.update(source for entry in current_entries if entry["id"] in required for source in entry.get("proof", []))
    by_id = {entry["id"]: entry for entry in current_entries}
    references = {"current": report.get("reference"), "older": report.get("older_reference")}
    for suite in suites().values():
        if not any(assertion["id"] in required for assertion in suite["assertions"]):
            continue
        details = report.get("suites", {}).get(suite["id"], {})
        if report.get("platform") not in suite_platforms(suite):
            problems.append(f"{suite['id']}: requires supported client execution on {', '.join(suite_platforms(suite))}; "
                            "a local or historical desktop result does not qualify this server host")
            # In particular, copied macOS observations must not pass Linux gates.
            for assertion in suite["assertions"]:
                by_id[assertion["id"]]["observation_results"].pop("suite:" + suite["id"], None)
            continue
        try:
            if details.get("platform") != report.get("platform"):
                raise ValueError(f"{suite['id']} lacks matching execution-platform evidence")
            expected = suite_reference(suite, references)
            if details.get("reference") != expected:
                raise ValueError(f"{suite['id']} lacks matching executable reference evidence")
            output = base64.b64decode(details.get("stdout_base64", ""), validate=True).decode("utf-8", "replace")
            observations, _ = suite_observations(suite, details.get("status", -1), output)
        except (ValueError, TypeError) as error:
            problems.append(str(error))
            observations, _ = suite_observations(suite, -1, "")
        for observation in observations:
            results = by_id[observation["assertion"]]["observation_results"]
            if results.get(observation["scenario"]) != "failure":
                results[observation["scenario"]] = observation["status"]
    derive_statuses(current_entries)
    for entry in current_entries:
        identifier = entry["id"]
        if profile not in entry["profiles"] and "classification" not in entry["profiles"]:
            continue
        if entry["status"] == "not-applicable":
            continue
        if entry["requirement"] == "required" and entry["status"] not in ("pass", "intentional-difference"):
            problems.append(f"{identifier}: {entry['status'] if identifier in evidence else 'missing evidence'}")
    return problems


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="action", required=True)
    inv = sub.add_parser("inventory", help="show reviewed scoped assertions and upstream drift without certifying them")
    inv.add_argument("--json", action="store_true")
    smoke_parser = sub.add_parser("smoke", help="run declared narrow C/C or C/R scenarios, not the complete release gate")
    smoke_parser.add_argument("--reference", required=True)
    smoke_parser.add_argument("--older-reference", help="explicit C3.7c executable required by the supported-version suites")
    smoke_parser.add_argument("--candidate", required=True)
    smoke_parser.add_argument("--candidate-kind", choices=("c", "rust"), default="rust")
    smoke_parser.add_argument("--scenario", choices=SCENARIOS, action="append")
    smoke_parser.add_argument("--suite", choices=["all", *suites()], action="append", help="collect exact named Cargo test evidence")
    smoke_parser.add_argument("--no-smoke", action="store_true", help="collect selected suites without C/R smoke scenarios")
    smoke_parser.add_argument("--report", default=str(HERE / "artifacts/smoke.json"))
    gate = sub.add_parser("gate", help="fail on pending/deferred/missing assertions or stale evidence")
    gate.add_argument("--report", required=True)
    gate.add_argument("--profile", required=True)
    args = parser.parse_args(argv)
    try:
        if args.action == "inventory":
            entries = inventory()
            if args.json:
                print(json.dumps({"source_revision": source_revision(), "summary": counts(entries), "entries": entries}, indent=2))
            else:
                print(f"Scoped assertions: {len(entries)}; {counts(entries)}")
                print(f"Reviewed source surface: { {kind: len(names) for kind, names in discovered(manifest()).items()} }")
                print(f"Upstream changes requiring review: {sum(e['id'].startswith('review:') for e in entries)}")
                print(f"Platform execution: { {platform: record['status'] for platform, record in manifest()['platform_execution'].items()} }")
                print("This inventory is independent of Engine::SUPPORTED_COMMANDS. No profile certified.")
            return 0
        if args.action == "smoke":
            return smoke(args)
        report = json.loads(Path(args.report).read_text())
        problems = blockers(report, args.profile)
        if problems:
            print(f"{args.profile}: BLOCKED ({len(problems)} obligations or evidence problems)")
            print("\n".join(problems[:20]))
            return 1
        print(f"{args.profile}: PASS")
        return 0
    except (OSError, ValueError, subprocess.SubprocessError) as error:
        print(f"conformance: {error}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
