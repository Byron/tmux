#!/usr/bin/env python3
"""Run Rustty's actual system-tmux view test through an isolated loopback sshd."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import pwd
import shlex
import socket
import subprocess
import tempfile
import time


def run():
    parser = argparse.ArgumentParser()
    parser.add_argument('--rustty', required=True, type=Path)
    parser.add_argument('--reference', required=True, type=Path)
    parser.add_argument('--output', type=Path, help='retain JSON evidence and the Cargo log')
    parser.add_argument('--sshd', default='/usr/sbin/sshd')
    parser.add_argument('--ssh', default='/usr/bin/ssh')
    parser.add_argument('--ssh-keygen', default='/usr/bin/ssh-keygen')
    args = parser.parse_args()
    reference = args.reference.resolve()
    with tempfile.TemporaryDirectory(prefix='rustty-system-ssh-') as directory:
        root = Path(directory)
        for name in ('host', 'client'):
            subprocess.run([args.ssh_keygen, '-q', '-t', 'ed25519', '-N', '', '-f', str(root / name)], check=True)
        with socket.socket() as listener:
            listener.bind(('127.0.0.1', 0))
            port = listener.getsockname()[1]
        user = pwd.getpwuid(os.getuid()).pw_name
        sock = root / 'tmux'
        dispatch = root / 'dispatch'
        dispatch.write_text('#!/usr/bin/env python3\nimport os, shlex, sys\n'
                            'argv=shlex.split(os.environ.get("SSH_ORIGINAL_COMMAND", ""))\n'
                            'if argv[:2] != ["exec", "tmux"]: sys.exit(1)\n'
                            f'os.execv({str(reference)!r}, [{str(reference)!r}, "-f", "/dev/null", "-S", {str(sock)!r}] + argv[2:])\n')
        dispatch.chmod(0o700)
        public = (root / 'client.pub').read_text()
        (root / 'authorized_keys').write_text(f'restrict,command="{dispatch}" {public}')
        (root / 'sshd.conf').write_text(
            f'Port {port}\nListenAddress 127.0.0.1\nHostKey {root}/host\nPidFile {root}/pid\n'
            f'AuthorizedKeysFile {root}/authorized_keys\nAllowUsers {user}\n'
            'PasswordAuthentication no\nKbdInteractiveAuthentication no\nUsePAM no\n'
            'StrictModes no\nLogLevel ERROR\nPermitTTY no\nAllowTcpForwarding no\nX11Forwarding no\n')
        host_key = (root / 'host.pub').read_text().split()
        (root / 'known_hosts').write_text(f'[127.0.0.1]:{port} {host_key[0]} {host_key[1]}\n')
        (root / 'ssh.conf').write_text(f'Host isolated-tmux\n HostName 127.0.0.1\n Port {port}\n User {user}\n'
            f' IdentityFile {root}/client\n IdentitiesOnly yes\n BatchMode yes\n StrictHostKeyChecking yes\n'
            f' UserKnownHostsFile {root}/known_hosts\n ConnectTimeout 2\n')
        (root / 'ssh').write_text(f'#!/bin/sh\nexec {shlex.quote(args.ssh)} -F {shlex.quote(str(root / "ssh.conf"))} "$@"\n')
        (root / 'ssh').chmod(0o700)
        with (root / 'sshd.log').open('wb') as log:
            daemon = subprocess.Popen([args.sshd, '-D', '-e', '-f', str(root / 'sshd.conf')], stderr=log)
            command = [str(reference), '-f', '/dev/null', '-S', str(sock)]
            try:
                for name in ('one', 'two'):
                    subprocess.run(command + ['new-session', '-d', '-s', name, '-x', '80', '-y', '24', '/bin/sh'], check=True)
                subprocess.run(command + ['split-window', '-d', '-t', 'one:0', '/bin/sh'], check=True)
                subprocess.run(command + ['link-window', '-s', 'one:0', '-t', 'two:1'], check=True)
                usage = subprocess.check_output(command + ['list-commands']).decode()
                paste_usage = next(line for line in usage.splitlines() if line.startswith('paste-buffer '))
                assert 'S' in paste_usage and 'r' in paste_usage and 'd' in paste_usage, paste_usage
                subprocess.run(command + ['set-buffer', '-b', 'user-kept', 'sentinel'], check=True)
                deadline = time.monotonic() + 5
                while True:
                    probe = subprocess.run([str(root / 'ssh'), '-T', 'isolated-tmux', 'exec tmux has-session -t one'], capture_output=True)
                    if probe.returncode == 0:
                        break
                    if time.monotonic() >= deadline:
                        raise RuntimeError(probe.stderr.decode(errors='replace') + (root / 'sshd.log').read_text())
                    time.sleep(.05)
                env = dict(os.environ, RUSTTY_TEST_SSH_HOST='isolated-tmux', PATH=str(root) + os.pathsep + os.environ['PATH'])
                get_clipboard = subprocess.run(command + ['show-options', '-s', 'get-clipboard'], capture_output=True).returncode == 0
                if get_clipboard:
                    env['RUSTTY_TEST_GET_CLIPBOARD'] = '1'
                else:
                    env.pop('RUSTTY_TEST_GET_CLIPBOARD', None)
                floating_usage = next((line for line in usage.splitlines() if line.startswith('new-pane ')), '')
                floating = bool(floating_usage)
                modal = 'O' in floating_usage.partition('[')[2].partition(']')[0]
                if floating:
                    env['RUSTTY_TEST_FLOATING'] = '1'
                else:
                    env.pop('RUSTTY_TEST_FLOATING', None)
                if modal:
                    env['RUSTTY_TEST_MODAL'] = '1'
                else:
                    env.pop('RUSTTY_TEST_MODAL', None)
                test = subprocess.run(['cargo', '+1.95.0', 'test', '--locked', '--offline', '-p', 'rustty', '--features', 'sessions',
                    'tmuxx::system::tests::stock_ssh_views_share_live_panes_and_survive_connection_restart',
                    '--', '--ignored', '--test-threads=1'], cwd=args.rustty, env=env, capture_output=True, text=True, timeout=120)
                report = {'reference': str(reference), 'version': subprocess.check_output([str(reference), '-V'], text=True).strip(),
                    'reference_sha256': hashlib.sha256(reference.read_bytes()).hexdigest(), 'exit_code': test.returncode,
                    'status': 'failed', 'rustty_sources': {name: hashlib.sha256((args.rustty / name).read_bytes()).hexdigest() for name in (
                        'crates/rustty/src/tmuxx.rs', 'crates/rustty/src/tmuxx/system.rs', 'crates/rustty/src/session.rs',
                        'crates/rustty-app/src/tmuxx_workspace.rs')},
                    'assertions': ['shared-pane-independent-selection', 'live-input-output', 'dynamic-pane-create-remove',
                        'reconnect-capture', 'same-session-duplicate-winlinks-and-active-index',
                        'mouse-and-protocol-reply-not-synchronized', 'ordinary-text-synchronized', 'nul-rejected',
                        'temporary-buffers-cleaned-on-success-and-missing-target', 'existing-user-buffer-preserved', 'deferred-server-text-forwarding',
                        'c-clipboard-buffer-replies-once-with-no-mirror-host-action' if get_clipboard else 'c-clipboard-query-silence-with-no-mirror-host-action']}
                if floating:
                    report['assertions'] += ['new-layouts-signed-floating-geometry']
                if modal:
                    report['assertions'] += ['modal-pane-discovery']
                if args.output:
                    args.output.parent.mkdir(parents=True, exist_ok=True)
                    args.output.with_suffix('.log').write_text(test.stdout + test.stderr)
                    args.output.write_text(json.dumps(report, indent=2) + '\n')
                # Preserve exact Cargo test names for the conformance gate.
                print(test.stdout, end='')
                if test.returncode:
                    print(test.stderr)
                test.check_returncode()
                buffers = subprocess.check_output(command + ['list-buffers', '-F', '#{buffer_name}'])
                assert b'__rustty_input_' not in buffers, buffers
                assert subprocess.check_output(command + ['show-buffer', '-b', 'user-kept']) == b'sentinel'
                report['status'] = 'passed'
                if args.output:
                    args.output.write_text(json.dumps(report, indent=2) + '\n')
                print(json.dumps({'reference': report['version'], 'status': report['status'], 'assertions': len(report['assertions'])}))
            finally:
                subprocess.run(command + ['kill-server'], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                daemon.terminate()
                try:
                    daemon.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    daemon.kill()
                    daemon.wait()


if __name__ == '__main__':
    run()
