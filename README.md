# FET Analyzer v2

Local analysis of FET electrical-characterisation measurements: transfer curves,
output characteristics, general IV, gated transfer TLM and ungated LTLM. It writes
traceable numerical results, Excel workbooks and standalone HTML reports, and
provides a browser dashboard or a native Windows window.

Designed and developed by **Sooraj Sanjay** — sooraj.sanjay@gmail.com.

## Start here

| What you want | Use |
|---|---|
| Windows, no Python installation | Extract the complete portable ZIP; open `FET-Analyzer-v2.exe` or `FET-Analyzer-Browser.exe` |
| Run from this source repository | Install 64-bit Python 3.10 or newer, then double-click **`run.cmd`** |
| Repeatable batch analysis or automation | `python -m fet_analyzer --input ... --output ... --config ...` |
| Native window from source | `run.cmd --mode native --root "C:\FET\measurements"` |
| Review a completed run without running software | Open the output folder's `index.html` |
| Deploy to an Intune-managed PC | Give IT the portable folder and [DEPLOYMENT.md](DEPLOYMENT.md) |

**Before analysing real data, verify device geometry, dielectric/Cox, polarity,
and the Ion read condition.** Defaults are editable examples, not calibrated
parameters for your devices. A successful run does not establish that a reported
mobility or contact resistance is physically valid.

