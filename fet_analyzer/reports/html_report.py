"""Small, dependency-free HTML report helpers with embedded PNG assets."""

from __future__ import annotations

import base64
import html
import re
from pathlib import Path
from typing import Iterable

from fet_analyzer.path_utils import prepare_write_path, safe_path


_INLINE = re.compile(r"(`[^`]+`|\*\*[^*]+\*\*)")


def _inline(text: str) -> str:
    parts: list[str] = []
    position = 0
    for match in _INLINE.finditer(text):
        parts.append(html.escape(text[position:match.start()]))
        token = match.group(0)
        if token.startswith("**"):
            parts.append(f"<strong>{html.escape(token[2:-2])}</strong>")
        else:
            parts.append(f"<code>{html.escape(token[1:-1])}</code>")
        position = match.end()
    parts.append(html.escape(text[position:]))
    return "".join(parts)


def _markdown_subset(lines: Iterable[str]) -> str:
    """Render the limited Markdown subset used by the legacy report builders."""
    source = list(lines)
    output: list[str] = []
    index = 0
    while index < len(source):
        line = source[index].strip()
        if not line:
            index += 1
            continue
        if line.startswith("#"):
            level = min(len(line) - len(line.lstrip("#")), 4)
            output.append(f"<h{level}>{_inline(line[level:].strip())}</h{level}>")
            index += 1
            continue
        if line.startswith("```"):
            index += 1
            block: list[str] = []
            while index < len(source) and not source[index].strip().startswith("```"):
                block.append(source[index])
                index += 1
            if index < len(source):
                index += 1
            output.append(f"<pre><code>{html.escape(chr(10).join(block))}</code></pre>")
            continue
        if line.startswith("|") and index + 1 < len(source) and source[index + 1].lstrip().startswith("|"):
            rows: list[list[str]] = []
            while index < len(source) and source[index].strip().startswith("|"):
                rows.append([cell.strip() for cell in source[index].strip().strip("|").split("|")])
                index += 1
            if len(rows) >= 2:
                output.append("<table><thead><tr>" + "".join(f"<th>{_inline(cell)}</th>" for cell in rows[0]) + "</tr></thead><tbody>")
                for row in rows[2:]:
                    output.append("<tr>" + "".join(f"<td>{_inline(cell)}</td>" for cell in row) + "</tr>")
                output.append("</tbody></table>")
            continue
        if line.startswith("- "):
            output.append("<ul>")
            while index < len(source) and source[index].strip().startswith("- "):
                output.append(f"<li>{_inline(source[index].strip()[2:])}</li>")
                index += 1
            output.append("</ul>")
            continue
        output.append(f"<p>{_inline(line)}</p>")
        index += 1
    return "\n".join(output)


def embedded_png(path: Path) -> str:
    encoded = base64.b64encode(safe_path(path).read_bytes()).decode("ascii")
    return f"data:image/png;base64,{encoded}"


def write_html_report(
    output_path: Path,
    title: str,
    markdown_lines: Iterable[str],
    plot_files: Iterable[Path] = (),
) -> Path:
    """Write a standalone report; plot bytes are embedded as data URIs."""
    figures = []
    for plot in plot_files:
        if not safe_path(plot).is_file():
            continue
        label = plot.stem.replace("_", " ").title()
        figures.append(
            f'<figure><img loading="lazy" src="{embedded_png(plot)}" alt="{html.escape(label)}">'
            f"<figcaption>{html.escape(label)}</figcaption></figure>"
        )
    document = f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>{html.escape(title)}</title><style>
:root{{--ink:#17201d;--muted:#66706b;--line:#d9ddd7;--accent:#126b5b;--paper:#fff;--bg:#f4f5f0}}
*{{box-sizing:border-box}}body{{margin:0;background:var(--bg);color:var(--ink);font:15px/1.55 system-ui,-apple-system,Segoe UI,sans-serif}}
main{{max-width:1120px;margin:28px auto;padding:34px 42px;background:var(--paper);box-shadow:0 8px 30px #17201d14}}
h1,h2,h3{{line-height:1.2}}h1{{color:var(--accent)}}h2{{margin-top:2rem;border-bottom:1px solid var(--line);padding-bottom:.35rem}}
table{{width:100%;border-collapse:collapse;margin:1rem 0 1.5rem;font-size:14px}}th,td{{padding:8px 10px;border-bottom:1px solid var(--line);text-align:left;vertical-align:top}}th{{background:#e8f1ee}}
code{{background:#eef1ef;padding:.1rem .3rem;border-radius:3px}}pre{{overflow:auto;background:#17201d;color:#ecf3ef;padding:14px;border-radius:5px}}pre code{{background:transparent;padding:0}}.plots{{display:grid;grid-template-columns:repeat(auto-fit,minmax(320px,1fr));gap:18px}}
figure{{margin:0;border:1px solid var(--line);padding:10px;background:#fff}}img{{display:block;width:100%;height:auto}}figcaption{{color:var(--muted);margin-top:8px;font-size:13px}}
@media(max-width:700px){{main{{margin:0;padding:20px}}.plots{{grid-template-columns:1fr}}}}@media print{{body{{background:#fff}}main{{box-shadow:none;margin:0;max-width:none}}}}
</style></head><body><main>{_markdown_subset(markdown_lines)}
<section class="plots">{''.join(figures)}</section></main></body></html>"""
    prepare_write_path(output_path).write_text(document, encoding="utf-8")
    return output_path
