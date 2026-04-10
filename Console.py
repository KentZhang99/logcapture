#!/usr/bin/env python3
"""
LogCapture Console - Serial port and SSH log capture tool
Usage: python Console.py
"""

import os
import sys
import time
import queue
import signal
import threading
import argparse
import datetime

try:
    import serial
    import serial.tools.list_ports
    SERIAL_AVAILABLE = True
except ImportError:
    SERIAL_AVAILABLE = False

try:
    import paramiko
    SSH_AVAILABLE = True
except ImportError:
    SSH_AVAILABLE = False


# ─────────────────────────────────────────────
#  Helpers
# ─────────────────────────────────────────────

def timestamp():
    return datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def log_filename(prefix):
    now = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    return f"{prefix}_{now}.log"


def print_banner():
    print("=" * 60)
    print("  LogCapture Console  –  Serial / SSH log capture")
    print("=" * 60)


# ─────────────────────────────────────────────
#  Serial capture
# ─────────────────────────────────────────────

class SerialCapture:
    """Captures log lines from a serial/COM port."""

    def __init__(self, port, baudrate=115200, output_file=None):
        self.port = port
        self.baudrate = baudrate
        self.output_file = output_file
        self._stop_event = threading.Event()
        self._thread = None
        self._ser = None

    def start(self):
        if not SERIAL_AVAILABLE:
            raise RuntimeError(
                "pyserial is not installed. Run: pip install pyserial"
            )
        self._ser = serial.Serial(
            self.port,
            self.baudrate,
            timeout=1,
        )
        self._stop_event.clear()
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()
        print(f"[{timestamp()}] Serial capture started on {self.port} @ {self.baudrate} baud")
        if self.output_file:
            print(f"[{timestamp()}] Saving to {self.output_file}")

    def _run(self):
        def _capture(fh):
            while not self._stop_event.is_set():
                try:
                    line = self._ser.readline()
                    if line:
                        decoded = line.decode("utf-8", errors="replace").rstrip()
                        entry = f"[{timestamp()}] {decoded}"
                        print(entry)
                        if fh:
                            fh.write(entry + "\n")
                            fh.flush()
                except serial.SerialException as exc:
                    print(f"[{timestamp()}] Serial error: {exc}")
                    break

        if self.output_file:
            with open(self.output_file, "a", encoding="utf-8") as fh:
                _capture(fh)
        else:
            _capture(None)

    def stop(self):
        self._stop_event.set()
        if self._thread:
            self._thread.join(timeout=3)
        if self._ser and self._ser.is_open:
            self._ser.close()
        print(f"[{timestamp()}] Serial capture stopped.")


# ─────────────────────────────────────────────
#  SSH capture
# ─────────────────────────────────────────────

