# Synthetic installation check

These data are invented, not measurements or a calibration standard. Generate them in a new writable folder:

```powershell
python examples\generate_demo.py --output C:\FET\demo
python -m fet_analyzer --input C:\FET\demo --output C:\FET\demo-output --config C:\FET\demo\fet_analyzer_config.yaml --workers 1
```

Open `C:\FET\demo-output\index.html`. Expect one transfer file, four LTLM files, a TLM workbook, batch summaries, and error reports. The invented LTLM relation is `Rtotal = 2000 + 500*L[um]` ohm with width 100 um, so the ideal sheet resistance is 50,000 ohm/sq and RcW is 100,000 ohm um. Warnings and missing transfer metrics are possible: the demo checks plumbing, not instrument accuracy or physical validity. The generator refuses to overwrite its files.
