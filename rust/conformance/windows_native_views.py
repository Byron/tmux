#!/usr/bin/env python3
"""Native HWND graph/retention and shipped-resource checks; requires an interactive desktop.

Every executable is supplied explicitly. Output is fresh evidence, never a claim
that keyboard/IME, clipboard, cross-logon SSH, or the entire profile passed.
"""
from __future__ import annotations

import argparse
import ctypes
from ctypes import wintypes
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import time
import uuid


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def wait_json(path: Path, process: subprocess.Popen, seconds: float = 30) -> dict:
    deadline = time.monotonic() + seconds
    last_error = "file has not been read"
    while time.monotonic() < deadline:
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except (FileNotFoundError, PermissionError, UnicodeDecodeError, json.JSONDecodeError) as error:
            # Rustty's smoke writer exposes the file before write_all finishes.
            # Retry incomplete publication, never a fully parsed bad result.
            last_error = f"{type(error).__name__}: {error}"
        if process.poll() is not None:
            raise AssertionError(f"owner exited {process.returncode} before complete JSON in {path}: {last_error}")
        time.sleep(0.05)
    raise TimeoutError(f"native view did not produce complete JSON in {path}: {last_error}")


def assert_rendered_workspaces(state: dict) -> None:
    """Each host's captured pixels must describe its current full tab/layout state."""
    captured = state.get("rendered_workspaces", {})
    for window in state["workspace"]["windows"]:
        assert captured.get(str(window["id"])) == window, (
            "native screenshot has stale tab/layout metadata", window["id"])


