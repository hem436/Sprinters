import sys
from pathlib import Path

# The agent package lives in model/ next to backend/ (POST /query runs it in this process; contract 01).
# In the Docker image PYTHONPATH already holds /app/model.
_MODEL_DIR = Path(__file__).resolve().parents[2] / "model"
if _MODEL_DIR.is_dir() and str(_MODEL_DIR) not in sys.path:
    sys.path.append(str(_MODEL_DIR))
