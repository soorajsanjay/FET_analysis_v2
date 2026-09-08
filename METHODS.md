# FET Analyzer v2

Automated FET electrical-characterization analysis with reproducible batch
outputs and a local browser dashboard.

Designed and developed by © Sooraj Sanjay
Contact: sooraj.sanjay@gmail.com

## Batch analysis

```powershell
python -m fet_analyzer --input <measurement-folder> --output <output-folder>
```

## Dashboard

```powershell
Set-Location -LiteralPath <measurement-folder>
python -m fet_analyzer.dashboard --root .
```

Run the GUI from the measurement folder and use `--root .`. This keeps the
worker's Windows working directory valid even when the installation or portable
application has been moved.

The same interface can run in a native Windows window when the optional native
dependency is installed:

```powershell
pip install ".[native]"
Set-Location -LiteralPath <measurement-folder>
fet-native --root .
```

The browser and native interfaces share one server, API, configuration editor,
device-parameter editor, run controls, reports, plots, and analysis methods.
They remain separate launch choices; neither replaces the other.

The dashboard runs locally on `127.0.0.1` and provides run control,
full-pipeline progress, report browsing, an interactive Sample Overview, a TLM
Explorer, Plot Studio, retained graphics when enabled, and run comparison.
Results charts use a locally bundled Plotly runtime, so pan, zoom, selection,
hover, legend filtering, axis controls, and PNG export work without internet
access. Sample cards and plots retain individual observations, N, missing count,
arithmetic mean, and 95% confidence intervals; N=1 intervals are shown as
unavailable and very small groups are labelled limited evidence.
Its advanced controls include an opt-in overwrite checkbox. The progress bar
reaches 100% only after final reports, summaries, TLM processing, and the HTML
index are complete; a small status bubble identifies the current stage.
The default output embeds plots in standalone HTML reports and does not retain
plot folders. Use `--save-plots` and/or `--batch-plots` only when separate PNG
files are required; these options do not change numerical analysis.

During processing, transient images are contained in one hidden `.fet_work`
directory under the output folder. It is removed automatically when the run
finishes; abandoned run directories are reclaimed safely on the next launch.

Device plotting and finalized report rendering run in independent processes by
default. Use the dashboard's **Parallel workers** field or `--workers N` to set
a fixed limit; `0` selects an automatic value and `1` provides a serial
reference mode. Parallel execution uses the same analysis and plotting
functions, DPI, image dimensions, filenames, and output count.

Every completed run also writes `index.html` in the output root. This portable
home page mirrors the main dashboard metrics and links every device, TLM, and
error HTML report together with the corresponding Excel workbooks.

The Sample Overview uses canonical values from
`batch_summary/master_summary.csv` and stored unfiltered statistics from
`metric_statistics.csv`. Statistics for active dashboard filters are view-only
and use sample SD with `CI95 = 1.96 * SD / sqrt(N)`; they are not written back
to reports. The TLM Explorer keeps fit-level RcW and resistivity separate from
device metrics versus channel length, and links plotted evidence to existing
device and TLM HTML/Excel reports.

Choosing a different project folder updates the displayed input, derived
output, and project-local configuration paths immediately. The output path is
editable and also has an independent folder picker; it may be outside the input
folder, and a typed missing directory is created when analysis begins. Existing
reports in the selected output folder are indexed in the background; the
current-stage bubble shows that indexing is in progress and the Results views
refresh only from the new project revision.

Compliance-plateau cleaning is disabled by default. Ion and transfer-TLM reads
can use a constant gate voltage, nominal gate field (`Vg/tox`), overdrive
(`Vg-Vth`), or overdrive field (`(Vg-Vth)/tox`). A field in MV/cm is converted
for each device using its recorded oxide thickness:
`V[V] = E[MV/cm] x tox[nm] x 0.1`. Field modes therefore require a positive
`oxide_thickness_nm`; overdrive modes also require a valid extracted Vth.

If the requested Vg is absent from a sweep, the nearest measured Vg is used.
Device HTML/Excel reports, batch summaries, and TLM outputs retain the requested
condition, actual measured condition, and voltage/field mismatch so the
substitution is auditable.

Ion and Ioff are reported both in amperes and as width-normalized µA/µm when a
positive channel width is available. Two independent dashboard checkboxes can
add fixed-gate and fixed-overdrive Ion results to the primary configured-Ion
result. Both may be enabled together. A supplied gate field takes precedence
over fixed Vg, and a supplied overdrive field takes precedence over fixed Vov;
reports retain the requested field and the actual measured Vg/Vov used.

Constant Vg (or constant nominal gate field) is the default primary Ion read.
A fresh configuration remains editable, but analysis preflight blocks until a
Vg or gate-field value is supplied. Ion/Ioff uses the same selected Ion
condition and the configured leakage-qualified Ioff. Device reports label the
physical measured Vds, including single-Vd files, and include a DIBL audit plot
with fit points, equation, polarity convention, R², and N.

Quality warnings are coverage based: the gate-leakage warning reports the
fraction of valid points for which `|Id| > |Ig|` and defaults to requiring 90%.
Warning-only open/short checks identify predominantly fA-to-pA flat sweeps or
predominantly flat high width-normalized current. They do not remove data or
change extracted results. Master summaries include brief warning text, Cox and
its source, film thickness, dielectric stack, and a separate best-per-file
table whose remarks retain measured Vds, direction, sweep type, sweep ID, read
condition, and warnings.

