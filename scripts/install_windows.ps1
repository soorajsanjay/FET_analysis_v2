param(
    [string]$InstallRoot = "$env:LOCALAPPDATA\FETAnalyzer",
    [string]$Wheelhouse = "",
    [string]$PythonCommand = "python",
    [switch]$NoDesktopShortcut
)

$ErrorActionPreference = "Stop"
$ProjectRoot = Split-Path -Parent $PSScriptRoot
$Venv = Join-Path $InstallRoot ".venv"
$Python = Join-Path $Venv "Scripts\python.exe"

New-Item -ItemType Directory -Force -Path $InstallRoot | Out-Null
if (-not (Test-Path $Python)) {
    & $PythonCommand -m venv $Venv
    if ($LASTEXITCODE -ne 0) { throw "Python environment creation failed" }
}

if ($Wheelhouse) {
    & $Python -m pip install --no-index --find-links $Wheelhouse "setuptools>=75" wheel
    if ($LASTEXITCODE -ne 0) { throw "Offline build requirements are missing from the wheelhouse" }
    & $Python -m pip install --no-index --find-links $Wheelhouse -r (Join-Path $ProjectRoot "requirements.lock")
    if ($LASTEXITCODE -ne 0) { throw "Offline dependency installation failed" }
    & $Python -m pip install --no-index --find-links $Wheelhouse --no-build-isolation --no-deps $ProjectRoot
    if ($LASTEXITCODE -ne 0) { throw "Offline application installation failed" }
} else {
    & $Python -m pip install -r (Join-Path $ProjectRoot "requirements.lock")
    if ($LASTEXITCODE -ne 0) { throw "Dependency installation failed" }
    & $Python -m pip install --no-deps $ProjectRoot
    if ($LASTEXITCODE -ne 0) { throw "Application installation failed" }
}

$Launcher = Join-Path $InstallRoot "Start FET Analyzer.cmd"
$BrowserLauncher = Join-Path $InstallRoot "Start FET Analyzer in Browser.cmd"
$LauncherText = "@echo off`r`npushd `"%~dp0`"`r`n`"$Python`" -m fet_analyzer.native --root .`r`npopd`r`n"
$BrowserLauncherText = "@echo off`r`npushd `"%~dp0`"`r`n`"$Python`" -m fet_analyzer.dashboard --root .`r`npopd`r`n"
Set-Content -LiteralPath $Launcher -Value $LauncherText -Encoding ASCII
Set-Content -LiteralPath $BrowserLauncher -Value $BrowserLauncherText -Encoding ASCII

if (-not $NoDesktopShortcut) {
    $Shell = New-Object -ComObject WScript.Shell
    $Shortcut = $Shell.CreateShortcut((Join-Path ([Environment]::GetFolderPath("Desktop")) "FET Analyzer v2.lnk"))
    $Shortcut.TargetPath = $Launcher
    $Shortcut.WorkingDirectory = $InstallRoot
    $Shortcut.Save()
}

Write-Host "FET Analyzer installed at $InstallRoot"
