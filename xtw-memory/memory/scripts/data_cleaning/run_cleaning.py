#!/usr/bin/env python3
"""Main entry point for running the xtw-memory chat cleaning pipeline."""

import sys
from pathlib import Path

# Add project root to sys.path
SCRIPT_DIR = Path(__file__).resolve().parent
PROJECT_DIR = SCRIPT_DIR.parents[2]  # bot/projects
if str(PROJECT_DIR) not in sys.path:
    sys.path.insert(0, str(PROJECT_DIR))

from memory.scripts.data_cleaning.pipeline import CleaningPipeline


def main():
    raw_dir = PROJECT_DIR / "memory" / "raw massage"
    output_base = PROJECT_DIR / "memory"

    pipeline = CleaningPipeline(raw_dir=str(raw_dir), output_base=str(output_base))
    manifest = pipeline.run()

    print("\n--- Cleaning Summary ---")
    print(f"Dataset Version:  {manifest['dataset_version']}")
    print(f"Raw Records:      {manifest['raw_record_count']:,}")
    print(f"Clean Records:    {manifest['clean_record_count']:,} ({manifest['retention_rate']*100:.2f}%)")
    print(f"Removed Records:  {manifest['removed_count']:,}")
    print(f"Flagged Records:  {manifest['flagged_count']:,}")
    print(f"Conversations:    {manifest['conversation_count']}")
    print(f"Participants:     {manifest['participant_count']:,}")
    print(f"Time Range:       {manifest['timestamp_min']} -> {manifest['timestamp_max']}")


if __name__ == "__main__":
    main()
