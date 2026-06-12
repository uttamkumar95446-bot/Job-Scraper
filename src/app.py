"""Streamlit Dashboard - Job Agent.

Provides a web UI for searching jobs across Naukri, RemoteOK, and Wellfound,
viewing results in an interactive table, and exporting to CSV.

Usage:
    streamlit run src/app.py
"""

import os
import sys
from collections import Counter
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from pathlib import Path
from typing import Optional

import streamlit as st
from dotenv import load_dotenv

# --- Path setup ---
_HERE = Path(__file__).resolve().parent
_PROJECT_ROOT = _HERE.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from src.csv_writer import write_jobs_to_csv
from src.models import Job
from src.scrapers import NaukriScraper, RemoteOKScraper, WellfoundScraper
from src.scrapers.base import BaseScraper

# Load .env file (for FIRECRAWL_API_KEY and other secrets)
load_dotenv()

# --- Page config ---

st.set_page_config(
    page_title="Job Agent",
    page_icon=":briefcase:",
    layout="wide",
    initial_sidebar_state="expanded",
)

# --- Constants ---

ALL_SCRAPERS: dict[str, type[BaseScraper]] = {
    "Naukri": NaukriScraper,
    "RemoteOK": RemoteOKScraper,
    "Wellfound": WellfoundScraper,
}

SOURCE_ICONS: dict[str, str] = {
    "Naukri": ":large_blue_circle:",
    "RemoteOK": ":large_green_circle:",
    "Wellfound": ":purple_circle:",
}

OUTPUT_DIR = _PROJECT_ROOT / "output"

# --- Session state initialisation ---

for key in ("jobs", "csv_path", "search_role", "search_location", "search_sources"):
    if key not in st.session_state:
        if key == "search_sources":
            st.session_state[key] = ["Naukri", "RemoteOK", "Wellfound"]
        else:
            st.session_state[key] = None


# --- Helper functions ---


def run_scrapers(role: str, location: Optional[str], sources: list[str]) -> list[Job]:
    """Run selected scrapers in parallel and return collected jobs."""
    scrapers: list[BaseScraper] = []
    for name in sources:
        cls = ALL_SCRAPERS.get(name)
        if cls is not None:
            scrapers.append(cls())

    if not scrapers:
        return []

    all_jobs: list[Job] = []
    progress_bar = st.progress(0, text="Initialising scrapers...")
    status_text = st.empty()

    with ThreadPoolExecutor(max_workers=len(scrapers)) as executor:
        futures = {
            executor.submit(_safe_scrape, s, role, location): s
            for s in scrapers
        }
        completed = 0
        total = len(futures)
        for future in as_completed(futures):
            scraper = futures[future]
            completed += 1
            try:
                jobs = future.result()
                all_jobs.extend(jobs)
                status_text.text(
                    f":white_check_mark: {scraper.source}: {len(jobs)} jobs found "
                    f"({completed}/{total})"
                )
            except Exception as e:
                status_text.text(f":x: {scraper.source}: {e} ({completed}/{total})")
            progress_bar.progress(completed / total)

    progress_bar.empty()
    status_text.empty()
    return all_jobs


def _safe_scrape(scraper: BaseScraper, role: str, location: Optional[str]) -> list[Job]:
    """Run a single scraper with error handling."""
    try:
        return scraper.scrape(role, location)
    except NotImplementedError:
        return []
    except Exception as e:
        raise RuntimeError(f"{scraper.source} error: {e}")


def list_previous_csvs() -> list[Path]:
    """List all CSV files in the output directory, newest first."""
    if not OUTPUT_DIR.exists():
        return []
    files = sorted(OUTPUT_DIR.glob("jobs_*.csv"), reverse=True)
    return files


def format_file_size(path: Path) -> str:
    """Return a human-readable file size."""
    size = path.stat().st_size
    if size < 1024:
        return f"{size} B"
    elif size < 1024 * 1024:
        return f"{size / 1024:.1f} KB"
    else:
        return f"{size / (1024 * 1024):.1f} MB"