class Fixture:
    def __init__(self, gui: Path, candidate: Path, directory: Path):
        self.gui, self.candidate, self.directory = gui, candidate, directory
        self.processes: list[subprocess.Popen] = []
        self.logs = []
        self.panes: dict[int, int] = {}
        self.checks: list[str] = []
        self.k32 = ctypes.WinDLL("kernel32", use_last_error=True)
        self.k32.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
        self.k32.OpenProcess.restype = wintypes.HANDLE
        self.k32.WaitForSingleObject.argtypes = [wintypes.HANDLE, wintypes.DWORD]
        self.k32.WaitForSingleObject.restype = wintypes.DWORD
        self.k32.CloseHandle.argtypes = [wintypes.HANDLE]
        self.env = os.environ.copy()
        for name in ["TMUXX_ENDPOINT", "TMUXX_CONPTY_RESOURCES", "RUSTTY_TMUXX_SMOKE_DIR",
                     "RUSTTY_TMUXX_SMOKE_HOLD_FILE", "RUSTTY_TMUXX_SMOKE_ATTACH_ONLY",
                     "RUSTTY_TMUXX_SMOKE_FLOATING", "RUSTTY_SMOKE_DIR", "RUSTTY_SMOKE_SECONDS"]:
            self.env.pop(name, None)

    def start(self, argv: list[str], name: str, env: dict | None = None) -> subprocess.Popen:
        log = (self.directory / f"{name}.log").open("wb")
        self.logs.append(log)
        process = subprocess.Popen(argv, stdin=subprocess.DEVNULL, stdout=log, stderr=log,
                                   env=env or self.env, creationflags=subprocess.CREATE_NO_WINDOW)
        self.processes.append(process)
        return process

    def command(self, instance: str, *args: str) -> str:
        completed = subprocess.run([str(self.candidate), "-L", instance, *args],
                                   env=self.env, capture_output=True, timeout=20)
        if completed.returncode:
            raise AssertionError(f"command {args!r}: {completed.stderr.decode('utf-8', 'replace')}")
        return completed.stdout.decode("utf-8")

    def remember(self, state: dict) -> None:
        for pid in state["pane_processes"].values():
            if pid and pid not in self.panes:
                handle = self.k32.OpenProcess(0x00100000, False, pid)  # SYNCHRONIZE only
                if not handle:
                    raise ctypes.WinError(ctypes.get_last_error())
                self.panes[pid] = handle

    def alive(self, pid: int) -> bool:
        return self.k32.WaitForSingleObject(self.panes[pid], 0) == 258

    def assert_dead(self, pids, timeout: float = 5) -> None:
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if not any(self.alive(pid) for pid in pids):
                return
            time.sleep(0.05)
        raise AssertionError(f"test-owned pane processes remain: {[pid for pid in pids if self.alive(pid)]}")

    def view(self, name: str, instance: str, embedded: bool, hold: bool = False, extra_args=()):
        directory = self.directory / name
        directory.mkdir()
        env = self.env | {"RUSTTY_TMUXX_SMOKE_DIR": str(directory), "RUSTTY_TMUXX_SMOKE_VISIBLE": "1"}
        if hold:
            marker = directory / "hold"
            marker.write_text("hold", encoding="utf-8")
            env["RUSTTY_TMUXX_SMOKE_HOLD_FILE"] = str(marker)
        if not embedded:
            env["RUSTTY_TMUXX_SMOKE_ATTACH_ONLY"] = "1"
        mode = "embedded" if embedded else f"pipe:{instance}"
        gui = self.start([str(self.gui), f"--tmuxx={mode}", f"--tmuxx-instance={instance}",
                          "--renderer=software", "--config-default-files=false", "--stream-deck=false", *extra_args],
                         name, env)
        state = wait_json(directory / ("ready.json" if hold else "result.json"), gui)
        assert not state["errors"], state["errors"]
        assert not state["hidden"], "native window was not visible"
        assert state["view_graph_consistent"]
        assert_rendered_workspaces(state)
        self.remember(state)
        return gui, directory, state

    def external_graph(self) -> None:
        instance = "native Ω &^ " + uuid.uuid4().hex
        gui, directory, before = self.view("external-graph", instance, True, True)
        original = before["pane_processes"].copy()
        session = "$" + str(before["server_sessions"][0]["id"])
        window = "@" + str(before["server_windows"][0]["id"])
        command = [sys.executable, "-u", "-c", "import os,time; print('external native pane',os.getpid(),flush=True); time.sleep(180)"]
        self.command(instance, "new-session", "-d", "-s", "external", *command)
        self.command(instance, "new-window", "-d", "-n", "Native 雪", "-t", session, *command)
        self.command(instance, "split-window", "-d", "-h", "-t", window, *command)
        self.command(instance, "link-window", "-s", window, "-t", "external:7")
        self.command(instance, "link-window", "-s", window, "-t", session + ":9")
        self.command(instance, "new-session", "-d", "-s", "grouped", "-t", session)
        (directory / "expected.json").write_text(json.dumps({"sessions": 3, "windows": 3, "panes": 5, "links": 8}), encoding="utf-8")
        (directory / "hold").unlink()
        after = wait_json(directory / "result.json", gui)
        self.remember(after)
        assert after["view_graph_consistent"] and after["windows"] == 3
        assert_rendered_workspaces(after)
        assert after["ui_labels_supported"], "native graph labels contain missing glyphs"
        assert len(after["rendered_hosts"]) == 3
        assert len(after["view_windows"]) == 8 and len(after["view_panes"]) == 18
        assert all(after["pane_processes"][pane] == pid for pane, pid in original.items())
        assert after["instance"] == before["instance"]
        for host in after["native_hosts"]:
            assert (directory / f"window-{host}.png").read_bytes().startswith(b"\x89PNG\r\n\x1a\n")
        assert gui.wait(timeout=20) == 0
        self.assert_dead(after["pane_processes"].values())
        self.checks += ["windows_native_views::external_shared_duplicate_links",
                        "windows_native_views::graceful_app_owner_cleanup"]

    def standalone_restart(self) -> None:
        instance = "retained Ω " + uuid.uuid4().hex
        owner = self.start([str(self.candidate), "-D", "-L", instance], "standalone-owner")
        deadline = time.monotonic() + 15
        while True:
            result = subprocess.run([str(self.candidate), "-L", instance, "list-sessions"],
                                    env=self.env, capture_output=True, timeout=5)
            if result.returncode == 0:
                break
            if owner.poll() is not None or time.monotonic() > deadline:
                raise AssertionError("standalone owner did not become ready")
            time.sleep(0.05)
        command = [sys.executable, "-u", "-c", "import os,time; print('retained native pane',os.getpid(),flush=True); time.sleep(180)"]
        self.command(instance, "new-session", "-d", "-s", "retained", *command)
        self.command(instance, "split-window", "-h", "-t", "retained", *command)
        for pane in self.command(instance, "list-panes", "-a", "-F", "#{pane_id}").splitlines():
            self.command(instance, "tmuxx-retain-pane", "-t", pane, "on")
        gui, _, first = self.view("retained-first", instance, False)
        assert gui.wait(timeout=20) == 0
        assert all(self.alive(pid) for pid in first["pane_processes"].values())
        gui, _, second = self.view("retained-second", instance, False)
        assert gui.wait(timeout=20) == 0
        assert first["pane_processes"] == second["pane_processes"]
        assert first["instance"] == second["instance"]
        assert all(self.alive(pid) for pid in first["pane_processes"].values())
        self.checks.append("windows_native_views::standalone_retained_gui_restart")
        gui, _, held = self.view("retained-abrupt", instance, False, True)
        assert held["pane_processes"] == first["pane_processes"]
        gui.kill()
        gui.wait(timeout=10)
        assert all(self.alive(pid) for pid in first["pane_processes"].values())
        gui, _, restarted = self.view("retained-after-abrupt", instance, False)
        assert gui.wait(timeout=20) == 0
        assert restarted["pane_processes"] == first["pane_processes"]
        assert restarted["instance"] == first["instance"]
        assert all(self.alive(pid) for pid in first["pane_processes"].values())
        self.command(instance, "kill-server")
        assert owner.wait(timeout=10) == 0
        self.assert_dead(first["pane_processes"].values())
        self.checks.append("windows_native_views::standalone_retained_abrupt_gui_restart")

    def abrupt_app_owner(self, abrupt: bool = True) -> None:
        mode = "abrupt" if abrupt else "graceful"
        instance = mode + "-app-" + uuid.uuid4().hex
        unrelated = self.start([sys.executable, "-c", "import time; time.sleep(180)"], mode + "-unrelated")
        gui, directory, before = self.view(mode + "-app", instance, True, True)
        marker = directory / "background.pid"
        script = (
            "import pathlib,subprocess,sys,time; "
            "child=subprocess.Popen([sys.executable,'-c','import time; time.sleep(180)'],"
            "stdin=subprocess.DEVNULL,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,"
            "creationflags=subprocess.CREATE_NEW_PROCESS_GROUP); "
            "marker=pathlib.Path(sys.argv[1]); pending=marker.with_name(marker.name+'.tmp'); "
            "pending.write_text(str(child.pid),encoding='ascii'); pending.replace(marker); "
            "print('APP_BACKGROUND_PID='+str(child.pid),flush=True); time.sleep(180)"
        )
        self.command(instance, "new-window", "-d", sys.executable, "-u", "-c", script, str(marker))
        deadline = time.monotonic() + 10
        while not marker.is_file():
            if gui.poll() is not None or time.monotonic() > deadline:
                raise AssertionError("app-owned background descendant did not start")
            time.sleep(.02)
        child_pid = int(marker.read_text(encoding="ascii"))
        pane_pids = [int(value) for value in self.command(instance, "list-panes", "-a", "-F", "#{pane_pid}").splitlines()]
        owned = pane_pids + [child_pid]
        self.remember({"pane_processes": dict(enumerate(owned))})
        assert all(self.alive(pid) for pid in owned), "app-owned process exited before abrupt-death check"
        assert unrelated.poll() is None
        if abrupt:
            gui.kill()  # TerminateProcess on this exact packaged GUI process.
            gui.wait(timeout=10)
        else:
            (directory / "expected.json").write_text(json.dumps({"sessions": 1, "windows": 2, "panes": 3, "links": 2}), encoding="utf-8")
            (directory / "hold").unlink()
            after = wait_json(directory / "result.json", gui)
            assert not after["errors"] and after["view_graph_consistent"]
            assert set(after["pane_processes"].values()) == set(pane_pids)
            assert gui.wait(timeout=20) == 0
        self.assert_dead(owned)
        assert unrelated.poll() is None, f"{mode} GUI death harmed an unrelated process"
        (directory / (mode + "-result.json")).write_text(json.dumps({
            "owner_pid": gui.pid, "pane_pids": pane_pids, "background_pid": child_pid,
            "unrelated_pid": unrelated.pid, "owned_handles_signaled": True, "unrelated_alive": True,
            "original_pane_pids": before["pane_processes"],
        }, indent=2), encoding="utf-8")
        unrelated.kill()
        unrelated.wait(timeout=5)
        self.checks.append(f"windows_native_views::{mode}_app_owner_descendant_cleanup")

    def negative_resources(self) -> None:
        for executable, label in [(self.gui, "gui"), (self.candidate, "standalone")]:
            for corruption in ["missing", "incompatible"]:
                directory = self.directory / f"{label}-{corruption}"
                directory.mkdir()
                copy = directory / executable.name
                shutil.copy2(executable, copy)
                shutil.copytree(executable.parent / "resources", directory / "resources")
                dlls = list((directory / "resources").rglob("conpty.dll"))
                assert len(dlls) == 1
                if corruption == "incompatible":
                    data = bytearray(dlls[0].read_bytes())
                    data[-1] ^= 1  # preserve length; the member digest must reject it
                    dlls[0].write_bytes(data)
                else:
                    dlls[0].unlink()
                instance = f"negative-{uuid.uuid4().hex}"
                args = [str(copy), "-D", "-L", instance] if label == "standalone" else [
                    str(copy), "--tmuxx=embedded", f"--tmuxx-instance={instance}",
                    "--config-default-files=false", "--stream-deck=false"]
                # The existing ordinary smoke switch suppresses Explorer's modal
                # startup-error box. Resource validation happens before smoke setup.
                child = self.start(args, f"{label}-{corruption}",
                                   self.env | {"RUSTTY_SMOKE_DIR": str(directory / "smoke")})
                assert child.wait(timeout=15) != 0, "invalid runtime unexpectedly started"
                self.logs[-1].flush()
                log = (self.directory / f"{label}-{corruption}.log").read_text(encoding="utf-8", errors="replace")
                assert "ConPTY" in log, log
        self.checks.append("windows_native_views::packaged_missing_incompatible_resources")

    def cleanup(self) -> list[int]:
        for child in reversed(self.processes):
            if child.poll() is None:
                child.kill()
            try:
                child.wait(timeout=10)
            except subprocess.TimeoutExpired:
                pass
        deadline = time.monotonic() + 5
        while any(self.alive(pid) for pid in self.panes) and time.monotonic() < deadline:
            time.sleep(0.05)
        leaked = [pid for pid in self.panes if self.alive(pid)]
        for handle in self.panes.values():
            self.k32.CloseHandle(handle)
        for log in self.logs:
            log.close()
        return leaked


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--gui", type=Path, required=True)
    parser.add_argument("--candidate", type=Path, required=True)
    parser.add_argument("--report", type=Path, required=True)
    args = parser.parse_args()
    if sys.platform != "win32":
        parser.error("requires native Windows")
    args.report.parent.mkdir(parents=True, exist_ok=True)
    directory = Path(tempfile.mkdtemp(prefix="windows-native-views-", dir=args.report.parent))
    fixture = Fixture(args.gui.resolve(strict=True), args.candidate.resolve(strict=True), directory)
    report = {"schema": 1, "kind": "windows-native-views", "artifact_directory": str(directory),
              "gui_sha256": sha256(fixture.gui), "candidate_sha256": sha256(fixture.candidate),
              "tests": [], "failures": [], "cleanup_remaining": []}
    try:
        fixture.external_graph()
        fixture.abrupt_app_owner()
        fixture.abrupt_app_owner(False)
        fixture.standalone_restart()
        fixture.negative_resources()
    except (Exception, KeyboardInterrupt) as error:
        report["failures"].append(f"{type(error).__name__}: {error}")
    finally:
        report["tests"] = fixture.checks
        report["cleanup_remaining"] = fixture.cleanup()
        report["passed"] = not report["failures"] and not report["cleanup_remaining"]
        args.report.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
        print(json.dumps(report))
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
