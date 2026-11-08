"""Rebuild the four independent datasets, then integration and validation."""
import subprocess
import sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[2]
for script in ('alibaba','burstgpt','pricing','thermal','integrate','validate','report'):
    subprocess.run([sys.executable,str(ROOT/'scripts/phase1'/f'{script}.py')],cwd=ROOT,check=True)
