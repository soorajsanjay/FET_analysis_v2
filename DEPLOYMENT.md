# Windows portable and Intune deployment

The portable deliverable is a **Windows x64 folder**, distributed as a ZIP. It
contains native, browser and worker executables plus their shared runtime. It does
not require a Python installation, pip or internet for analysis. Keep every file in
the extracted folder together. This release is unsigned unless your organisation
signs it. Actual execution on a managed PC requires that organisation's approval.

## End-user launch

1. Obtain the ZIP and its SHA-256 checksum from the same approved release channel.
2. Extract it completely to an IT-approved location. Do not run inside the archive.
3. Open `FET-Analyzer-v2.exe`. If WebView2 is unavailable, use
   `FET-Analyzer-Browser.exe` and an installed browser.
4. Select measurements and outputs in a separate writable project folder.
5. Follow README.md for parameter verification, configuration and analysis.

Checksums detect accidental changes but do not substitute for a trusted publisher.
Windows SmartScreen/App Control/AppLocker may block unsigned or unapproved EXEs,
DLLs or scripts. Do not change organisation policy to work around a block.

## Build, test, sign and archive

Use an approved Windows x64 machine with Python 3.11–3.13. Python 3.11 is used by CI.
From a PowerShell session permitted by your organisation:

```powershell
.\scripts\build_windows.ps1
.\scripts\smoke_windows.ps1
# Optional trusted signing; requires an available private key:
.\scripts\sign_windows.ps1 -CertificateThumbprint "YOUR_CERTIFICATE_THUMBPRINT"
.\scripts\package_windows.ps1
```

The build installs primary dependency versions constrained by `requirements.lock`,
checks native process exit codes, and builds three executables under
`dist\FET-Analyzer-v2`. It also copies documentation, configuration templates and
the synthetic example generator. `BUILD_DEPENDENCIES.txt`, `BUILD_RUNTIME.txt` and
`THIRD_PARTY_NOTICES.txt` document the runtime and third-party packages. The primary
requirements file is not a complete transitive lock; preserve the build inventory
and approved wheels for exact reproduction. Rebuild after source changes.

`package_windows.ps1` smoke-tests the actual folder, then creates
`dist\FET-Analyzer-v2-windows-portable.zip` and `.zip.sha256`. Run it after signing
so the checksum describes the signed deliverable. The signing helper verifies that
each entry-point signature is Valid; it does not sign every dependency DLL. IT
must determine trust requirements for all bundled binaries under its policy.
A self-signed certificate is not automatically trusted on colleagues' PCs.

Native-host logs are under `%LOCALAPPDATA%\FET Analyzer\logs`. The browser and native
hosts launch `FET-Analyzer-Worker.exe`; moving only one EXE breaks that relationship.
The browser smoke test exercises HTTP startup and a dashboard-triggered frozen
analysis. `--help` tests are not proof that WebView2 renders on another computer;
pilot the actual native window on the destination image.

## Intune-managed PCs

A portable package can be deployed through Intune as a Win32 app. **Intune does not
make an arbitrary unsigned executable trusted merely because it is in a ZIP.**
Your IT administrator should choose an installation context and approved directory,
apply publisher/hash or managed-installer policy as appropriate, and pilot it.

Microsoft's [Win32 packaging instructions](https://learn.microsoft.com/en-us/intune/app-management/deployment/create-win32-package)
use the Win32 Content Prep Tool to wrap installation files in `.intunewin`.
That wrapper is a delivery format for Intune, not the application executable.

Suggested IT handoff:

1. Scan the reviewed portable folder and its dependency inventory. Sign approved
   binaries/scripts or establish the required allowlisting policy.
2. Stage the **complete folder** with your organisation's install and uninstall
   scripts. Installation should copy into a versioned directory such as
   `%ProgramFiles%\FET Analyzer\2.0.0` in system context, or an approved per-user
   location in user context. Do not mix per-user paths with a SYSTEM install.
3. Create Start Menu shortcuts to the native and browser executables with a valid
   working directory. Users select a writable measurement folder inside the app;
   do not store datasets under Program Files.
4. Use Microsoft's tool, for example:

   ```text
   IntuneWinAppUtil.exe -c C:\Intune\FET-staging -s install.cmd -o C:\Intune\packages -q
   ```

   `install.cmd` here is the organisation-supplied installer in the staging folder.
   The repository does not contain tenant-specific Intune install/uninstall policy.
5. Configure Win32 app install/uninstall commands, x64 OS requirements, return codes
   and detection rules. Detect the executable **and version/build identity**, not
   just a folder. Choose versioned destinations/detection when replacing builds
   because the product version remains 2.0.0 across source fixes.
6. Deploy WebView2 Evergreen Runtime as an approved dependency for the native host,
   or provide the browser launcher. See Microsoft's
   [WebView2 distribution guidance](https://learn.microsoft.com/en-us/microsoft-edge/webview2/concepts/distribution).
7. Pilot under a standard user with actual App Control, antivirus, proxy, execution
   policy and filesystem settings. Test worker subprocesses, HTML/Excel export,
   offline charts, ZTR decompression, long paths and a representative TLM group.
8. Preserve scientific data on uninstall. Upgrade only when analysis is stopped;
   prefer a new versioned application folder and retain rollback capability.

No tenant deployment, administrator certificate or representative Intune device
was supplied for this release. Consequently no `.intunewin` tenant package or
managed-device compatibility certification is claimed. IT can wrap the tested
portable deliverable without installing Python on end-user PCs.

## Alternative: approved Python installation

`scripts/install_windows.ps1` creates an isolated environment under
`%LOCALAPPDATA%\FETAnalyzer`, installs the local package and creates launchers and
an optional desktop shortcut. Python must already be approved/installed:

```powershell
.\scripts\install_windows.ps1 -PythonCommand python
# Completely offline: provide all dependencies plus setuptools and wheel
.\scripts\install_windows.ps1 -Wheelhouse C:\Approved\fet-wheelhouse -NoDesktopShortcut
```

The offline branch uses `--no-index` and disables build isolation after installing
build dependencies from the supplied wheelhouse. Populate that wheelhouse on a
connected machine matching the destination Python version/architecture:

```powershell
python -m pip download -r requirements.lock "setuptools>=75" wheel -d C:\Approved\fet-wheelhouse
```

An IT-approved PowerShell policy/signature is still required to run the installer.
The root `run.cmd` is the simpler source route; the portable package is the route
for users who cannot install Python or dependencies.

## Evidence to retain

For a software release, keep its source commit, ZIP checksum, test log, dependency
inventory, signing/scan results and pilot outcome. For each scientific run keep
raw inputs, YAML, device parameter table, `run_manifest.json`, processing log,
error reports and the complete output tree. Generated reports may contain
measurement values, private paths and identifying sample names.
