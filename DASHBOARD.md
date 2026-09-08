# FET Analysis Studio

Designed and developed by © Sooraj Sanjay
(`sooraj.sanjay@gmail.com`).

The browser dashboard is an optional layer over the existing batch pipeline.

The dashboard runs the FET electrical-analysis pipeline. The batch command and
its output format remain unchanged.

## Start

```powershell
Set-Location -LiteralPath <measurement-folder>
python -m fet_analyzer.dashboard --root .
```

Use `--root .` after changing into the intended measurement folder. Avoid
putting an arbitrary file or stale directory in `--root`; the selected root is
also used as the Windows working directory for the analysis worker.

The dashboard opens at `http://127.0.0.1:8765`. Use `--no-browser` when it
should start without opening a browser, and `--port` to choose another port.

In the portable Windows build, double-click `FET-Analyzer-v2.exe` for the
native application window. Use `FET-Analyzer-Browser.exe` if WebView2 cannot
initialize. Both hosts delegate analysis to the primary executable's internal
worker mode. Keep the entire portable directory together because `_internal`
contains the scientific runtime. `FET-Analyzer-Worker.exe` remains an optional
batch-command convenience entry point.

For a completed run that does not need the live server, open the generated
`output/index.html`. It contains the run KPIs, device dashboard, TLM dashboard
(including sample-level MASTER fits), and links to all HTML and Excel results.

## Workflow

1. Choose or type an input folder. Run **Validate run** to see configuration,
   input, duplicate, readability, output-conflict, geometry, and Ion-read
   issues together. **Open output folder**, **Open HTML index**, and the
   diagnostic copy/export actions are available from the Run overview.
   A folder selected with **Choose input** is displayed immediately together
   with its derived output and configuration paths. The output path can be
   typed directly or selected independently with **Choose output**. Existing
   reports are then indexed in the background; Results are cleared during the
   switch so stale data from the previous project cannot remain visible.
2. Optionally provide a YAML configuration and enable recursive discovery.
   The Configuration page provides Ion and transfer-TLM method selectors for
   constant Vg, nominal gate field (`Vg/tox`), overdrive (`Vg-Vth`), and
   overdrive field (`(Vg-Vth)/tox`). Fields are converted per device using its
   oxide thickness. A live calculator previews the resulting Vg or Vov, and
   fixed-choice configuration fields are dropdowns.
   Independent checkboxes can include fixed-gate and fixed-overdrive Ion in the
   same run. Each accepts either voltage or electric field; field takes
   precedence when both are filled. Reports show current in A and µA/µm and
   retain the actual measured Vg and Vov selected from the sweep.
   Under gm smoothing, `adaptive_savgol` reveals its adaptive limits and
   stability controls; fixed-window and unsmoothed modes keep their existing
   behavior. Adaptive mode differentiates first, tests only windows below 10%
   of each contiguous usable region, and records its complete candidate audit
   in the device HTML and Excel outputs. If a region is too short for a legal
   five-point window, raw gm remains visible but peak-gm Vth and mobility are
   suppressed as unreliable.
   Compliance-plateau cleaning is off by default under Advanced.
   Constant Vg or constant nominal gate field is the default primary Ion
   condition. The configuration can be opened before it is complete, but
   Validate run and Run analysis require one of those values. Ion/Ioff always
   follows the selected primary Ion condition; optional overdrive results are
   additionally retained when enabled or when an overdrive override is present.
   Irrelevant Ion and TLM fields are hidden for the selected method. Use **Calculate
   Ion conditions** on Run overview to inspect per-device polarity, oxide
   source, requested field/voltage, resolved overdrive, and readiness before
   starting the batch. When the exact requested Vg is absent, analysis uses the
   nearest measured point and records the request, actual Vg, and mismatch in
   the corresponding device, batch-summary, and TLM outputs.
   Use **Device parameters** to create or edit `device_parameters.txt` directly
   in the dashboard. Rows may apply sample-wide or use filename wildcards for
   device-specific geometry, material, polarity, temperature, and noise-floor
   overrides. Fields with a fixed set of choices use dropdowns. Values are
   validated before the TSV is replaced.
3. Run the pipeline and follow its live processing log.
   Progress is reported as both processed-file count and percentage. A running
   job can be stopped from the same panel.
   Advanced execution settings provide three presets. **Full analysis** is the
   default and writes input-named Excel workbooks plus standalone HTML reports
   with embedded figures, without retaining plot folders. **Keep PNG plots**
   retains separate device, TLM, and batch graphics. **Fast analysis** keeps
   numerical extraction, JSON/CSV summaries, and HTML reports but skips the
   per-file Excel workbooks.
   The three checkboxes can be adjusted independently after selecting a preset.
   Reports use measured `Vds = Vd - Vs`; if only one terminal is recorded, the
   missing reference is explicitly noted as assumed 0 V. Single-Vds transfer
   files therefore retain their real measured bias instead of a blank
   preferred-bias field. Detailed transfer plots remain embedded in the device
   HTML report below the result tables.
   The master workbook records Cox, film thickness, dielectric stack, concise
   warning text, and a Best per File sheet. Each best-value remark identifies
   its measured Vds, direction, sweep type, sweep ID, read condition, and any
   warning. DIBL reports include a calculation-audit plot.
   Gate leakage is checked by the fraction of valid points satisfying
   `|Id| > |Ig|` (90% by default), not by a single worst ratio. Open/short
   sanity checks are warning-only and leave all extracted numbers unchanged.
