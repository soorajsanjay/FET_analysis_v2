"""Generate invented n-FET transfer and ungated LTLM data for installation checks."""
import argparse
import csv
import math
from pathlib import Path

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument("--output", required=True, type=Path)
args = parser.parse_args()
root = args.output.resolve()
root.mkdir(parents=True, exist_ok=True)
files = [root / "fet_analyzer_config.yaml", root / "device_parameters.txt", root / "IdVg__Demo_Synthetic_FET_Device__1.csv"]
files += [root / f"LTLM__Demo_Synthetic_TLM1_{length}um__1.csv" for length in (5, 10, 25, 50)]
if any(path.exists() for path in files):
    parser.error("Example files already exist. Choose a new folder to preserve existing data.")
files[0].write_text("device_defaults:\n  polarity: n\n  channel_length_um: 10.0\ntransfer:\n  ion_method: fixed_vg\n  ion_fixed_vg_v: 4.0\n", encoding="utf-8")
files[1].write_text("sample_label\tdevice_pattern\tpolarity\tchannel_width_um\toxide_thickness_nm\tdielectric_constant\tparameter_set_name\nDemo\t*\tn\t100\t90\t3.9\tSYNTHETIC_DEMO_ONLY\n", encoding="utf-8")
with files[2].open("w", newline="", encoding="utf-8") as handle:
    writer = csv.writer(handle)
    writer.writerow(["Vg", "Vd", "Vs", "Id", "Ig"])
    gates = [-2 + i * 0.1 for i in range(81)]
    for vg in gates + gates[-2::-1]:
        current = 1e-10 + 2e-6 * math.log1p(math.exp(3 * (vg - 1))) / 3
        writer.writerow([vg, 0.1, 0, current, 1e-13])
for length, path in zip((5, 10, 25, 50), files[3:]):
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        writer.writerow(["Vd", "Vs", "Id"])
        for index in range(21):
            vd = -0.1 + index * 0.01
            writer.writerow([vd, 0, vd / (2000 + 500 * length)])
print(f"Synthetic examples generated at {root}. These are not experimental results.")
