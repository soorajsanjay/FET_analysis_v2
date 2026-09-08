"""
FET Analyzer — Automated FET electrical characterization analysis pipeline.

Usage:
    python -m fet_analyzer --input ./data --output ./output
    python -m fet_analyzer --config config.yaml --recursive
    python -m fet_analyzer --dry-run
"""

__version__ = "2.0.1"
__author__ = "Sooraj Sanjay"
__email__ = "sooraj.sanjay@gmail.com"
__copyright__ = "Copyright (c) Sooraj Sanjay"
from fet_analyzer.api import analyze_transfer

__all__ = ["analyze_transfer"]