4. Browse every generated Excel worksheet, CSV, and JSON report. The original
   report file can be downloaded from the report view.
5. Start Results in **Sample Overview**. Persistent sample, measurement-type,
   quality, and Ion-condition filters drive KPI cards, the sample-by-metric
   heatmap, the device-point/mean/95% CI view, and the relationship explorer.
   Individual points retain device, actual-bias, quality, and warning context;
   click a point or table row to open its existing HTML or Excel evidence.
   Arithmetic means and confidence intervals come from stored statistics for
   unfiltered sample views. Filtered view-only intervals use sample SD with
   `CI95 = 1.96 * SD / sqrt(N)`. N=1 has no interval and small N is labelled
   limited evidence.
6. Use **TLM Explorer** for measured total resistance × width, the least-squares
   fit and residuals, device metrics versus channel length, and fit parameters
   versus read bias. RcW and film resistivity are fit-level quantities and are
   never presented as per-length device measurements.
   TLM regression is ordinary least squares with a free intercept. `LTLM*`
   drain-voltage sweeps are authoritatively included as ungated TLM data while
   retaining their normal IV/output report; transfer-curve TLM and gated
   output-characteristic sanity fits are handled separately and are never
   included in HTML/dashboard plots. Index values prefer an accepted ungated
   LTLM fit, then an accepted gated-transfer fit at the common measured Vg
   nearest 0 V; review and rejected fits remain audit-only. The
   `TLM/master_tlm_summary.xlsx` workbook provides dedicated Gated TLM,
   Ungated LTLM, Output Sanity Check, and Fit Audit sheets.
   Gated-TLM resistance can be read at maximum measured current, fixed Vg,
   fixed nominal gate field, fixed overdrive, or fixed overdrive field.
   **Run TLM only - continue** performs a scoped preflight, requires an existing
   output folder, and atomically refreshes TLM artifacts without regenerating
   ordinary master summaries or non-TLM device outputs.
7. In **Plot Studio**, select a report and numeric X/Y parameters. Add multiple
   series to bottom/top X axes and left/right Y axes, choose linear or log axes,
   enter optional ranges, and export a PNG. All Results and Plot Studio charts
   use the bundled Plotly runtime for offline pan, zoom, selection, hover,
   autoscale/reset, legend filtering, and image export.
8. Graphics Gallery is shown only when standalone PNG/SVG/JPEG files were
   retained. Otherwise open the corresponding HTML reports for embedded plots.
9. Use Compare Runs to compare mean metrics against another output folder.

## Modularity

`fet_analyzer.dashboard.adapters.ReportCatalog` is the dashboard's interface to
analysis code. It currently registers Excel, CSV/TSV, and JSON adapters. A
similar pipeline can be integrated by registering another adapter implementing
`inspect(path, root)` and `read(dataset, limit)`; the web UI does not depend on
FET-specific Python analysis objects.

The dashboard invokes the public batch entry point in a child process. This
keeps dashboard state separate from analysis state and ensures dashboard runs
behave the same as command-line runs.

The advanced execution controls include **Overwrite existing outputs**. It is
off by default. When enabled, matching per-file reports, workbooks, metadata,
and metrics are replaced; when disabled, existing per-file outputs are skipped.

Progress covers the complete pipeline rather than only input-file parsing. The
bar remains below 100% while final device reports, batch/sample summaries, TLM
workflows, error reporting, the run manifest, or the HTML home page are still
being produced. A compact status bubble shows the active file or finalization
stage.

While a run is active, all temporary device and TLM images are contained inside
one hidden `output/.fet_work` directory. Do not delete it during processing.
Temporary images are removed after report embedding, and the directory is
removed after normal completion or dashboard cancellation. If the process is
forcibly terminated, abandoned run directories are reclaimed on the next
launch without disturbing a concurrent active run.

The equivalent command-line controls include `--no-device-excel`, `--save-plots`,
`--batch-plots`, and `--overwrite`. These affect export artifacts only; they do not change
measurement parsing or numerical extraction. The in-dashboard **README &
methods** page explains the GUI, extraction methods, output layout, and quality
warnings.
# Browser and native launch modes

The complete dashboard can be launched in either form:

```powershell
python -m pip install -e ".[native]"  # one-time source installation
Set-Location -LiteralPath <measurement-folder>
fet-dashboard --root .
fet-native --root .
```

Equivalent module commands are `python -m fet_analyzer.dashboard --root .`
and `python -m fet_analyzer.native --root .`. The Windows installer creates separate native and
browser launchers, plus a native desktop shortcut unless shortcuts are disabled.

`fet-dashboard` opens the system browser. `fet-native` opens the same local
interface in a native Windows WebView2 window. Both modes expose the same run,
configuration, device-parameter, report, statistics, TLM, comparison, plotting,
and interactive Results features.

# Performance control

**Parallel workers** is `0` by default, which selects an automatic process
count based on the CPU and number of input files. Each process handles a
different device, avoiding unsafe shared Matplotlib state. Set it to `1` for a
serial validation run or to a positive value to limit memory use. Worker count
does not change the calculations, plot quality, plot count, or report set.
