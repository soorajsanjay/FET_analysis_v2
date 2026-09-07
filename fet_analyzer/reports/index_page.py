"""Generate an output-root home page for all HTML and dashboard summaries."""
from __future__ import annotations

import csv
import html
import json
from pathlib import Path
from statistics import median
from urllib.parse import quote
from typing import Any

from fet_analyzer.path_utils import prepare_write_path, safe_path


def _read_csv(path: Path) -> list[dict[str, str]]:
    if not safe_path(path).exists():
        return []
    with safe_path(path).open(newline="", encoding="utf-8-sig") as handle:
        return list(csv.DictReader(handle))


def _number(value: Any) -> float | None:
    try:
        result = float(value)
        return result if result == result else None
    except (TypeError, ValueError):
        return None


def _fmt(value: Any, digits: int = 3) -> str:
    number = _number(value)
    if number is None:
        return "—"
    return f"{number:.{digits}g}"


def _link(root: Path, target: Path, label: str) -> str:
    relative = target.relative_to(root).as_posix()
    return f'<a href="{html.escape(quote(relative))}">{html.escape(label)}</a>'


def generate_html_index(output_root: Path) -> Path:
    """Write a portable landing page with report links and run-dashboard data."""
    output_root = output_root.resolve()
    index_path = output_root / "index.html"
    batch_rows = _read_csv(output_root / "batch_summary" / "master_summary.csv")
    tlm_rows = _read_csv(output_root / "TLM" / "tlm_master_summary.csv")
    master_tlm_workbook = output_root / "TLM" / "master_tlm_summary.xlsx"
    manifest: dict[str, Any] = {}
    manifest_path = output_root / "run_manifest.json"
    if safe_path(manifest_path).exists():
        manifest = json.loads(safe_path(manifest_path).read_text(encoding="utf-8"))
    errors: dict[str, Any] = {}
    error_path = output_root / "errors" / "error_report.json"
    if safe_path(error_path).exists():
        errors = json.loads(safe_path(error_path).read_text(encoding="utf-8"))

    report_files = sorted(
        path for path in output_root.rglob("*.html")
        if path.resolve() != index_path.resolve()
    )
    samples = sorted({row.get("sample_id", "") for row in batch_rows if row.get("sample_id")})
    ratios = [value for value in (_number(row.get("ion_ioff_log10")) for row in batch_rows) if value is not None]
    swings = [value for value in (_number(row.get("ss_min_mv_dec")) for row in batch_rows) if value is not None]
    run_stats = manifest.get("statistics", {})
    processed = sum(int(run_stats.get(key, 0) or 0) for key in ("transfer", "output", "general_iv", "tlm"))

    device_rows = []
    for row in batch_rows:
        device = row.get("device", "unknown")
        report = output_root / f"{device}_report.html"
        workbook = output_root / f"{device}.xlsx"
        report_cell = _link(output_root, report, "HTML") if report.exists() else "—"
        workbook_cell = _link(output_root, workbook, "Excel") if workbook.exists() else "—"
        device_rows.append(
            "<tr>"
            f"<td>{html.escape(device)}</td><td>{html.escape(row.get('sample_id',''))}</td>"
            f"<td>{html.escape(row.get('type',''))}</td><td>{_fmt(row.get('ion_ioff_log10'))}</td>"
            f"<td>{_fmt(row.get('ss_min_mv_dec'))}</td><td>{html.escape(row.get('quality_status',''))}</td>"
            f"<td>{report_cell} · {workbook_cell}</td></tr>"
        )

    tlm_table_rows = []
    for row in tlm_rows:
        sample = row.get("sample_id", "unknown")
        tlm_id = row.get("tlm_id", "")
        folder = output_root / "TLM" / sample / tlm_id
        report = folder / f"TLM_{sample}_{tlm_id}_report.html"
        workbook = folder / f"TLM_{sample}_{tlm_id}.xlsx"
        links = []
        rcw_raw = row.get("index_rcw_ohm_um")
        try:
            rcw_kohm_um = float(rcw_raw) / 1000.0
        except (TypeError, ValueError):
            rcw_kohm_um = None
        if row.get("index_source") == "ungated_ltlm":
            index_mode = "Ungated LTLM"
        elif row.get("index_source") == "gated_transfer_vg0":
            index_mode = f"Gated transfer at Vg={_fmt(row.get('index_actual_vg_v'))} V"
        else:
            index_mode = "Unavailable"
        if report.exists(): links.append(_link(output_root, report, "HTML"))
        if workbook.exists(): links.append(_link(output_root, workbook, "Excel"))
        tlm_table_rows.append(
            "<tr>"
            f"<td>{html.escape(sample)}</td><td>{html.escape(tlm_id)}</td>"
            f"<td>{html.escape(row.get('analysis_level','individual'))}</td>"
            f"<td>{html.escape(row.get('n_tlm_structures','1'))}</td>"
            f"<td>{html.escape(index_mode)}</td>"
            f"<td>{_fmt(row.get('index_rsh_ohm_sq'))}</td>"
            f"<td>{_fmt(rcw_kohm_um)}</td>"
            f"<td>{_fmt(row.get('index_rho_film_ohm_cm'))}</td>"
            f"<td>{_fmt(row.get('index_rhoc_ohm_cm2'))}</td>"
            f"<td>{html.escape(row.get('index_acceptance_status',''))}</td>"
            f"<td>{' · '.join(links) or '—'}</td></tr>"
        )

    grouped_reports: dict[str, list[Path]] = {}
    for report in report_files:
        relative = report.relative_to(output_root)
        group = relative.parts[0] if len(relative.parts) > 1 else "Device reports"
        grouped_reports.setdefault(group, []).append(report)
    report_sections = []
    for group, paths in grouped_reports.items():
        links = "".join(f"<li>{_link(output_root, path, path.relative_to(output_root).as_posix())}</li>" for path in paths)
        report_sections.append(f"<details><summary>{html.escape(group)} <span>{len(paths)}</span></summary><ul>{links}</ul></details>")

    document = f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>FET Analysis Home</title><style>
