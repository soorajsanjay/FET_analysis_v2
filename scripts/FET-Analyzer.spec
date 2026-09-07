# -*- mode: python ; coding: utf-8 -*-
from pathlib import Path
from PyInstaller.utils.hooks import collect_all

project = Path(SPECPATH).resolve().parent
version_file = str(project / "scripts" / "windows_version_info.txt")
static_data = [
    (str(project / "fet_analyzer" / "dashboard" / "static"), "fet_analyzer/dashboard/static"),
    (str(project / "config"), "config"),
]
shared_binaries = []
shared_hidden = ["webview.platforms.edgechromium", "webview.platforms.winforms"]
for package in ("matplotlib", "scipy", "openpyxl", "webview"):
    package_data, package_binaries, package_hidden = collect_all(package)
    static_data += package_data
    shared_binaries += package_binaries
    shared_hidden += package_hidden
common = dict(
    pathex=[str(project)],
    datas=static_data,
    binaries=shared_binaries,
    hiddenimports=shared_hidden,
    hookspath=[], hooksconfig={}, runtime_hooks=[], excludes=[], noarchive=False,
)

app = Analysis([str(project / "scripts" / "frozen_dispatch.py")], **common)
app_pyz = PYZ(app.pure)

native = EXE(app_pyz, app.scripts, [], exclude_binaries=True, name="FET-Analyzer-v2",
             debug=False, bootloader_ignore_signals=False, strip=False, upx=True,
             console=False, disable_windowed_traceback=False, version=version_file)
browser = EXE(app_pyz, app.scripts, [], exclude_binaries=True, name="FET-Analyzer-Browser",
              debug=False, bootloader_ignore_signals=False, strip=False, upx=True,
              console=True, disable_windowed_traceback=False, version=version_file)
worker = EXE(app_pyz, app.scripts, [], exclude_binaries=True, name="FET-Analyzer-Worker",
             debug=False, bootloader_ignore_signals=False, strip=False, upx=True,
             console=True, disable_windowed_traceback=False, version=version_file)

COLLECT(native, browser, worker,
        app.binaries, app.datas,
        strip=False, upx=True, name="FET-Analyzer-v2")