Set `transfer.smooth_method: adaptive_savgol` to opt into adaptive gm
smoothing. gm is still calculated first by central difference; each contiguous
finite region is then assessed independently. The method tests odd windows from
5% up to a strict limit below 10% of that region, selecting the smallest stable
plateau while guarding gm peak magnitude and location. Short regions that
cannot support a legal five-point window retain raw gm for inspection and
suppress peak-gm Vth and mobility. Candidate diagnostics and the selected
peak-region window are recorded in JSON, device Excel/HTML, and batch summaries.

Transfer curves are segmented by physical measured drain bias before gate-sweep
direction is detected: a measured `Vds` column is used directly, otherwise Vds
is calculated row by row as `Vd - Vs`. Undersized bias runs are quarantined with
their raw-index provenance and cannot contaminate a neighboring gm derivative.
Extraction independently rechecks Vds homogeneity before reporting gm-dependent
Vth or mobility. A gm peak one point inside a Vg boundary remains valid when its
central-difference support contains three same-bias points; boundary proximity
is recorded for review but is not itself a rejection rule. Configure the bias
grouping threshold with `transfer.vds_segmentation_tolerance_v`.

The dashboard provides a live Vg/Vov field calculator, per-device pre-run Ion
calculator, method-specific controls, and dropdowns for configuration or
device-parameter fields with a fixed list of supported choices.
Configuration validation runs before saving or analysis. Parameter preflight
supports `warning`, `strict`, and `error` modes, and TLM fits retain their data
with `accepted`, `review`, or `rejected_nonphysical` acceptance status.
The **Device parameters** page provides a validated table editor for the
project-local `device_parameters.txt`, including sample/device wildcard rows
and all supported geometry and material fields.

The public in-memory API is available as `fet_analyzer.analyze_transfer(...)`.
Metrics JSON uses the versioned canonical result schema `5.0`; parser and
analysis registries expose controlled extension points without changing CLI
dispatch code.

`film_thickness_nm` is available in the device defaults and master device
parameter table. When supplied, TLM outputs include semiconductor film
resistivity using `rho_film [ohm cm] = Rsh [ohm/sq] × thickness[nm] × 1e-7`,
as well as specific contact resistivity `rhoc`.

If a sample contains at least two complete TLM structures, the pipeline keeps
their individual analyses and additionally writes `TLM/<sample>/MASTER/`.
At every shared read bias it groups observations by channel length, reports
mean, sample standard deviation, count, and contributing TLM IDs for Id and
Rtotal, then performs the TLM fit through the mean Rtotal at each length.

TLM lines use ordinary least-squares regression with a free intercept. Files
named `LTLM*` remain available for their normal output/IV analysis and are also
treated authoritatively as ungated TLM measurements, even if an instrument
export contains an incidental gate column. Resistance is extracted from the
low-Vd region without a gate-bias label. Transfer-curve TLM files remain the
gated path; gated output-characteristic TLM is kept separately as an Excel-only
sanity check and is excluded from HTML/dashboard plots. Index values use an
accepted ungated LTLM fit first, then an accepted gated-transfer fit at the
common measured Vg nearest 0 V. The additive `TLM/master_tlm_summary.xlsx` workbook compares these modes
on separate sheets and does not select a generic "best" gated fit.

Gated rows are reported near 0 V, at the unified Ion fixed-gate/field setting,
at the unified Ion overdrive/field setting, and at the first accepted all-length
fit reached from the measured per-device Ioff envelope toward the On state.
Every reported fit has a TLM-line/residual plot, and gated groups also receive a
parameter-versus-Vg context plot.

To refresh only TLM results in an existing output folder, use
`python -m fet_analyzer --input . --output .\output --only tlm --tlm-continue`,
or choose **Run TLM only - continue** in the dashboard. This scoped mode
reprocesses raw TLM-role inputs and atomically replaces only the `TLM` folder;
ordinary master summaries and non-TLM outputs are not regenerated.

The gated-TLM resistance read condition is controlled only by
`tlm.transfer_read_mode`: `maximum_current`, `constant_vg`,
`constant_gate_field`, `constant_overdrive`, or `constant_overdrive_field`.
Maximum-current mode records the measured Vg selected for every device and
warns because those Vg values may differ across channel lengths.

See [DASHBOARD.md](DASHBOARD.md) for dashboard usage and
[DEPLOYMENT.md](DEPLOYMENT.md) for managed Windows and Intune deployment.

## Portable Windows application

`scripts/build_windows.ps1` creates one shared portable folder containing:

- `FET-Analyzer-v2.exe` — primary native WebView2 window and internal worker;
- `FET-Analyzer-Browser.exe` — explicit browser/console fallback;
- `FET-Analyzer-Worker.exe` — optional batch CLI convenience entry point.

Keep the complete folder together. Moving only the primary executable will
leave it without its shared scientific runtime. Run
`scripts/smoke_windows.ps1` after building. Native startup failures are written
under `%LOCALAPPDATA%\FET Analyzer\logs` and display a dialog pointing to the
browser fallback. Use `FET-Analyzer-Worker.exe --doctor --input <folder>` for a
runtime, parser, configuration, and path diagnostic.

## Reliability outputs

Every completed run writes:

- `run_manifest.json`
- `processing_log.txt`
- `errors/error_report.json`
- `errors/error_report.csv`
- `errors/error_report.html`

A partial failure returns a non-zero exit code while preserving successful
device outputs for review.
