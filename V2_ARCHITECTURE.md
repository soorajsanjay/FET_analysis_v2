# FET Analyzer v2 architecture

The v2 pipeline preserves the existing parsers, cleaning, extraction methods,
plots, reports, batch summaries, and TLM calculations. It adds typed,
standalone sweep analysis and a sample-level metric database.

## Processing flow

1. Parse each input file.
2. Classify it as transfer, output, general IV, or TLM-modified transfer/output.
3. Resolve device parameters with this precedence:
   device_parameters.txt > filename > numeric metadata > config defaults.
4. Split the data by fixed bias and sweep direction.
5. Clean each segment independently.
6. Analyze each standalone segment.
7. Generate flat JSON artifacts, an input-named Excel workbook, and a
   standalone HTML report with embedded plots. Separate PNGs are optional.
8. Group file observations by filename-derived sample ID.
9. Discover and plot every metric having observations at multiple values of a
   numeric device parameter.
10. Run the existing cross-length TLM workflow.

Names, labels, sample IDs, and measurement labels are derived only from the
filename. Metadata strings are retained for audit display. Metadata may supply
numeric geometry only when the same parameter is unavailable from the filename
or the master device parameter table.

## Standalone analyzers

- fet_analyzer.analysis.transfer_sweep.analyze_transfer_sweep accepts one
  transfer segment at one Vds and one direction. It returns a
  TransferSweepResult containing Vth, mobility, SS, Ion/Ioff, gm, warnings,
  direction, bias, and source identity.
- fet_analyzer.analysis.output_sweep.analyze_output_sweep accepts one output
  segment at one Vg. It returns average, median, and low-Vd linear-fit
  resistance plus gds. A missing gate variable is represented by
  no_gate_bias=True and gate_bias_v=None.
- fet_analyzer.analysis.numerics contains reusable gm, SS, Ion/Ioff, and gds
  primitives. Analysis modules do not import plotting modules.

Each `<input-name>.xlsx` contains a Sweep Results sheet with one long-form
result object for each unique (bias, direction) segment. The workbook and its
`<input-name>_report.html`, metadata JSON, and metrics JSON are written directly
to the output root rather than a per-file folder.

## Sample database

sample_database/sample_database.json, .csv, and .xlsx contain one observation
per processed file, grouped by filename-derived sample ID. The database
discovers every numeric metric that can be paired with at least two different
values of a numeric parameter. Optional comparison PNGs are written under
sample_database/plots/<sample>/ only when plot retention is enabled.

The output root also contains `index.html`, a static run home page generated
after the manifest and report sets are complete. It reads the durable CSV/JSON
outputs and links rather than duplicating analytical calculations.

Dedicated TLM processing has two levels: `(sample, TLM id)` preserves each
physical structure, while `(sample, MASTER)` is created only when at least two
complete structures are available. MASTER groups observations by read bias and
channel length, stores Id/Rtotal mean, sample standard deviation and count, and
fits the mean Rtotal values. `film_thickness_nm` enables conversion from sheet
resistance to bulk film resistivity without changing contact-resistivity logic.

The dedicated TLM workflow additionally writes Rc, RcW, Rsh, transfer length,
contact resistivity, and fit quality against Vg where sufficient channel
lengths are available.
