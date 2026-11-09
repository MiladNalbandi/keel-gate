"""Fail if README.md grows past its line budget.

The README must stay a two-minute read. Detail belongs in docs/.
"""

from __future__ import annotations

import sys
from pathlib import Path

MAX_LINES = 100


def main() -> int:
    readme = Path(__file__).resolve().parent.parent / "README.md"
    count = len(readme.read_text(encoding="utf-8").splitlines())
    if count > MAX_LINES:
        print(f"README.md has {count} lines; the budget is {MAX_LINES}. Move detail to docs/.")
        return 1
    print(f"README.md: {count}/{MAX_LINES} lines")
    return 0


if __name__ == "__main__":
    sys.exit(main())
