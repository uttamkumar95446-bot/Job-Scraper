"""CSV output logic for the Job Agent."""

import csv
import os
from collections import Counter
from datetime import datetime
from pathlib import Path

from src.models import Job

#: Default directory where CSV files are written.
OUTPUT_DIR = Path(__file__).resolve().parent.parent / "output"


def write_jobs_to_csv(
    jobs: list[Job],
    output_dir: str | os.PathLike | None = None,
) -> Path:
    """Write a list of ``Job`` objects into a timestamped CSV file.

    Args:
        jobs: Collected job listings.
        output_dir: Target directory (defaults to ``output/`` at project root).

    Returns:
        ``Path`` to the created CSV file.
    """
    target_dir = Path(output_dir) if output_dir else OUTPUT_DIR
    target_dir.mkdir(parents=True, exist_ok=True)

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    filepath = target_dir / f"jobs_{timestamp}.csv"

    if not jobs:
        # Write an empty file with just the header row
        with open(filepath, "w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=Job.csv_columns())
            writer.writeheader()
        return filepath

    with open(filepath, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=Job.csv_columns())
        writer.writeheader()
        for job in jobs:
            writer.writerow(job.to_csv_row())

    return filepath


def print_summary(jobs: list[Job], filepath: Path) -> None:
    """Print a human-readable summary of the scraping run to stdout."""
    source_counts = Counter(job.source for job in jobs)

    print(f"\n{'='*55}")
    print(f"  Job Scraping Complete")
    print(f"{'='*55}")
    print(f"  Total jobs collected: {len(jobs)}")
    for source, count in sorted(source_counts.items()):
        print(f"    - {source:<12}  {count}")
    print(f"\n  Output: {filepath}")
    print(f"{'='*55}\n")
