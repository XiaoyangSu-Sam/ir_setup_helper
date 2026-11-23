"""Run the local server and stop the instance associated with this library."""
from __future__ import annotations

import argparse
import ctypes
import json
import os
import socket
import subprocess
import sys
import time
from urllib.request import urlopen
import webbrowser

from endurance.paths import ROOT, data_dir

FROZEN = getattr(sys, "frozen", False)
PORT = 19392 if FROZEN else 19391
URL = f"http://127.0.0.1:{PORT}"


def lock_launcher(handle):
    handle.seek(0)
    if os.name == "nt":
        import msvcrt
        msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
    else:
        import fcntl
        fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)


def stop_and_wait(handle, request):
    for _ in range(100):
        try:
            lock_launcher(handle)
        except OSError:
            time.sleep(.15)
            continue
        request.unlink(missing_ok=True)
        return 0
    return 1


def ready():
    try:
        with urlopen(URL + "/_stcore/health", timeout=.5) as response:
            return response.status == 200
    except OSError:
        return False


def open_browser():
    if FROZEN:
        os.startfile(URL)
    else:
        webbrowser.open(URL)


def fail(log, hidden, reason):
    if FROZEN and not hidden:
        ctypes.windll.user32.MessageBoxW(
            None, f"{reason}\n启动日志：{log}", "耐力调教助手", 0x10,
        )
    return 1


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--stop", action="store_true")
    parser.add_argument("--stop-and-wait", action="store_true", help=argparse.SUPPRESS)
    parser.add_argument("--serve", action="store_true", help=argparse.SUPPRESS)
    parser.add_argument("--no-browser", action="store_true")
    args = parser.parse_args()
    library = data_dir()
    runtime = library / ("runtime-installed" if FROZEN else "runtime")
    runtime.mkdir(parents=True, exist_ok=True)
    log_path = runtime / "server.log"
    flags = ["run", str(ROOT / "app.py"), "--server.address=127.0.0.1",
             f"--server.port={PORT}", "--server.headless=true"]
    if args.serve and FROZEN:
        # The windowed child starts with no console handles.
        with log_path.open("a", encoding="utf-8", buffering=1) as log:
            sys.stdout = sys.stderr = log
            from streamlit.web.cli import main as streamlit_main

            streamlit_main(flags + ["--server.fileWatcherType=none"], prog_name="streamlit")
        return 0

    request = runtime / "stop.request"
    if args.stop or args.stop_and_wait:
        request.write_text("stop", encoding="ascii")
    if args.stop:
        return 0

    with (runtime / "launcher.lock").open("a+b") as handle:
        if handle.tell() == 0:
            handle.write(b"1")
            handle.flush()
        if args.stop_and_wait:
            return stop_and_wait(handle, request)
        try:
            lock_launcher(handle)
        except OSError:
            if not args.no_browser:
                for _ in range(100):
                    if ready():
                        open_browser()
                        return 0
                    time.sleep(.3)
                return fail(log_path, args.no_browser, "本机服务尚未启动。")
            return 0
        request.unlink(missing_ok=True)

        with socket.socket() as probe:
            probe.settimeout(.5)
            if probe.connect_ex(("127.0.0.1", PORT)) == 0:
                return fail(log_path, args.no_browser, f"本机端口 {PORT} 已被占用。")

        exe = ROOT / ".venv" / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
        command = [sys.executable, "--serve"] if FROZEN else [str(exe), "-m", "streamlit", *flags]
        env = {**os.environ, "PYTHONUTF8": "1", "ENDURANCE_DATA_DIR": str(library)}
        with log_path.open("a", encoding="utf-8") as log:
            child = subprocess.Popen(command, cwd=ROOT, env=env, stdout=log, stderr=log,
                                     creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0)
            session = runtime / "session.json"
            try:
                session.write_text(json.dumps({"pid": child.pid, "url": URL, "root": str(ROOT)}), encoding="utf-8")
                for _ in range(100):
                    if request.exists():
                        return 0
                    if child.poll() is not None:
                        break
                    if ready():
                        if not args.no_browser:
                            open_browser()
                        while child.poll() is None and not request.exists():
                            time.sleep(.3)
                        return int(not request.exists())
                    time.sleep(.3)
                return fail(log_path, args.no_browser, "无法启动本机服务。")
            finally:
                if child.poll() is None:
                    child.terminate()
                    try:
                        child.wait(timeout=10)
                    except subprocess.TimeoutExpired:
                        child.kill()
                        child.wait(timeout=3)
                request.unlink(missing_ok=True)
                session.unlink(missing_ok=True)


if __name__ == "__main__":
    raise SystemExit(main())
