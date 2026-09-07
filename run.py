"""Source launcher: bootstrap a local environment, then forward to the chosen UI/CLI."""
from __future__ import annotations
import argparse
import hashlib
import os
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parent


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--mode", choices=["browser", "native", "batch", "doctor", "setup"], default="browser")
    parser.add_argument("--reinstall", action="store_true", help="Refresh the local environment after dependency changes")
    args, forwarded = parser.parse_known_args()
    if not (3, 11) <= sys.version_info[:2] < (3, 14):
        parser.error("Install Python 3.11, 3.12, or 3.13, or use the portable Windows package.")
    environment = ROOT / ".venv"
    python = environment / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
    if not python.is_file():
        print("Creating the local Python environment...", flush=True)
        subprocess.run([sys.executable, "-m", "venv", str(environment)], check=True)
    native = args.mode == "native"
    marker = environment / (".fet-ready-native" if native else ".fet-ready")
    fingerprint = hashlib.sha256((ROOT / "pyproject.toml").read_bytes() + (ROOT / "requirements.lock").read_bytes()).hexdigest()
    if args.reinstall or not marker.is_file() or marker.read_text().strip() != fingerprint:
        print("Installing dependencies (first launch needs internet or an approved package mirror)...", flush=True)
        subprocess.run([str(python), "-m", "pip", "install", "-c", str(ROOT / "requirements.lock"),
                        "-e", str(ROOT) + ("[native]" if native else "")], check=True)
        marker.write_text(fingerprint, encoding="ascii")
    if args.mode == "setup":
        print(f"Ready: {python}")
        return 0
    module = {"browser": "fet_analyzer.dashboard", "native": "fet_analyzer.native",
              "batch": "fet_analyzer", "doctor": "fet_analyzer"}[args.mode]
    command = [str(python), "-m", module]
    if args.mode == "doctor":
        command.append("--doctor")
    command.extend(forwarded)
    print("Starting FET Analyzer. Keep this console open while using the dashboard.", flush=True)
    return subprocess.call(command, cwd=ROOT)


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except subprocess.CalledProcessError as exc:
        print(f"Setup failed (exit {exc.returncode}). Check Python, network/proxy settings and write access.", file=sys.stderr)
        raise SystemExit(exc.returncode)
    except KeyboardInterrupt:
        raise SystemExit(130)
    except OSError as exc:
        print(f"Cannot launch FET Analyzer: {exc}", file=sys.stderr)
        raise SystemExit(1)
