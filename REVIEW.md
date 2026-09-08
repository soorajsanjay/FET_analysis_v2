# Release readiness review — 8 September 2026

## Scope and conclusion

Reviewed the current source snapshot, including pre-existing uncommitted dashboard
and TLM fixes, CLI dispatch, parser contracts, configuration/device provenance,
launcher/build/install/signing scripts, output lifecycle, documentation and tests.
This is an engineering review and regression check, not an independent validation
of every extraction formula or an Intune certification. The intended delivery is
a private, clean source repository and an unsigned portable Windows build for pilot use.

## Issues corrected during this review

- Centralized filename identity and geometry in `fet_analyzer/filename_conventions.py`.
  Any filename containing TLM is now a TLM role, channel length can be recovered
  from a unique micrometre token anywhere in that filename, and labelled CL/Lch,
  GL/Lg and CW/Wch geometry retains explicit provenance and ambiguity errors.
- The frozen dashboard now relaunches the primary executable in internal worker
  mode. Diagnostics actively probe the worker route and report Windows launch or
  application-control failures with actionable paths and error numbers.
- Source launch now supports Python 3.10 and newer, creates version-specific virtual
  environments, and uses a tested Python 3.14 dependency branch.

- Binary XLSX was being passed to the CSV text parser. Numeric single-worksheet
  XLSX now uses openpyxl; ambiguous multiple sheets, formulas and legacy XLS fail
  with actionable conversion instructions.
- `--dry-run --only tlm --tlm-continue` previously reached the real continuation
  before the dry-run branch. It now invokes preflight only and reports eligibility.
- `--summary-only` previously depended on discovery of raw files and a configured
  Ion read. It now rebuilds directly from the existing output; incompatible mode
  combinations are rejected.
- An explicit input directory did not consistently control the default output
  location. The override is now resolved before deriving a relative output.
- Negative worker counts are now rejected. Empty-input TLM continuation returns
  failure rather than reporting a successful refresh.
- The local dashboard accepted foreign Origin/Host requests. It now checks Host,
  Origin and cross-site browser requests while retaining ordinary local clients.
- Windows build/install scripts now check native process exit codes. Offline setup
  no longer attempts an online pip upgrade and receives build dependencies from
  its wheelhouse. The signing script's variable-colon syntax error was fixed and
  it no longer accepts an UnknownError signature as success.
- Frozen smoke tests require a successful analysis and concrete output artifacts;
  partial failure is no longer accepted as a passing release smoke test.
- Corrected ungated TLM fit-length/point counts in the dashboard and replaced
  misleading hysteresis threshold-shift tooltips with constant-current wording.
- Added root source launcher, synthetic demo generator, portable ZIP/checksum
  script, third-party notices inventory and expanded user/deployment documentation.

## Validation

The pre-change suite passed 126 tests. With the shared filename conventions,
launcher, diagnostics, CLI and local-origin regressions, the suite passes 152
tests on Windows with Python 3.13.14.
The synthetic five-file batch completed with zero reported processing errors and
created transfer, LTLM, per-file Excel/HTML, batch summaries and the run index.
The same 152 tests also pass against the clean source export with the constrained
scientific dependency versions. Coverage is 62% (CI floor: 50%). Python compilation,
PowerShell syntax and both dashboard JavaScript syntax checks passed.
The root run.cmd bootstrapped a new environment and its doctor mode returned READY.
The fresh frozen build passed native/browser/worker help, the primary executable's
internal-worker doctor path, worker doctor/dry-run, HTTP startup and dashboard-triggered
analysis from a path containing spaces with exit 0 and required output
artifacts. The live browser displayed synthetic Sample Overview and TLM Explorer
results; the ungated fit counts now show four lengths and four points.
The native WebView2 window itself was not visually inspected on a managed PC.

## Remaining limits and scientific review requirements

- The original checkout contains tracked private measurements and sample-specific
  parameter rows. The new repository exports a fresh source-only snapshot and does
  not inherit the old Git history. Original files remain in the original checkout.
- Device/template defaults are not confirmed geometry or dielectric values. Confirm
  width, length, Cox/thickness, polarity and read bias before reporting numbers.
- Ungated LTLM resistance fits recorded Vd. Nonzero source bias needs explicit
  review; this release does not redefine its independent variable.
- Summary-only rebuilds from stored metrics, not raw measurements. TLM continuation
  deliberately leaves ordinary master summaries at their earlier state.
- Filtered 95% intervals are normal approximations and do not account for repeated
  measures or small-sample t uncertainty. Use the observation/provenance tables.
- Native WebView2 behaviour, trusted signing, malware/application-control scans,
  offline wheelhouse installation and Intune deployment need destination-side
  validation. No trusted signing certificate or managed test PC was supplied.
- The primary requirements file is not a full transitive lock. Preserve actual build
  dependency inventory and approved wheels for exact reproduction.
- The project has attribution/intended-use notices but no chosen open-source licence.
  Select the desired reuse licence before broad public distribution.

The test suite checks many numerical and provenance contracts, but passing tests
cannot establish instrument calibration, appropriateness of a chosen extraction
method, or the physical correctness of unreviewed datasets.
