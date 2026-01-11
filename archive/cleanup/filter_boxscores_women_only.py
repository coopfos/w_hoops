#!/usr/bin/env python3
"""
Remove raw boxscore CSV files whose filename does NOT contain '_w_'.
"""

import argparse
import csv
import os
from pathlib import Path


def should_delete(path: Path) -> bool:
    return path.suffix.lower() == ".csv" and "_w_" not in path.name


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Delete raw boxscore CSV files whose filename does NOT contain '_w_'."
    )
    parser.add_argument(
        "root",
        nargs="?",
        default="2025/box scores raw",
        help="Directory to scan (default: ../2025/box scores raw).",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print files that would be deleted without deleting.",
    )

    args = parser.parse_args()
    root = Path(args.root).resolve()
    if not root.exists():
        raise SystemExit(f"Root directory not found: {root}")

    csv_files = list(root.rglob("*.csv"))
    if not csv_files:
        print(f"No CSV files found under {root}.")
        return

    for path in csv_files:
        if should_delete(path):
            if args.dry_run:
                print(f"DELETE {path}")
            else:
                os.remove(path)
                print(f"DELETED {path}")


if __name__ == "__main__":
    main()
