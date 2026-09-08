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
    if sys.version_info[:2] < (3, 10):
        parser.error("Install Python 3.10 or newer, or use the portable Windows package.")
    version_tag = f"py{sys.version_info.major}{sys.version_info.minor}"
    environment = ROOT / f".venv-{version_tag}"
    python = environment / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
    if not python.is_file():
        print(f"Bootstrap interpreter: {sys.executable} (Python {sys.version.split()[0]})", flush=True)
        print(f"Creating the local Python environment: {environment}", flush=True)
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
        subprocess.run([str(python), "-c",
                        "import fet_analyzer,sys; print('Ready interpreter:',sys.executable); print('Python:',sys.version.split()[0]); print('FET Analyzer:',fet_analyzer.__version__); print('Package:',fet_analyzer.__file__)"], check=True)
        return 0
    module = {"browser": "fet_analyzer.dashboard", "native": "fet_analyzer.native",
              "batch": "fet_analyzer", "doctor": "fet_analyzer"}[args.mode]
    command = [str(python), "-m", module]
    if args.mode == "doctor":
        command.append("--doctor")
    command.extend(forwarded)
    subprocess.run([str(python), "-c",
                    "import fet_analyzer,sys; print('Selected interpreter:',sys.executable); print('Python:',sys.version.split()[0]); print('Environment:',sys.prefix); print('FET Analyzer:',fet_analyzer.__version__); print('Package:',fet_analyzer.__file__)"], check=True)
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
