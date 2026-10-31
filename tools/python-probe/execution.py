"""Compatibility entry for boundary experiments; application owns the single implementation."""
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'backend' / 'src'))
from silicolab import restricted_python as implementation
sys.modules[__name__] = implementation
