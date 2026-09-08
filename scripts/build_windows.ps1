param([string]$OutputRoot = "dist", [string]$PythonCommand = "python")
$ErrorActionPreference = "Stop"
$ProjectRoot = Split-Path -Parent $PSScriptRoot
$Venv = Join-Path $ProjectRoot ".venv-build"
$Python = Join-Path $Venv "Scripts\python.exe"
if (-not (Test-Path -LiteralPath $Python)) {
    & $PythonCommand -m venv $Venv
    if ($LASTEXITCODE -ne 0) { throw "Python environment creation failed" }
}
& $Python -c "import sys; assert sys.version_info[:2] == (3,13), 'Portable release builds require Python 3.13'"
if ($LASTEXITCODE -ne 0) { throw "Unsupported build Python" }
& $Python -m pip install -c "$ProjectRoot\requirements.lock" "$ProjectRoot[build,native]"
if ($LASTEXITCODE -ne 0) { throw "Build dependency installation failed" }
$Dist = if ([IO.Path]::IsPathRooted($OutputRoot)) { $OutputRoot } else { Join-Path $ProjectRoot $OutputRoot }
& $Python -m PyInstaller --noconfirm --clean "$ProjectRoot\scripts\FET-Analyzer.spec" --distpath $Dist --workpath "$ProjectRoot\build"
if ($LASTEXITCODE -ne 0) { throw "PyInstaller failed" }
$Package = Join-Path $Dist "FET-Analyzer-v2"
foreach ($Name in @("FET-Analyzer-v2.exe", "FET-Analyzer-Browser.exe", "FET-Analyzer-Worker.exe")) {
    if (-not (Test-Path -LiteralPath (Join-Path $Package $Name))) { throw "Missing built executable: $Name" }
}
foreach ($Doc in @("README.md", "DEPLOYMENT.md", "NOTICE.md", "DASHBOARD.md", "METHODS.md", "V2_ARCHITECTURE.md", "REVIEW.md")) {
    Copy-Item -LiteralPath (Join-Path $ProjectRoot $Doc) -Destination $Package
}
Copy-Item -LiteralPath "$ProjectRoot\config" -Destination $Package -Recurse -Force
Copy-Item -LiteralPath "$ProjectRoot\examples" -Destination $Package -Recurse -Force
& $Python "$ProjectRoot\scripts\collect_licenses.py" --output "$Package\THIRD_PARTY_NOTICES.txt"
if ($LASTEXITCODE -ne 0) { throw "Third-party notice collection failed" }
& $Python -m pip freeze | Set-Content -LiteralPath "$Package\BUILD_DEPENDENCIES.txt" -Encoding UTF8
if ($LASTEXITCODE -ne 0) { throw "Dependency inventory failed" }
& $Python -c "import platform; print(platform.platform()); print(platform.python_version())" | Set-Content -LiteralPath "$Package\BUILD_RUNTIME.txt" -Encoding UTF8
Write-Host "Portable build created at $Package. Run scripts\smoke_windows.ps1 before sharing."
