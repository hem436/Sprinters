import sys
from pathlib import Path

# POST /query runs Arka's agent (model/) and the document routes call Myank's service (extraction/) in this
# process (contract 01). In the Docker image PYTHONPATH already holds them.
_REPO = Path(__file__).resolve().parents[2]
for _part in ("model", "extraction"):
    _dir = _REPO / _part
    if _dir.is_dir() and str(_dir) not in sys.path:
        sys.path.append(str(_dir))
