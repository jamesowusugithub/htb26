"""Rebuild the analytical layer without regenerating the harmonised sources."""
import subprocess
import sys
from pathlib import Path

ROOT=Path(__file__).resolve().parents[2]
for name in ('workloads','hardware','costs','validate','report'):
    subprocess.run([sys.executable,str(ROOT/'scripts/integrated'/f'{name}.py')],cwd=ROOT,check=True)
