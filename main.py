"""Service Assembly Studio — assemble church service videos for YouTube."""

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.ui.main_window import run_app


def main() -> None:
    run_app()


if __name__ == "__main__":
    main()