def read_csv_preview(path: Path, n: int = 5) -> list[dict]:
    """Read the first n rows of a CSV file."""
    import csv
    rows: list[dict] = []
    with open(path, "r", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for i, row in enumerate(reader):
            if i >= n:
                break
            rows.append(row)
    return rows


# --- Sidebar: Search controls ---

st.sidebar.title(":briefcase: Job Agent")
st.sidebar.markdown(
    "Automated job discovery across **Naukri**, **RemoteOK**, and **Wellfound**."
)

st.sidebar.divider()

st.sidebar.subheader(":mag: Search Parameters")

role = st.sidebar.text_input(
    "Job Role *",
    placeholder="e.g. Product Manager, Data Analyst",
    help="Enter the job title or role you want to search for.",
    key="role_input",
)

location = st.sidebar.text_input(
    "Location (optional)",
    placeholder="e.g. Bangalore, Mumbai, Remote",
    help="Filter jobs by location. Leave empty for all locations.",
    key="location_input",
)

st.sidebar.markdown("##### Sources")
col1, col2 = st.sidebar.columns(2)
with col1:
    use_naukri = st.checkbox("Naukri", value=True, key="cb_naukri")
    use_remoteok = st.checkbox("RemoteOK", value=True, key="cb_remoteok")
with col2:
    use_wellfound = st.checkbox("Wellfound", value=True, key="cb_wellfound")

selected_sources = []
if use_naukri:
    selected_sources.append("Naukri")
if use_remoteok:
    selected_sources.append("RemoteOK")
if use_wellfound:
    selected_sources.append("Wellfound")

run_button = st.sidebar.button(
    ":rocket: Run Search",
    type="primary",
    use_container_width=True,
    disabled=not role.strip() or not selected_sources,
)

st.sidebar.divider()

# --- Sidebar: Environment status ---

st.sidebar.subheader(":gear: Status")

firecrawl_key = os.getenv("FIRECRAWL_API_KEY")
if firecrawl_key:
    st.sidebar.success(":white_check_mark: Firecrawl API key configured")
else:
    st.sidebar.warning(":warning: FIRECRAWL_API_KEY not set --- Wellfound won't work")

st.sidebar.caption(f"Streamlit v{st.__version__}")

# --- Main area ---

st.title(":briefcase: Job Agent Dashboard")
st.markdown(
    "Search for jobs across **Naukri**, **RemoteOK**, and **Wellfound** in one place. "
    "Results are displayed below and saved to a timestamped CSV."
)

# --- Execute search ---

if run_button and role.strip() and selected_sources:
    with st.spinner("Scraping job listings - this may take a minute..."):
        jobs = run_scrapers(
            role.strip(),
            location.strip() if location.strip() else None,
            selected_sources,
        )

    st.session_state.jobs = jobs
    st.session_state.search_role = role.strip()
    st.session_state.search_location = location.strip() if location.strip() else None
    st.session_state.search_sources = selected_sources

    if jobs:
        csv_path = write_jobs_to_csv(jobs)
        st.session_state.csv_path = csv_path
        st.balloons()
    else:
        st.session_state.csv_path = None
        st.info(
            "No jobs found matching your criteria. "
            "Try a different role or expand your sources."
        )

# --- Results section ---

jobs = st.session_state.jobs

if jobs is not None:
    st.divider()

    # --- Summary cards ---
    st.subheader(":bar_chart: Summary")

    source_counts = Counter(job.source for job in jobs)

    cols = st.columns(4)
    with cols[0]:
        st.metric("Total Jobs", len(jobs))

    source_name_map = {cls.source: name for name, cls in ALL_SCRAPERS.items()}
    for i, (source_key, display_name) in enumerate(source_name_map.items(), start=1):
        if i < 4:
            count = source_counts.get(source_key, 0)
            icon = SOURCE_ICONS.get(display_name, "")
            with cols[i]:
                st.metric(f"{icon} {display_name}", count)

    # --- Chart ---
    if source_counts:
        st.subheader(":chart_with_upwards_trend: Jobs by Source")
        chart_data = {
            "Source": list(source_counts.keys()),
            "Count": list(source_counts.values()),
        }
        st.bar_chart(chart_data, x="Source", y="Count", color="Source")

    # --- Results table ---
    st.subheader
