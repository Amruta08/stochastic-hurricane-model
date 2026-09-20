import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
SRC = ROOT / "src"

# (script filename, human-readable description, required-for-pipeline flag)
MODULES = [
    ("build_01_portfolio.py", "Module 1: Synthetic exposure portfolio", True),
    ("build_02b_event_set.py", "Module 2: HURDAT2 parsing + stochastic event set", True),
    ("build_03_hazard_windfield.py", "Module 3: Holland wind field (diagnostic sanity checks only - writes no tables)", False),
    ("build_04_vulnerability_loss.py", "Module 4: Vulnerability curves + Event Loss Table", True),
    ("build_05_ylt_simulation.py", "Module 5: 100,000-year YLT simulation", True),
    ("build_06_ep_curves.py", "Module 6: AAL / OEP / AEP / PML via SQL", True),
    ("build_07_geospatial_map.py", "Module 7: GeoPackage export for QGIS", True),
    ("build_08_pdf_report.py", "Module 8: Final PDF loss report", True),
]


def check_hurdat2_present():
    hurdat_path = ROOT / "data" / "raw" / "hurdat2.txt"
    if not hurdat_path.exists():
        print(f"ERROR: {hurdat_path} not found.")
        print("Download the latest HURDAT2 Atlantic file from NOAA NHC:")
        print("  https://www.nhc.noaa.gov/data/#hurdat")
        print(f"and save it to: {hurdat_path}")
        sys.exit(1)


def run_module(filename, description):
    print("\n" + "=" * 70)
    print(description)
    print("=" * 70)
    result = subprocess.run([sys.executable, str(SRC / filename)], cwd=str(SRC))
    if result.returncode != 0:
        print(f"\nFAILED at {filename} (exit code {result.returncode}). Stopping.")
        sys.exit(result.returncode)


if __name__ == "__main__":
    check_hurdat2_present()

    for filename, description, required in MODULES:
        run_module(filename, description)

    print("\n" + "=" * 70)
    print("PIPELINE COMPLETE")
    print("=" * 70)
    print("Outputs:")
    print(f"  - Database:    {ROOT / 'db' / 'portfolio.db'}")
    print(f"  - GeoPackage:  {ROOT / 'outputs' / 'maps' / 'portfolio_accumulation.gpkg'}")
    print(f"                 (open in QGIS to style + export the hero image)")
    print(f"  - PDF report:  {ROOT / 'outputs' / 'reports' / 'loss_report.pdf'}")