:root{{--ink:#17201d;--muted:#65716c;--accent:#126b5b;--accent2:#dcece7;--line:#d7ded9;--bg:#f2f4ef;--paper:#fff}}
*{{box-sizing:border-box}}body{{margin:0;background:var(--bg);color:var(--ink);font:15px/1.5 system-ui,-apple-system,Segoe UI,sans-serif}}
header{{background:linear-gradient(125deg,#123d35,#126b5b);color:#fff;padding:38px max(24px,calc((100% - 1240px)/2))}}header h1{{margin:0 0 6px;font-size:2.2rem}}header p{{margin:0;color:#d9ebe5}}
main{{max-width:1240px;margin:24px auto;padding:0 22px 48px}}.cards{{display:grid;grid-template-columns:repeat(auto-fit,minmax(170px,1fr));gap:12px}}.card,section,details{{background:var(--paper);border:1px solid var(--line);border-radius:8px;box-shadow:0 4px 16px #17201d0b}}.card{{padding:17px}}.card strong{{display:block;font-size:1.55rem;color:var(--accent)}}.card span{{color:var(--muted)}}section{{padding:20px;margin-top:18px}}h2{{margin:0 0 14px}}.toolbar{{display:flex;gap:10px;align-items:center;flex-wrap:wrap}}input{{min-width:280px;padding:9px 11px;border:1px solid var(--line);border-radius:5px}}.table-wrap{{overflow:auto}}table{{width:100%;border-collapse:collapse;font-size:13px}}th,td{{padding:8px 9px;border-bottom:1px solid var(--line);text-align:left;white-space:nowrap}}th{{background:var(--accent2);position:sticky;top:0}}a{{color:#0c6253;text-decoration:none}}a:hover{{text-decoration:underline}}details{{margin:8px 0;padding:11px 14px}}summary{{cursor:pointer;font-weight:650}}summary span{{float:right;color:var(--muted)}}ul{{columns:2;gap:28px}}.note{{color:var(--muted);font-size:13px}}@media(max-width:700px){{ul{{columns:1}}header{{padding:28px 22px}}}}
</style></head><body><header><h1>FET Analysis Home</h1><p>Run dashboard, device reports, TLM results, and downloadable analysis files.</p></header><main>
<div class="cards">
<div class="card"><strong>{processed or len(batch_rows)}</strong><span>processed measurements</span></div>
<div class="card"><strong>{len(samples)}</strong><span>samples</span></div>
<div class="card"><strong>{_fmt(median(ratios) if ratios else None)}</strong><span>median log10(Ion/Ioff)</span></div>
<div class="card"><strong>{_fmt(median(swings) if swings else None)}</strong><span>median SS (mV/dec)</span></div>
<div class="card"><strong>{len(tlm_rows)}</strong><span>TLM result sets</span></div>
<div class="card"><strong>{errors.get('error_count', run_stats.get('error', 0))}</strong><span>recorded errors</span></div>
</div>
<section><div class="toolbar"><h2>Device dashboard</h2><input id="deviceFilter" placeholder="Filter devices or samples"></div><p class="note">Preferred per-file metrics use the configured Ion method and recorded sweep-selection rules.</p><div class="table-wrap"><table id="deviceTable"><thead><tr><th>Device</th><th>Sample</th><th>Type</th><th>log10 Ion/Ioff</th><th>SS</th><th>Quality</th><th>Files</th></tr></thead><tbody>{''.join(device_rows) or '<tr><td colspan="7">No batch summary is available.</td></tr>'}</tbody></table></div></section>
<section><h2>TLM dashboard</h2><p class="note">Index values use an accepted ungated LTLM fit first, then an accepted gated-transfer fit at the common measured Vg nearest 0 V. Output-characteristic TLM remains an Excel-only sanity check. {(_link(output_root, master_tlm_workbook, 'Open gated / ungated / output-sanity master TLM workbook') if master_tlm_workbook.exists() else '')}</p><div class="table-wrap"><table><thead><tr><th>Sample</th><th>TLM</th><th>Level</th><th>Structures</th><th>Mode / read condition</th><th>Rsh (ohm/sq)</th><th>Contact resistance (kΩ·µm)</th><th>Film rho (ohm cm)</th><th>Contact rho (ohm cm2)</th><th>Status</th><th>Files</th></tr></thead><tbody>{''.join(tlm_table_rows) or '<tr><td colspan="11">No TLM summary is available.</td></tr>'}</tbody></table></div></section>
<section><h2>All HTML reports</h2>{''.join(report_sections) or '<p>No HTML reports were generated.</p>'}</section>
</main><script>const q=document.getElementById('deviceFilter'),rows=[...document.querySelectorAll('#deviceTable tbody tr')];q?.addEventListener('input',()=>{{const term=q.value.toLowerCase();rows.forEach(row=>row.hidden=!row.textContent.toLowerCase().includes(term))}});</script></body></html>"""
    prepare_write_path(index_path).write_text(document, encoding="utf-8")
    return index_path
