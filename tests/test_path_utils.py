from __future__ import annotations

import io
import re
import sys
import tempfile
import unittest
from contextlib import redirect_stderr
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from fet_analyzer.cli import _warn_if_output_path_long
from fet_analyzer.dashboard.server import DashboardState
from fet_analyzer.path_utils import (
    OUTPUT_PATH_WARNING_THRESHOLD,
    WINDOWS_LONG_PATH_THRESHOLD,
    output_path_warning,
    prepare_write_path,
    safe_copy2,
    safe_path,
    safe_replace,
    safe_rmtree,
    unique_directory,
)
from fet_analyzer.temp_workspace import RunWorkspace


class PathUtilityTests(unittest.TestCase):
    def test_non_windows_path_is_unchanged(self):
        logical = Path("relative") / ("x" * 260) / "result.json"
        with patch("fet_analyzer.path_utils.sys.platform", "linux"):
            self.assertEqual(safe_path(logical), logical)

    @unittest.skipUnless(sys.platform == "win32", "Windows path syntax")
    def test_windows_drive_unc_and_existing_prefixes(self):
        short = Path(r"C:\data\result.json")
        self.assertEqual(safe_path(short), short)

        drive = Path("C:/") / ("x" * 250) / "result.json"
        self.assertTrue(str(safe_path(drive)).startswith("\\\\?\\C:\\"))

        unc = "\\\\server\\share\\" + ("x" * 250) + "\\result.json"
        self.assertTrue(str(safe_path(unc)).startswith("\\\\?\\UNC\\server\\share\\"))

        extended = Path(r"\\?\C:\already\extended\result.json")
        self.assertEqual(safe_path(extended), extended)

    def test_warning_threshold_is_non_blocking_and_shared_with_cli(self):
        short = Path("x" * max(1, OUTPUT_PATH_WARNING_THRESHOLD // 4))
        self.assertIsNone(output_path_warning(short, threshold=10_000))

        long_output = Path("C:/") / ("o" * (OUTPUT_PATH_WARNING_THRESHOLD + 10))
        warning = output_path_warning(long_output)
        self.assertIsNotNone(warning)
        self.assertIn("consider choosing a shorter output location", warning)

        stderr = io.StringIO()
        with redirect_stderr(stderr):
            self.assertTrue(_warn_if_output_path_long(long_output))
        self.assertIn("WARNING:", stderr.getvalue())

    def test_short_directory_creation_retries_a_collision(self):
        with tempfile.TemporaryDirectory() as folder:
            parent = Path(folder)
            (parent / "device_deadbeef").mkdir()
            identifiers = [
                SimpleNamespace(hex="deadbeef" + "0" * 24),
                SimpleNamespace(hex="cafebabe" + "1" * 24),
            ]
            with patch("fet_analyzer.path_utils.uuid4", side_effect=identifiers):
                path, full_id = unique_directory(parent, "device_")
            self.assertEqual(path.name, "device_cafebabe")
            self.assertEqual(full_id, "cafebabe" + "1" * 24)

    @unittest.skipUnless(sys.platform == "win32", "Windows long-path integration")
    def test_actual_long_writes_copy_replace_plot_and_workbook(self):
        root = Path(tempfile.mkdtemp(prefix="fet-long-path-"))
        try:
            nested = root
            index = 0
            while len(str(nested / "transfer_vth_extraction_bias-1.0.png")) <= 280:
                nested /= f"segment_{index}_{'x' * 35}"
                index += 1

            text_path = nested / "payload.json"
            prepared = prepare_write_path(text_path)
            self.assertGreater(len(str(text_path.resolve())), WINDOWS_LONG_PATH_THRESHOLD)
            self.assertTrue(str(prepared).startswith("\\\\?\\"))
            prepared.write_text('{"status":"ok"}', encoding="utf-8")
            self.assertEqual(safe_path(text_path).read_text(encoding="utf-8"), '{"status":"ok"}')

            copied = nested / "payload-copy.json"
            safe_copy2(text_path, copied)
            replaced = nested / "payload-final.json"
            safe_replace(copied, replaced)
            self.assertTrue(safe_path(replaced).is_file())

            try:
                import matplotlib
                matplotlib.use("Agg")
                import matplotlib.pyplot as plt
            except ImportError:
                plt = None
            if plt is not None:
                plot_path = nested / "transfer_vth_extraction_bias-1.0.png"
                figure, axis = plt.subplots()
                axis.plot([0, 1], [0, 1])
                figure.savefig(prepare_write_path(plot_path))
                plt.close(figure)
                self.assertTrue(safe_path(plot_path).is_file())

            try:
                import openpyxl
            except ImportError:
                openpyxl = None
            if openpyxl is not None:
                workbook_path = nested / "device-analysis.xlsx"
                workbook = openpyxl.Workbook()
                workbook.active["A1"] = "unchanged content"
                workbook.save(prepare_write_path(workbook_path))
                workbook.close()
                loaded = openpyxl.load_workbook(safe_path(workbook_path), read_only=True)
                try:
                    self.assertEqual(loaded.active["A1"].value, "unchanged content")
                finally:
                    loaded.close()
        finally:
            safe_rmtree(root, ignore_errors=True)


class WorkspaceAndDiagnosticsTests(unittest.TestCase):
    def test_workspace_uses_short_names_and_retains_full_ids(self):
        with tempfile.TemporaryDirectory() as folder:
            output = Path(folder)
            workspace = RunWorkspace(output)
            try:
                device = workspace.temporary_directory("device_")
                self.assertEqual(workspace.root.name, ".fw")
                self.assertRegex(workspace.path.name, r"^run_\d+_[0-9a-f]{8}$")
                self.assertRegex(device.name, r"^device_[0-9a-f]{8}$")
                self.assertRegex(workspace.run_id, r"^[0-9a-f]{32}$")
                self.assertRegex(workspace.temporary_ids[device], r"^[0-9a-f]{32}$")
            finally:
                workspace.cleanup()
            self.assertFalse((output / ".fw").exists())

    def test_dashboard_diagnostics_and_preflight_report_long_output(self):
        with tempfile.TemporaryDirectory() as folder:
            state = DashboardState(Path(folder))
            state.output_dir = Path("C:/") / ("o" * 210)
            diagnostics = state.diagnostic_payload()
            output_check = next(
                item for item in diagnostics["checks"] if item["name"] == "output"
            )
            self.assertIsNotNone(output_check["warning"])
            self.assertGreater(output_check["path_length"], 200)

            with patch(
                "fet_analyzer.file_discovery.discover_files", return_value=([], []),
            ), patch.object(state, "ion_preflight", return_value={"rows": []}):
                preflight = state.preflight_payload(overwrite=True)
            warning_codes = {
                item.get("code") for item in preflight["issues"]
                if item.get("level") == "warning"
            }
            self.assertIn("output_path_long", warning_codes)


class WriteBoundaryAuditTests(unittest.TestCase):
    def test_mutating_file_calls_use_path_boundary(self):
        package = Path(__file__).resolve().parents[1] / "fet_analyzer"
        violations: list[str] = []
        patterns = (
            re.compile(r"\.savefig\("),
            re.compile(r"\b(?:wb|workbook)\.save\("),
            re.compile(r"\.write_(?:text|bytes)\("),
        )
        for path in package.rglob("*.py"):
            if path.name == "path_utils.py":
                continue
            for line_number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
                if any(pattern.search(line) for pattern in patterns):
                    if "prepare_write_path" not in line:
                        violations.append(f"{path.relative_to(package)}:{line_number}: {line.strip()}")
                if ".mkdir(" in line or "shutil." in line:
                    violations.append(f"{path.relative_to(package)}:{line_number}: {line.strip()}")
                if re.search(r"\bopen\([^\n]+,\s*[\"'](?:w|a|x|wb|ab|xb)", line):
                    if "prepare_write_path" not in line:
                        violations.append(f"{path.relative_to(package)}:{line_number}: {line.strip()}")
        self.assertEqual(violations, [], "Unprotected file mutations:\n" + "\n".join(violations))
