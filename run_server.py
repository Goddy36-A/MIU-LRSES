#!/usr/bin/env python3
"""Start MIU-LRSES on your own computer. Standard library only.

Applies any pending database updates, starts the web server, opens your browser, and
(while this window is open) runs the reminder processor about once a minute so in-app
reminders are delivered. Press Ctrl+C in this window to stop.
"""
import argparse
import os
import signal
import socket
import subprocess
import sys
import threading
import time
import webbrowser
from pathlib import Path

ROOT = Path(__file__).resolve().parent
VPY = ROOT / "venv" / ("Scripts/python.exe" if os.name == "nt" else "bin/python")


def say(msg=""):
    print(msg, flush=True)


def port_free(host, port):
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        return s.connect_ex((host, port)) != 0


def wait_until_up(host, port, timeout=40):
    end = time.time() + timeout
    while time.time() < end:
        if not port_free(host, port):
            return True
        time.sleep(0.4)
    return False


def reminder_loop(stop, interval):
    """Runs `process_reminders` repeatedly while the server is up. Output goes to logs/reminders.log."""
    log_dir = ROOT / "logs"
    log_dir.mkdir(exist_ok=True)
    while not stop.wait(interval):
        with open(log_dir / "reminders.log", "ab") as log:
            log.write(f"===== {time.strftime('%Y-%m-%d %H:%M:%S')} =====\n".encode())
            subprocess.run([str(VPY), "manage.py", "process_reminders"], cwd=ROOT, stdout=log, stderr=subprocess.STDOUT)


def main():
    p = argparse.ArgumentParser(description="Start MIU-LRSES locally.")
    p.add_argument("--host", default="127.0.0.1")
    p.add_argument("--port", type=int, default=8000)
    p.add_argument("--no-browser", action="store_true")
    p.add_argument("--no-reminders", action="store_true", help="do not run the reminder processor in the background")
    p.add_argument("--reminder-interval", type=int, default=60, help="seconds between reminder runs (default 60)")
    p.add_argument("--reload", action="store_true", help="auto-restart when code changes (developers)")
    args = p.parse_args()

    if not VPY.exists():
        say("Setup has not been run yet. Run start.bat (Windows) or ./start.sh, or: python setup_local.py")
        return 1

    say("Checking the database ...")
    if subprocess.run([str(VPY), "manage.py", "migrate", "--noinput"], cwd=ROOT, stdout=subprocess.DEVNULL).returncode != 0:
        subprocess.run([str(VPY), "manage.py", "migrate", "--noinput"], cwd=ROOT)
        say("The database could not be prepared (see above).")
        return 1

    port = args.port
    for candidate in range(args.port, args.port + 11):
        if port_free(args.host, candidate):
            port = candidate
            break
    else:
        say(f"Ports {args.port}-{args.port + 10} are all busy. Close other programs or use --port.")
        return 1
    if port != args.port:
        say(f"Port {args.port} is busy, using {port} instead.")
    url = f"http://{args.host}:{port}/"

    cmd = [str(VPY), "manage.py", "runserver", f"{args.host}:{port}"] + ([] if args.reload else ["--noreload"])
    server = subprocess.Popen(cmd, cwd=ROOT)
    stop = threading.Event()

    say("\n" + "=" * 60)
    say(f" MIU-LRSES is starting at {url}")
    say(" Keep this window open while you use the system.")
    say(" To stop: press Ctrl+C here, or close this window.")
    if args.no_reminders:
        say(" Reminders: NOT being processed (--no-reminders).")
    else:
        say(f" Reminders: processed every {args.reminder_interval}s while this window is open (in-app only).")
    say("=" * 60 + "\n")

    if not args.no_reminders:
        threading.Thread(target=reminder_loop, args=(stop, args.reminder_interval), daemon=True).start()
    if not args.no_browser:
        threading.Thread(target=lambda: wait_until_up(args.host, port) and webbrowser.open(url), daemon=True).start()

    def _terminate(*_):
        raise KeyboardInterrupt

    signal.signal(signal.SIGTERM, _terminate)  # a normal "stop" request behaves like Ctrl+C
    try:
        code = server.wait()
    except KeyboardInterrupt:
        say("\nStopping ...")
        code = 0
    finally:
        stop.set()
        if server.poll() is None:
            server.terminate()
            try:
                server.wait(timeout=10)
            except subprocess.TimeoutExpired:
                server.kill()
    say("MIU-LRSES stopped.")
    return code


if __name__ == "__main__":
    sys.exit(main())