class SSHCapture:
    """Captures log output from a remote host via SSH."""

    def __init__(self, host, port=22, username=None, password=None,
                 key_path=None, command=None, output_file=None,
                 no_host_key_check=False):
        self.host = host
        self.port = port
        self.username = username
        self.password = password
        self.key_path = key_path
        self.command = command or "tail -f /var/log/syslog"
        self.output_file = output_file
        self.no_host_key_check = no_host_key_check
        self._stop_event = threading.Event()
        self._thread = None
        self._client = None

    def start(self):
        if not SSH_AVAILABLE:
            raise RuntimeError(
                "paramiko is not installed. Run: pip install paramiko"
            )
        self._client = paramiko.SSHClient()
        # Load system and user known_hosts so legitimate hosts are accepted
        self._client.load_system_host_keys()
        try:
            self._client.load_host_keys(
                os.path.expanduser("~/.ssh/known_hosts")
            )
        except FileNotFoundError:
            pass

        if self.no_host_key_check:
            # Insecure: accept any host key without verification
            print(
                f"[{timestamp()}] WARNING: host key verification is disabled. "
                "This is vulnerable to man-in-the-middle attacks."
            )
            self._client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
        else:
            # Reject connections to unknown hosts; user must add them to known_hosts
            self._client.set_missing_host_key_policy(paramiko.RejectPolicy())

        connect_kwargs = dict(
            hostname=self.host,
            port=self.port,
            username=self.username,
            timeout=10,
        )
        if self.key_path:
            connect_kwargs["key_filename"] = self.key_path
        else:
            connect_kwargs["password"] = self.password

        self._client.connect(**connect_kwargs)
        self._stop_event.clear()
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()
        print(f"[{timestamp()}] SSH capture started: {self.username}@{self.host}:{self.port}")
        print(f"[{timestamp()}] Remote command: {self.command}")
        if self.output_file:
            print(f"[{timestamp()}] Saving to {self.output_file}")

    def _run(self):
        import socket

        def _capture(fh):
            transport = self._client.get_transport()
            channel = transport.open_session()
            channel.get_pty()
            channel.exec_command(self.command)
            channel.settimeout(1.0)
            while not self._stop_event.is_set():
                try:
                    data = channel.recv(4096)
                    if not data:
                        break
                    for line in data.decode("utf-8", errors="replace").splitlines():
                        entry = f"[{timestamp()}] {line}"
                        print(entry)
                        if fh:
                            fh.write(entry + "\n")
                            fh.flush()
                except socket.timeout:
                    continue
                except OSError as exc:
                    print(f"[{timestamp()}] SSH read error: {exc}")
                    break

        try:
            if self.output_file:
                with open(self.output_file, "a", encoding="utf-8") as fh:
                    _capture(fh)
            else:
                _capture(None)
        finally:
            try:
                self._client.close()
            except OSError as exc:
                print(f"[{timestamp()}] SSH close error: {exc}")

    def stop(self):
        self._stop_event.set()
        if self._thread:
            self._thread.join(timeout=3)
        print(f"[{timestamp()}] SSH capture stopped.")


# ─────────────────────────────────────────────
#  Interactive menu
# ─────────────────────────────────────────────

def prompt(msg, default=None):
    """Prompt the user for input with an optional default."""
    if default is not None:
        msg = f"{msg} [{default}]: "
    else:
        msg = f"{msg}: "
    value = input(msg).strip()
    return value if value else default


def list_serial_ports():
    if not SERIAL_AVAILABLE:
        print("pyserial not installed – cannot list ports.")
        return []
    ports = list(serial.tools.list_ports.comports())
    if not ports:
        print("No serial ports detected.")
    else:
        print("Available serial ports:")
        for i, p in enumerate(ports):
            print(f"  {i + 1}. {p.device}  –  {p.description}")
    return ports


def run_serial_interactive():
    ports = list_serial_ports()
    if ports:
        choice = prompt("Enter port name or number from list above")
        try:
            idx = int(choice) - 1
            port = ports[idx].device
        except (ValueError, IndexError):
            port = choice
    else:
        port = prompt("Enter serial port (e.g. COM3 or /dev/ttyUSB0)")

    baudrate = int(prompt("Baud rate", default="115200"))
    save = prompt("Save to file? (y/n)", default="y").lower() == "y"
    output_file = log_filename("serial") if save else None

    capture = SerialCapture(port, baudrate, output_file)
    try:
        capture.start()
        print("Press Ctrl+C to stop capture.")
        while True:
            time.sleep(0.5)
    except KeyboardInterrupt:
        pass
    finally:
        capture.stop()


def run_ssh_interactive():
    host = prompt("SSH host")
    port = int(prompt("SSH port", default="22"))
    username = prompt("Username")
    use_key = prompt("Use SSH key file? (y/n)", default="n").lower() == "y"
    key_path = None
    password = None
    if use_key:
        key_path = prompt("Path to private key file", default=os.path.expanduser("~/.ssh/id_rsa"))
    else:
        import getpass
        password = getpass.getpass(f"Password for {username}@{host}: ")

    command = prompt("Remote command", default="tail -f /var/log/syslog")
    no_host_key_check = (
        prompt("Disable host key verification? (y/n)", default="n").lower() == "y"
    )
    save = prompt("Save to file? (y/n)", default="y").lower() == "y"
    output_file = log_filename("ssh") if save else None

    capture = SSHCapture(
        host=host,
        port=port,
        username=username,
        password=password,
        key_path=key_path,
        command=command,
        output_file=output_file,
        no_host_key_check=no_host_key_check,
    )
    try:
        capture.start()
        print("Press Ctrl+C to stop capture.")
        while True:
            time.sleep(0.5)
    except KeyboardInterrupt:
        pass
    finally:
        capture.stop()


