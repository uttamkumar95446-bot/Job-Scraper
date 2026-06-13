"""Job Agent -- CLI entry-point.

Usage:
    python src.main "Product Manager roles in Bangalore" --sources naukri
    python src.main "Python Developer jobs in Mumbai" --sources naukri,remoteok
    python src.main "Data Analyst"
    python src.main --role "Software Engineer" --location "Remote"
"""

import argparse
import re
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed

from dotenv import load_dotenv

from src.csv_writer import write_jobs_to_csv, print_summary
from src.models import Job
from src.scrapers.naukri import NaukriScraper
from src.scrapers.remoteok import RemoteOKScraper
from src.scrapers.wellfound import WellfoundScraper
from src.scrapers.base import BaseScraper

# Registry of all available scrapers
ALL_SCRAPERS: dict[str, type[BaseScraper]] = {
    "naukri": NaukriScraper,
    "remoteok": RemoteOKScraper,
    "wellfound": WellfoundScraper,
}

# ── Natural-language query parser ────────────────────────────────────────

def parse_query(query: str) -> tuple[str, str | None]:
    """Extract ``(role, location)`` from a natural-language search query.

    Examples:
        ``"Find product manager roles in Bangalore"``  → ``("product manager", "Bangalore")``
        ``"Python Developer jobs in Mumbai"``           → ``("Python Developer", "Mumbai")``
        ``"Data Analyst"``                               → ``("Data Analyst", None)``
        ``"software engineer"``                          → ``("software engineer", None)``
    """
    text = query.strip()
    if not text:
        return ("", None)

    # 1. Strip common leading filler phrases (case-insensitive)
    leading_pattern = re.compile(
        r"^(find\s+(?:me\s+)?|search\s+(?:for\s+)?|look\s+(?:ing\s+)?(?:for\s+)?"
        r"|show\s+(?:me\s+)?|get\s+(?:me\s+)?|i\s+want\s+(?:a\s+|an\s+|the\s+)?"
        r"|i\s+am\s+looking\s+(?:for\s+)?|need\s+(?:a\s+|an\s+)?)",
        re.IGNORECASE,
    )
    text = leading_pattern.sub("", text).strip()

    # 2. Strip trailing filler words (case-insensitive)
    trailing_pattern = re.compile(
        r"\s+(?:jobs?|positions|roles?|openings|listings|vacancies|opportunities)\s*$",
        re.IGNORECASE,
    )
    text = trailing_pattern.sub("", text).strip()

    # 3. Detect location keyword: " in <Location>", " at <Location>", " near <Location>"
    location_match = re.search(
        r"\s+(?:in|at|near|around)\s+(.+)$",
        text,
        re.IGNORECASE,
    )
    if location_match:
        location = location_match.group(1).strip()
        role = text[: location_match.start()].strip()
        # Further clean trailing filler words from role portion
        role = trailing_pattern.sub("", role).strip()
        return (role if role else text, location)

    # No location detected -- entire cleaned string is the role
    return (text, None)


# ── Argument parsing ─────────────────────────────────────────────────────

def _preprocess_argv(argv: list[str] | None) -> list[str] | None:
    """Pre-process argv to convert bare ``sources`` keyword to ``--sources``.

    Supports the user's preferred shorthand:
        ``python src.main "Data Analyst" sources naukri``
    without requiring a ``--`` prefix on ``sources``.
    """
    if argv is None:
        return None

    processed: list[str] = []
    i = 0
    while i < len(argv):
        if argv[i] == "sources" and i + 1 < len(argv):
            # Check it's not already a flag-like argument
            if not argv[i].startswith("-"):
                processed.append("--sources")
                i += 1
                continue
        processed.append(argv[i])
        i += 1
    return processed


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Automated job listing aggregator for Naukri, RemoteOK & Wellfound.",
    )

    # Positional query string (natural language)
    parser.add_argument(
        "query",
        nargs="?",
        default=None,
        help=(
            "Natural-language search query. "
            'Examples: "Data Analyst", "Product Manager roles in Bangalore".'
        ),
    )

    # Explicit overrides (take precedence over parsed query)
    parser.add_argument(
        "--role",
        default=None,
        help="Job title / role to search for (overrides parsed query).",
    )
    parser.add_argument(
        "--location",
        "-loc",
        default=None,
        help="Optional location filter (overrides parsed query).",
    )
    parser.add_argument(
        "--sources",
        "-sources",
        "-s",
        default="all",
        help=(
            "Comma-separated list of sources to query. "
            "Options: naukri,remoteok,wellfound. Default: all."
        ),
    )

    return parser.parse_args(argv)


def resolve_scrapers(sources_arg: str) -> list[BaseScraper]:
    """Parse the ``--sources`` flag into a list of scraper instances."""
    if sources_arg == "all":
        names = list(ALL_SCRAPERS.keys())
    else:
        names = [s.strip().lower() for s in sources_arg.split(",") if s.strip()]

    scrapers: list[BaseScraper] = []
    for name in names:
        cls = ALL_SCRAPERS.get(name)
        if cls is None:
            print(f"[!] Unknown source '{name}' -- skipping. Valid: {list(ALL_SCRAPERS.keys())}")
            continue
        scrapers.append(cls())
    return scrapers


def run_scraper(scraper: BaseScraper, role: str, location: str | None) -> list[Job]:
    """Run a single scraper and return its results (with error handling)."""
    try:
        print(f"  [~] Scraping {scraper.source}... ", end="", flush=True)
        jobs = scraper.scrape(role, location)
        print(f"{len(jobs)} jobs found")
        return jobs
    except NotImplementedError:
        print(f"[!] {scraper.source} scraper not yet implemented -- skipping")
        return []
    except Exception as e:
        print(f"[X] Error scraping {scraper.source}: {e}")
        return []


def main(argv: list[str] | None = None) -> None:
    # Load .env file (for FIRECRAWL_API_KEY and other secrets)
    load_dotenv()

    argv = _preprocess_argv(argv)
    args = parse_args(argv)

    # ── Resolve role & location ──────────────────────────────────────
    role: str | None = None
    location: str | None = None

    if args.query:
        # Parse natural-language query
        role, location = parse_query(args.query)

    # Explicit flags take precedence over parsed values
    if args.role:
        role = args.role
    if args.location:
        location = args.location

    if not role:
        print("[X] No role specified. Provide a query or use --role.")
        print("    Usage: python src.main \"Product Manager roles in Bangalore\"")
        sys.exit(1)

    # ── Resolve scrapers & run ───────────────────────────────────────
    scrapers = resolve_scrapers(args.sources)

    if not scrapers:
        print("[X] No valid scrapers selected. Exiting.")
        sys.exit(1)

    print(f"\n>>> Job Agent -- Searching for '{role}'")
    if location:
        print(f">>> Location: {location}")
    print(f">>> Sources: {', '.join(s.source for s in scrapers)}\n")

    all_jobs: list[Job] = []

    # Run scrapers in parallel for speed
    with ThreadPoolExecutor(max_workers=len(scrapers)) as executor:
        futures = {
            executor.submit(run_scraper, s, role, location): s
            for s in scrapers
        }
        for future in as_completed(futures):
            all_jobs.extend(future.result())

    filepath = write_jobs_to_csv(all_jobs)
    print_summary(all_jobs, filepath)


if __name__ == "__main__":
    main()