Contents: [installation](#installation), [first analysis](#your-first-analysis),
[inputs](#measurement-inputs), [parameters](#device-parameters-and-configuration),
[modes](#analysis-modes), [CLI](#command-line-reference), [results](#outputs-and-review),
[troubleshooting](#troubleshooting), [development](#development-and-release).
More detail: [dashboard guide](DASHBOARD.md), [methods and interpretation](METHODS.md),
[deployment](DEPLOYMENT.md), [architecture](V2_ARCHITECTURE.md), [review](REVIEW.md).

## Installation

### One-click source launcher on Windows

1. Clone this repository or download and extract its source ZIP to a writable
   folder, for example `C:\FET\FET_analysis_v2`. Do not run inside a ZIP viewer.
2. Install an approved **64-bit Python 3.10 or newer** with `pip` and `venv`.
   CI tests Python 3.10, 3.11, 3.13 and 3.14. The launcher checks `python` first,
   then installed `py` launcher versions from 3.14 through 3.10.
3. Double-click **`run.cmd`** in the repository root. It creates a version-specific
   environment such as `.venv-py314`, installs
   the application and dependencies, and opens the local browser dashboard.
4. Keep its console open while working. Stop a running analysis in the dashboard
   before closing the server; `Ctrl+C` stops the console server.

The first launch needs internet or an approved Python package mirror and may take
several minutes. Later launches reuse the matching versioned environment. A changed dependency specification
or `--reinstall` triggers setup again. Source edits are picked up by the editable
installation. The launcher does not elevate privileges or change execution policy.
If setup fails, the console stays open with the error.

```powershell
.\run.cmd --root "C:\FET\measurements"
.\run.cmd --mode native --root "C:\FET\measurements"
.\run.cmd --mode setup
.\run.cmd --reinstall --mode setup
.\run.cmd --mode batch --input "C:\FET\measurements" --output "C:\FET\results" --config "C:\FET\measurements\fet_analyzer_config.yaml"
.\run.cmd --mode doctor --input "C:\FET\measurements" --config "C:\FET\measurements\fet_analyzer_config.yaml"
```

`run.py --help` describes the launcher. To see the application's help after setup,
use the interpreter path printed by `run.cmd`, followed by `-m fet_analyzer --help`. Relative paths passed to
`run.cmd`/`run.py` are relative to the repository root; use absolute paths for data.
The default mode is browser, which does not require WebView2. Native mode installs
the optional Python host and requires Microsoft Edge WebView2 Runtime on Windows.

### Manual source installation

From the extracted repository:

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -c requirements.lock -e .
.\.venv\Scripts\python.exe -m fet_analyzer.dashboard --root "C:\FET\measurements"
# Optional native interface:
.\.venv\Scripts\python.exe -m pip install -c requirements.lock -e ".[native]"
.\.venv\Scripts\fet-native.exe --root "C:\FET\measurements"
```

Activation is optional: explicit interpreter paths avoid PowerShell activation
policy issues. Once activated, `python` and `fet-dashboard` refer to that environment.
On Linux/macOS, use `python3 -m venv .venv` and `.venv/bin/python` with the same
installation and batch/browser commands. The portable binaries are Windows-only;
Linux/macOS native UI and managed deployment are not validated in this release.

`requirements.lock` pins the primary scientific/native libraries; it is **not a
complete transitive lockfile**. Portable builds include their actual dependency
inventory. Use an IT-managed wheelhouse for reproducible offline installation.

### Portable Windows folder

Extract the whole distribution to a location IT permits and keep it together:

- `FET-Analyzer-v2.exe`: native application window and its own internal analysis worker.
- `FET-Analyzer-Browser.exe`: equivalent browser dashboard with console.
- `FET-Analyzer-Worker.exe`: optional batch CLI convenience entry point.
- `_internal/`: bundled Python, libraries and application resources; required.

No separate Python or pip setup is needed. Native mode needs WebView2; browser
mode uses an installed browser. The scientific code and Plotly charts work offline.
Store measurements and outputs in a separate writable project folder. A ZIP is
portable packaging, not permission to execute on a restricted PC. See deployment
instructions for signatures, allowlisting and Intune delivery.

## Your first analysis

1. **Make a project folder.** Put related input measurements together. Use a fresh,
   separate output directory for each scientific comparison or changed configuration.
2. **Open the dashboard** and choose the input folder. Choose the output folder
   independently if desired. Result indexing runs in the background after switching
   projects; wait for it to finish before inspecting results.
3. **Create/open local configuration** on Configuration. Set primary Ion to your
   intended signed gate voltage, gate field, overdrive or maximum-current method.
   The default fixed-Vg method is deliberately incomplete until its read value is set.
4. **Review Device parameters.** Set real width, channel length, polarity, dielectric
   thickness/constant or directly measured Cox. Remove provisional assumptions only
   after checking them. Use the Ion calculator to inspect per-device read readiness.
5. **Validate run.** Resolve configuration errors, unreadable inputs, duplicates,
   geometry issues and output conflicts. A warning may need scientific review even
   when it does not block execution.
6. **Run analysis.** Full analysis writes HTML plus per-file Excel. Fast analysis
   skips per-file Excel; Keep PNG plots retains external graphics. Worker count `0`
   is automatic; `1` is the serial reference and reduces concurrent memory use.
7. **Review results.** Start with errors, warnings and device reports, then Sample
   Overview and TLM Explorer. Check actual bias, sweep direction, provenance, fit
   acceptance and sample count before comparing headline values.
8. **Archive the complete output folder**, your input files, configuration and
   parameter table. Share the complete output tree to preserve links from `index.html`.

For an invented installation check, run `python examples\generate_demo.py --output
C:\FET\demo` and follow [examples/README.md](examples/README.md). Real measurements
are intentionally excluded from this repository.

## Measurement inputs

| Input | Supported contract |
|---|---|
| `.csv` | Comma-separated numeric measurement data, optionally with EasyEXPERT metadata before the column header; UTF-8/BOM supported |
| `.xlsx` | One worksheet, numeric measurement values and the same tabular layout as CSV; formulas and multiple sheets are rejected explicitly |
| `.xls` | Legacy binary Excel is rejected; export it as CSV or single-sheet `.xlsx` |
| `.xtr` / `.xml` | Keysight-compatible XTR measurement XML, not arbitrary XML |
| `.ztr` / `.zip` | Keysight-compatible compressed ZTR measurement archives, not arbitrary ZIP files |

Use columns such as `Vg,Vd,Vs,Id,Ig` (voltages in V, currents in A). Transfer analysis
needs a swept gate voltage and drain current; record drain/source bias and gate
leakage where available. Missing gate leakage limits leakage-qualified metrics.
A recorded `Vds` is used directly; otherwise transfer bias is derived from `Vd-Vs`.
This is a measurement parser, not a general importer for arbitrary spreadsheets,
formatted report workbooks or files containing unit strings in numeric cells.

The default structured filename convention is:

```text
measurementType__sampleLabel_sampleDetails_deviceType_deviceName__measurementCount.ext
IdVg__SampleA_SnO_TLM1_10um__1.csv
LTLM__SampleA_SnO_TLM1_25um__1.ztr
```

Sample labels should not contain underscores with the default structured pattern.
Filename parsing is centralized in `fet_analyzer/filename_conventions.py`; project
exceptions belong in YAML `filename_patterns` or `tlm.lch_regex`. Inspect the
detected value and source in dashboard preflight before running an analysis.

### Filename geometry and TLM rules

Any case-insensitive occurrence of `TLM` marks a file as a TLM structure. The
measured columns still determine whether it is a transfer, output, or general-IV
measurement. `LTLM` selects the ungated LTLM role. `TLM1`, `TLM02`, and similar
tokens identify the structure; plain `TLM` uses the stable identifier `TLM`.

The clearest complete geometry block is:

```text
CL<channel-length>_GL<gate-length>_CW<channel-width>
IdVg_SampleB_TLM1_CL25_GL20_CW100.csv
```

`CL`, `GL`, and `CW` are in micrometres even without a suffix. Integers, decimals,
case variants, optional label/value separators, and `um`, `µm`, or `μm` suffixes
are accepted. For example, `cl25.5_gl20_cw100`, `CL_25_GL_20_CW_100`, and
`CL25um_GL20µm_CW100μm` are equivalent apart from the first channel length.
The block supplies geometry for ordinary and TLM devices; it does not create TLM
membership without `TLM` in the filename.

| Result parameter | Built-in labels | Unit |
|---|---|---|
| `channel_length_um` | `CL`, `Lch`, `L`, `channel_length` | µm |
| `channel_width_um` | `CW`, `Wch`, `W`, `width`, `channel_width` | µm |
| `gate_length_um` | `GL`, `Lg`, `gate_length` | µm |
| `oxide_thickness_nm` | `tox`, `oxide`, `oxide_thickness` | nm |
| `film_thickness_nm` | `tfilm`, `film_thickness`, `semiconductor_thickness` | nm |

Short `L` and `W` labels require filename token boundaries and will not match
letters inside a sample name. Values must be finite and greater than zero. `CL`
always means channel length; contact dimensions remain explicit columns in
`device_parameters.txt`.

For a TLM filename only, one unlabelled micrometre token is a channel-length
fallback. All of these resolve 25 µm:

```text
IdVg_SampleB_TLM1_25um.csv
SampleB_25um_TLM1_IdVg.csv
sampleb_tlm_25µm.csv
```

Repeated equal values are deduplicated. Different unlabelled values, such as
`TLM1_25um_100um`, are ambiguous because the program cannot know which dimension
is channel length. Add `CL25`, supply a confirmed `device_parameters.txt` value,
or set `tlm.lch_regex`. Conflicting explicit values such as `CL25_Lch50` are also
reported rather than guessed. Unlabelled dimensions on non-TLM files are ignored.

Resolution order for channel length is: confirmed parameter-table row, configured
`tlm.lch_regex`, `CL`, another explicit length label, one unlabelled TLM `um` token,
metadata, then an allowed default. Other geometry uses confirmed table, filename,
metadata, then allowed default. An auto-generated `TEMPLATE_UNCONFIRMED` row cannot
erase explicit filename evidence. TLM fitting will not group a missing or ambiguous
length using an unconfirmed global template.

To add a stable organization-wide alias, edit the documented
`PARAMETER_CONVENTIONS` registry in `fet_analyzer/filename_conventions.py` and add
a parser test. For a project-only naming scheme, edit YAML instead. Material words
in a filename do **not** establish dielectric constant or Cox.

Duplicate representations are resolved by `general.file_priority` (normally CSV,
XLSX, XLS, XTR, ZTR); review which file was selected. Convert unsupported XLS files
before mixing them with other representations. Recursive discovery excludes output,
build and temporary directories, but keep source code separate from measurements.
ZTR decompression may create an input-side `decompressed_ztr` cache.

## Device parameters and configuration

Copy `config/config_template.yaml` into the measurement folder as
`fet_analyzer_config.yaml`, or create it in the dashboard. The CLI does not auto-load
that filename: **pass `--config` explicitly**. YAML overlays internal defaults.
Presets in `config/presets/` are starting points, not complete calibrated setups.

`device_parameters.txt` is a project-local **tab-separated** table editable in the
GUI. Default/inferred geometry is resolved first, followed by matching wildcard and
sample/device rows. More specific rows override less specific rows; conflicting
equally specific assignments are rejected. Inspect `geometry_sources` in results
for the actual resolution. Legacy per-device parameter files may also be present;
review resolved provenance when migrating an older project.

| Parameter | Meaning |
|---|---|
| `channel_width_um`, `channel_length_um`, `gate_length_um` | Electrical geometry; explicit labelled values can be inferred from the filename |
| `oxide_thickness_nm`, `dielectric_constant` | Used for `Cox = epsilon0 * epsilon_r / tox` unless direct Cox is provided |
| `cox_f_per_cm2` | Direct capacitance per area, in F/cm²; verify magnitude and units |
| `polarity` | Explicit `p` or `n`; affects signed read conditions and extraction conventions |
| `film_thickness_nm` | Semiconductor thickness for bulk film resistivity; distinct from gate oxide thickness |
| `contact_length_um`, `contact_width_um` | Contact geometry where required by TLM interpretation |
| `parameter_set_name` | Keep `TEMPLATE_UNCONFIRMED` until parameters have been checked |

`advanced.parameter_preflight_mode` supports `warning` (retain with warnings),
`strict` (suppress dependent metrics), and `error` (stop affected device). Generated
sample rows are provisional. Do not simply relabel template values as confirmed.

CLI relative input/output paths resolve from the working directory. YAML relative
input resolves from the YAML directory; YAML relative output resolves beneath the
resolved input. An explicit `--output` takes precedence. Prefer absolute paths in
scripts to avoid accidental writes to a different project.

## Analysis modes

| Mode | Purpose and important constraints |
|---|---|
| Transfer | Segment by measured Vds and sweep direction; extract gm, Vth, mobility, Ion/Ioff, SS and supported hysteresis/DIBL |
| Output characteristics | Drain sweeps, resistance/conductance and output plots; do not treat these as transfer mobility measurements |
| General IV | Retain classified IV evidence; not every FET metric applies |
| Gated transfer TLM | Compare resistance across channel lengths at controlled gate/overdrive conditions and compatible drain bias |
| Ungated LTLM | `LTLM*` files use low-drain-bias resistance fits even when incidental gate columns are present |
| Output TLM sanity check | Separate Excel-only audit; excluded from HTML/dashboard TLM plots |
| Summary only | Rebuild batch summaries/index from existing stored outputs without re-extracting measurements |
| TLM continuation | Refresh only `TLM/` in an existing output; ordinary device and master-summary artifacts retain their previous state |

### Ion and extraction choices

- Primary Ion methods: `fixed_vg` (including configured gate field),
  `maximum_measured`, `fixed_overdrive`, `fixed_overdrive_field`,
  `max_common_overdrive`. Configuration validation also handles documented aliases.
- A supplied gate field overrides fixed Vg; a supplied overdrive field overrides
  fixed Vov. Signed field conversion is `V = E[MV/cm] * tox[nm] * 0.1`. Overdrive
  uses `Vov = Vg-Vth` and needs a valid extracted Vth. Typical On conditions are
  negative for p-FETs and positive for n-FETs; use your device physics.
- When a requested gate voltage is not measured, choose a real nearest measured
  point. Equidistant Ion ties use lower median absolute current, then lower absolute
  voltage, then numeric voltage. Reports retain requested/actual conditions and mismatch.
- `report_ion_at_fixed_vg` and `report_ion_at_fixed_overdrive` can add both results
  without replacing the primary configured Ion. Ion/Ioff follows the primary condition.
- Vth methods: `peak_gm_tangent` and `constant_current`; the latter needs a target
  current density. gm smoothing: `none`, fixed `savgol`, opt-in `adaptive_savgol`.
  A gm smoothing window of zero disables fixed smoothing. Adaptive failures may
  suppress gm-dependent results instead of fabricating a peak.
- Ioff: `minimum_above_ig` or `minimum_measured`. SS eligibility is separately
  leakage-qualified. Hysteresis is a horizontal constant-current shift, not a
  forward/reverse Vth difference. Best values may come from different sweeps;
  check Best per File remarks and actual Vds.

### TLM interpretation

`tlm.transfer_read_mode` selects `maximum_current`, `constant_vg`,
`constant_gate_field`, `constant_overdrive` or `constant_overdrive_field`. Maximum
current can select different measured Vg across lengths and is flagged accordingly.
Set `tlm.transfer_read_vds_v` when a file has multiple drain biases.

TLM uses a free-intercept ordinary least-squares line through resistance × width
versus length. Fits retain `accepted`, `review` or `rejected_nonphysical` status,
residuals and reasons. A high R² alone is insufficient. At least three distinct
lengths are normally required; shared geometry and comparable operating points matter.

`tlm.tlm_output_vd_max = 0.1` means fit points in the **low-|Vd| window**, not read
resistance at a single 0.1 V point. The ungated path uses recorded Vd; use source-zero
measurements or explicitly review nonzero Vs before interpreting this resistance.
Film resistivity is `Rsh * film_thickness_nm * 1e-7` ohm cm. Specific contact
resistivity `rhoc` is a different quantity in ohm cm².

The additive `TLM/master_tlm_summary.xlsx` compares near-zero, fixed gate/field,
fixed overdrive/field and first accepted all-length On-state conditions. Existing
summary fields also retain best-fit and maximum-|Vg| selections; these are different
selection rules, not interchangeable operating points. Actual signed bias and
acceptance accompany the reported fits. Two or more eligible complete structures
can additionally produce sample-level `TLM/<sample>/MASTER/` aggregates.

## Command-line reference

Commands below assume an activated environment (or replace `python` with the
version-specific interpreter printed by `run.cmd`). For portable CLI use `FET-Analyzer-Worker.exe` in place
of `python -m fet_analyzer`.

```powershell
# Full analysis (fresh output recommended)
python -m fet_analyzer --input "C:\FET\data" --output "C:\FET\run-001" --config "C:\FET\data\fet_analyzer_config.yaml" --workers 1
# Discovery without numerical processing; configuration must be ready
python -m fet_analyzer --input "C:\FET\data" --config "C:\FET\data\fet_analyzer_config.yaml" --dry-run
# Transfer-only, reduced per-file exports
python -m fet_analyzer --input "C:\FET\data" --output "C:\FET\transfer" --config "C:\FET\data\fet_analyzer_config.yaml" --only transfer --no-device-excel
# TLM-only continuation; inspect preflight first
python -m fet_analyzer --input "C:\FET\data" --output "C:\FET\run-001" --config "C:\FET\data\fet_analyzer_config.yaml" --only tlm --tlm-continue --dry-run
python -m fet_analyzer --input "C:\FET\data" --output "C:\FET\run-001" --config "C:\FET\data\fet_analyzer_config.yaml" --only tlm --tlm-continue
# Rebuild summaries from stored metrics (raw data not required)
python -m fet_analyzer --output "C:\FET\run-001" --summary-only
# Environment/configuration/path diagnostics
python -m fet_analyzer --doctor --input "C:\FET\data" --config "C:\FET\data\fet_analyzer_config.yaml"
# Browser or native host, after installation
fet-dashboard --root "C:\FET\data" --port 8765
fet-native --root "C:\FET\data"
```

| CLI option | Effect |
|---|---|
| `--input/-i`, `--output/-o`, `--config/-c` | Explicit data, results and YAML paths |
| `--recursive/-r` | Search descendants; set YAML `general.recursive: false` to disable configured recursion |
| `--only transfer/output/general_iv/tlm` | Measurement filter; TLM-only full processing differs from scoped continuation |
| `--dry-run` | List discovered inputs; with continuation, inspect TLM eligibility without refreshing outputs (ZTR parsing may cache decompression) |
| `--summary-only` | Rebuild summaries/index from stored metrics; cannot combine with filtering, continuation or dry-run |
| `--tlm-continue` | Requires `--only tlm`; existing output and eligible raw TLM inputs required |
| `--workers N` | `0` automatic, `1` serial, positive N limits processes |
| `--no-device-excel` | Skip per-file Excel; retains numerical analysis and HTML |
| `--save-plots`, `--batch-plots` | Retain separate PNGs; HTML always embeds its figures |
| `--overwrite` | Replace matching per-file outputs; not a cleanup of all obsolete artifacts |
| `--doctor`, `--verbose/-v`, `--version/-V`, `--help/-h` | Diagnostics, debug log, version and help |

Browser options: `--root`, loopback `--host`, `--port`, `--no-browser`.
Native options: `--root`, `--debug`. Both use the same dashboard and worker pipeline.
The browser normally serves at `http://127.0.0.1:8765` and is a local desktop tool,
not a multi-user or network service.

## Outputs and review

| Artifact | Use |
|---|---|
| `index.html` | Portable run entry point with device/TLM links |
| Per-device HTML and input-named `.xlsx` | Sweep evidence, extraction details, warnings and embedded plots |
| Metrics JSON / metadata | Machine-readable values and provenance; canonical result schema 5.0 |
| `batch_summary/` | CSV/Excel master tables, best-per-file values and metric statistics |
| `TLM/` | Structure/sample workbooks, fit audits and TLM HTML |
| `run_manifest.json` | Runtime/configuration and run accounting |
| `processing_log.txt` | Processing and finalisation messages |
| `errors/error_report.json`, `.csv`, `.html` | Failure inventory, including successful runs with zero errors |

Output paths mirror measurement organisation where relevant. Temporary plot files
live under `.fet_work` during processing; do not remove it while analysis is active.
Normal completion/cancellation cleans it; stale work is reclaimed on a later run.

A normal completed batch returns **0** for success and **2** for recorded partial
failures while preserving successful outputs; startup/validation failure returns
nonzero (usually **1**). An empty discovery currently returns 0, so automation should
also inspect logs, manifest and expected output counts. Summary-only and TLM-only
refreshes have their own limited output scope; they are not new full analysis runs.

Changing configuration without `--overwrite` can leave old per-file results reused.
Use a fresh directory for comparisons. After scoped TLM continuation, ordinary
master summaries may reflect the previous run; inspect the newly generated TLM
artifacts directly or perform a full fresh analysis for a consistent archive.

Sample Overview shows individual observations, means, N, missing counts and 95%
intervals. Filtered view intervals use `1.96 * sample_SD / sqrt(N)`; they are normal
approximations, not small-sample t intervals. N=1 has no interval. Do not infer
independent replication from repeated sweeps of the same device.

## Troubleshooting

| Symptom | Action |
|---|---|
| Launcher cannot find Python | Install approved 64-bit Python 3.10 or newer or use the portable ZIP; `run.cmd` reports the interpreter candidates it checked |
| `[WinError 5] Access is denied` while starting analysis | Copy and fully extract the ZIP to an approved local folder, try outside OneDrive, inspect file Properties for an organization-permitted Unblock option, export diagnostics, and ask IT about application-control policy |
| `FET-Analyzer-Worker.exe` appears to do nothing | Open `FET-Analyzer-v2.exe` for the GUI, or run `FET-Analyzer-Worker.exe --help` from a console for batch syntax |
| TLM detected but channel length is missing | Add `CL<number>`, use one unlabelled `<number>um` token, configure `tlm.lch_regex`, or add a confirmed device-parameter row |
| TLM channel length is ambiguous | Remove competing unlabelled dimensions or label channel length explicitly, for example `CL25_GL20_CW100` |
| pip/proxy/certificate error | Use your institution's approved mirror/wheelhouse; do not disable certificate checks |
| Native window fails | Try browser executable; inspect `%LOCALAPPDATA%\FET Analyzer\logs`; ask IT about WebView2 |
| Port 8765 is occupied | Stop the old server or use `--port 8766` |
| Primary Ion is missing | Supply its selected gate/overdrive condition in Configuration and validate |
| No files or wrong grouping | Review extensions, filename pattern, recursion, duplicate selection and classification |
| Missing/unexpected mobility | Verify W/L/Cox, measured Vds, gm method, selected sweep and quality/suppression reasons |
| No accepted TLM fit | Check distinct lengths, width consistency, bias compatibility, fit residuals and nonphysical intercept/slope |
| TLM continuation is checking inputs | ZTR preflight can take minutes; wait for inline status and confirmation |
| Excel save error | Close workbooks in Excel, check write permission and use a short output path |
| Results look unchanged | Use a fresh output folder or deliberately enable overwrite |
| Restricted PC blocks EXE/script | Ask IT to approve/package the application; portability does not override policy |

When reporting a problem, provide application/build version, launch command,
configuration, parameter provenance, error report and relevant log. Remove private
paths/measurements before making diagnostics public.

## Python API

`from fet_analyzer import analyze_transfer` accepts a mapping of column names to
numeric sequences, a resolved device dictionary, and optional configuration and
metadata. It returns a canonical metrics dictionary without producing files:

```python
from fet_analyzer import analyze_transfer
result = analyze_transfer(
    columns={"Vg": [-1, 0, 1, 2, 3], "Vd": [0.1]*5,
             "Id": [1e-9, 1e-8, 1e-7, 2e-7, 3e-7], "Ig": [1e-13]*5},
    device={"channel_width_um": 100, "channel_length_um": 10,
            "oxide_thickness_nm": 90, "cox_f_per_cm2": 3.84e-8, "polarity": "n"},
    config={"transfer": {"ion_method": "fixed_vg", "ion_fixed_vg_v": 2}},
)
```

This short invented array illustrates calling syntax, not sufficient sampling for
all metrics. The API caller owns parameter resolution and scientific validation;
it does not perform the complete CLI file/preflight/report workflow.

## Development and release

```powershell
python -m pip install -c requirements.lock -e ".[test,native,build]"
python -m unittest discover -s tests -v
python -m compileall -q fet_analyzer tests run.py examples scripts
# From a PowerShell session permitted by your policy:
.\scripts\build_windows.ps1
.\scripts\smoke_windows.ps1
.\scripts\package_windows.ps1
```

CI runs Windows tests, coverage, syntax checks and a frozen application smoke test.
Builds include native/browser/worker executables, configuration templates, synthetic
example generator, documentation, third-party notices and dependency inventory.
The package script checks the built runtime before writing a ZIP and SHA-256 file.
A trusted signing certificate must be supplied separately; repository builds are unsigned.

This repository is a clean source snapshot with synthetic examples only. Avoid
committing real measurements, local parameter tables, outputs, credentials or signing
keys. The ignore rules do not remove files already tracked in Git. Private access
can later be changed to public in GitHub Settings → General → Danger Zone → Change
repository visibility; review the complete history, collaborator rights and licensing
before doing so. [NOTICE.md](NOTICE.md) describes attribution and intended use;
no general open-source licence has been selected for the project.
