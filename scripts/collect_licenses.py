"""Collect installed distribution licenses for a portable delivery."""
import argparse
from importlib.metadata import distributions
from pathlib import Path

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument("--output", required=True, type=Path)
args = parser.parse_args()
sections = ["Third-party metadata and license texts from the build environment. Includes build tools and runtime libraries.\n"]
for dist in sorted(distributions(), key=lambda item: item.metadata.get("Name", "").lower()):
    sections.append(f"\n{'=' * 72}\n{dist.metadata.get('Name')} {dist.version}\n"
                    f"License: {dist.metadata.get('License-Expression') or dist.metadata.get('License', 'See bundled text')}\n")
    for file in dist.files or []:
        if any(term in file.name.lower() for term in ("license", "copying", "notice")) and file.suffix.lower() not in (".py", ".pyc"):
            path = Path(dist.locate_file(file))
            if path.is_file():
                sections.append(f"\n--- {file} ---\n" + path.read_text(encoding="utf-8", errors="replace"))
sections.append("\nPlotly.js bundled license:\n" + (Path(__file__).resolve().parents[1] / "fet_analyzer/dashboard/static/PLOTLY-LICENSE.txt").read_text(encoding="utf-8"))
args.output.write_text("\n".join(sections), encoding="utf-8")
