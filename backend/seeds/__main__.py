"""`python -m seeds` entry point — see `seeds.cli` for the commands."""

from __future__ import annotations

import sys

from seeds.cli import main

if __name__ == "__main__":
    sys.exit(main())
