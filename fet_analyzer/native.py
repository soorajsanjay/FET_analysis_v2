"""Native Windows host for the shared FET Analyzer dashboard."""
from __future__ import annotations

import argparse
import multiprocessing
import threading
from pathlib import Path

from fet_analyzer.dashboard.server import create_server
from fet_analyzer.runtime import append_runtime_log


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="FET Analyzer native desktop GUI")
    parser.add_argument(
        "--root", default=".",
        help="Initial measurement folder (recommended: change into it and use --root .)",
    )
    parser.add_argument("--debug", action="store_true", help="Enable WebView debugging tools")
    return parser


def main(argv: list[str] | None = None) -> int:
    multiprocessing.freeze_support()
    args = build_parser().parse_args(argv)
    try:
        import webview
    except Exception as exc:  # pragma: no cover - depends on optional desktop runtime
        return _startup_failure(exc)

    try:
        server, url = create_server(Path(args.root), port=0)
    except Exception as exc:  # pragma: no cover - platform/startup failure
        return _startup_failure(exc)
    server_thread = threading.Thread(
        target=server.serve_forever, name="fet-dashboard-server", daemon=True
    )
    server_thread.start()
    try:
        try:
            window = webview.create_window(
                "FET Analyzer",
                url,
                width=1440,
                height=940,
                min_size=(1024, 720),
                confirm_close=True,
            )
            state = getattr(server, "dashboard_state", None)
            if state is not None:
                dialog_kind = getattr(
                    getattr(webview, "FileDialog", None), "FOLDER",
                    getattr(webview, "FOLDER_DIALOG", 20),
                )
                state.folder_picker = lambda initial: window.create_file_dialog(
                    dialog_kind, directory=str(initial)
                )
            webview.start(debug=args.debug)
        except Exception as exc:  # pragma: no cover - platform backend failure
            return _startup_failure(exc)
    finally:
        state = getattr(server, "dashboard_state", None)
        process = getattr(state, "process", None) if state is not None else None
        if process is not None and process.poll() is None:
            state.stop_run()
            try:
                process.wait(timeout=7)
            except Exception as exc:
                append_runtime_log(
                    "native-shutdown",
                    f"Worker did not stop cleanly: {type(exc).__name__}: {exc}",
                )
        server.shutdown()
        server.server_close()
        server_thread.join(timeout=5)
    return 0


def _startup_failure(exc: BaseException) -> int:
    """Record and visibly explain native-host failures in windowed builds."""
    log_path = append_runtime_log("native-startup", f"{type(exc).__name__}: {exc}")
    message = (
        "FET Analyzer could not open its native window.\n\n"
        f"{type(exc).__name__}: {exc}\n\n"
        f"Diagnostic log: {log_path}\n\n"
        "Run FET-Analyzer-Browser.exe from the same folder as a fallback. "
        "If the problem mentions WebView2, install or repair Microsoft Edge WebView2 Runtime."
    )
    try:
        if __import__("os").name == "nt":
            import ctypes
            ctypes.windll.user32.MessageBoxW(None, message, "FET Analyzer startup error", 0x10)
        else:
            print(message)
    except Exception:
        print(message)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
