"""Backward-compatible entrypoint; prefer ``scripts/smoke_p0.py``. """

from __future__ import annotations

import sys
from pathlib import Path

# Allow `python scripts/smoke_p0_w2.py` without installing as a package.
sys.path.insert(0, str(Path(__file__).resolve().parent))

from smoke_p0 import main  # noqa: E402

if __name__ == "__main__":
    raise SystemExit(main())