def interactive_menu():
    print_banner()
    print()
    print("Select capture mode:")
    print("  1. Serial port")
    print("  2. SSH")
    print("  q. Quit")
    print()

    while True:
        choice = input("Choice: ").strip().lower()
        if choice == "1":
            run_serial_interactive()
            break
        elif choice == "2":
            run_ssh_interactive()
            break
        elif choice in ("q", "quit", "exit"):
            print("Goodbye.")
            sys.exit(0)
        else:
            print("Invalid choice. Enter 1, 2, or q.")


# ─────────────────────────────────────────────
#  CLI argument parser
# ─────────────────────────────────────────────

def build_parser():
    parser = argparse.ArgumentParser(
        prog="Console.py",
        description="LogCapture – capture logs from a serial port or SSH session",
    )
    subparsers = parser.add_subparsers(dest="mode")

    # serial sub-command
    sp = subparsers.add_parser("serial", help="Capture from a serial port")
    sp.add_argument("port", help="Serial port (e.g. COM3 or /dev/ttyUSB0)")
    sp.add_argument("-b", "--baudrate", type=int, default=115200,
                    help="Baud rate (default: 115200)")
    sp.add_argument("-o", "--output", metavar="FILE",
                    help="Save output to FILE (default: auto-generated filename)")

    # ssh sub-command
    ssh = subparsers.add_parser("ssh", help="Capture from a remote host via SSH")
    ssh.add_argument("host", help="Remote hostname or IP address")
    ssh.add_argument("-p", "--port", type=int, default=22,
                     help="SSH port (default: 22)")
    ssh.add_argument("-u", "--user", metavar="USERNAME", required=True,
                     help="SSH username")
    ssh.add_argument("--password", metavar="PASSWORD",
                     help="SSH password. WARNING: passing credentials on the "
                          "command line is insecure (visible in process listings "
                          "and shell history). Omit to be prompted securely, or "
                          "prefer key-based auth via --identity.")
    ssh.add_argument("-i", "--identity", metavar="KEY_FILE",
                     help="Path to SSH private key file")
    ssh.add_argument("--no-host-key-check", action="store_true",
                     help="Disable SSH host key verification. "
                          "INSECURE: vulnerable to man-in-the-middle attacks. "
                          "Use only in trusted network environments.")
    ssh.add_argument("-c", "--command", default="tail -f /var/log/syslog",
                     help="Remote command to run (default: tail -f /var/log/syslog)")
    ssh.add_argument("-o", "--output", metavar="FILE",
                     help="Save output to FILE (default: auto-generated filename)")

    return parser


def main():
    parser = build_parser()
    args = parser.parse_args()

    if args.mode is None:
        # No sub-command – launch interactive menu
        interactive_menu()
        return

    # ── Serial mode ──────────────────────────
    if args.mode == "serial":
        output_file = args.output or log_filename("serial")
        capture = SerialCapture(args.port, args.baudrate, output_file)
        try:
            capture.start()
            print("Press Ctrl+C to stop capture.")
            while True:
                time.sleep(0.5)
        except KeyboardInterrupt:
            pass
        finally:
            capture.stop()

    # ── SSH mode ─────────────────────────────
    elif args.mode == "ssh":
        password = args.password
        if password:
            import warnings
            warnings.warn(
                "Passing passwords on the command line is insecure. "
                "Consider using SSH key-based authentication (--identity) "
                "or omit --password to be prompted securely.",
                stacklevel=2,
            )
        if not password and not args.identity:
            import getpass
            password = getpass.getpass(f"Password for {args.user}@{args.host}: ")

        output_file = args.output or log_filename("ssh")
        capture = SSHCapture(
            host=args.host,
            port=args.port,
            username=args.user,
            password=password,
            key_path=args.identity,
            command=args.command,
            output_file=output_file,
            no_host_key_check=args.no_host_key_check,
        )
        try:
            capture.start()
            print("Press Ctrl+C to stop capture.")
            while True:
                time.sleep(0.5)
        except KeyboardInterrupt:
            pass
        finally:
            capture.stop()


if __name__ == "__main__":
    main()
