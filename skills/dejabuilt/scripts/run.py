"""Entry point: `python run.py <search|inspect|verdict> ...`.

Works from any working directory and needs nothing beyond Python 3.10.
"""

from __future__ import annotations

import sys
from pathlib import Path

if sys.version_info < (3, 10):  # noqa: UP036 - this guard is the point
    sys.exit("dejabuilt needs Python 3.10 or newer")

sys.path.insert(0, str(Path(__file__).resolve().parent))

from dejabuilt.cli import main

if __name__ == "__main__":
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="replace")
    sys.exit(main())
