"""pytest conftest for skills/tp-spec — ensure _shared is on sys.path."""
import sys
from pathlib import Path

_SHARED = Path(__file__).resolve().parent.parent / "_shared"
if str(_SHARED) not in sys.path:
    sys.path.insert(0, str(_SHARED))
