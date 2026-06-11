"""Wellfound (AngelList) scraper — uses Firecrawl SDK.

Strategy:
    1. Load ``FIRECRAWL_API_KEY`` from environment.
    2. Construct the correct Wellfound search URL:
       - In-person/any:  ``wellfound.com/role/<role>``
       - Remote:         ``wellfound.com/role/r/<role>``
    3. Use Firecrawl's ``scrape_url`` to get the rendered page HTML.
    4. Parse the rendered HTML directly with BeautifulSoup
       (Wellfound server-renders job cards as visible HTML).
    5. Map to :class:`Job` model and return.
    6. Client-side filter by location if requested.
"""

import logging
import os
import re
import time

from bs4 import BeautifulSoup, Tag

from src.models import Job
from src.scrapers.base import BaseScraper

logger = logging.getLogger(__name__)

# ── URL templates ────────────────────────────────────────────────────────
# Wellfound URL patterns (discovered via live inspection):
#   /role/<slug>       — all jobs for a role (in-person + remote)
#   /role/r/<slug>     — remote-only jobs for a role

WELLFOUND_URL = "https://wellfound.com/role/{role_slug}"
WELLFOUND_REMOTE_URL = "https://wellfound.com/role/r/{role_slug}"
WELLFOUND_LOCATION_URL = "https://wellfound.com/role/l/{role_slug}/{location_slug}"

# ── Slug helpers ─────────────────────────────────────────────────────────


def _to_wellfound_slug(text: str) -> str:
    """Convert text into a hyphenated Wellfound-compatible slug."""
    slug = text.lower().strip()
    slug = re.sub(r"[^a-z0-9\s-]", "", slug)
    slug = re.sub(r"[\s-]+", "-", slug)
    return slug.strip("-")


# ── URL construction ─────────────────────────────────────────────────────


# ── Location slug helpers ───────────────────────────────────────────────
# Wellfound supports location-specific URLs like:
#   /role/l/<role>/<location>  — e.g. /role/l/software-engineer/bangalore
# We map common Indian city variants to the slug Wellfound recognises.

# Mapping from user-typed location → best Wellfound slug for India
_INDIAN_CITY_MAP: dict[str, str] = {
    "bengaluru": "bangalore",
    "banglore": "bangalore",
    "bengalore": "bangalore",
    "bangalore": "bangalore",
}


def _to_location_slug(location: str) -> str:
    """Convert a location string into a Wellfound-compatible URL slug.

    Handles common Indian city variants (e.g. "Banglore" → "bangalore").
    """
    slug = _to_wellfound_slug(location)
    return _INDIAN_CITY_MAP.get(slug, slug)


def _build_search_url(role: str, location: str | None = None) -> str:
    """Build a Wellfound search URL for the given role and optional location.

    When a location is provided, uses the location-scoped URL pattern
    (/role/l/<role>/<location>) to only fetch jobs in that location.
    Falls back to the generic role URL if no location is given.
    """
    role_slug = _to_wellfound_slug(role)
    if location:
        location_slug = _to_location_slug(location)
        return WELLFOUND_LOCATION_URL.format(
            role_slug=role_slug, location_slug=location_slug
        )
    return WELLFOUND_URL.format(role_slug=role_slug)


def _build_remote_search_url(role: str) -> str:
    """Build a Wellfound search URL scoped to remote jobs."""
    role_slug = _to_wellfound_slug(role)
    return WELLFOUND_REMOTE_URL.format(role_slug=role_slug)


# ── HTML parsing ─────────────────────────────────────────────────────────

# Job cards are rendered as server-side HTML by Next.js.
# Each card has this approximate structure:
#
# <div class="mb-6 w-full rounded border border-gray-400 bg-white">   ← CARD
#   <div class="flex w-full" data-testid="startup-header">            ← COMPANY
#     <a href="/company/{slug}"><h2>Company Name</h2></a>
#   </div>
#   <div class="mb-4 w-full px-4">                                    ← JOB
#     <a class="...text-brand-burgandy..." href="/jobs/{id}-{slug}">
#       Job Title
#     </a>
#     <span class="...rounded-lg...">Full-time</span>
#     <span class="pl-1 text-xs">$salary or Location</span>           ← salary OR location
#     <span class="text-xs lowercase text-dark-a">3 days ago</span>
#   </div>
#   ... (multiple job listings per company card)
# </div>

CARD_SELECTOR = "div.mb-6.w-full.rounded.border.border-gray-400.bg-white"
COMPANY_NAME_SELECTOR = "h2.inline.text-md.font-semibold"
COMPANY_LINK_SELECTOR = "a[href*='/company/']"
JOB_TITLE_SELECTOR = "a[href*='/jobs/']"
JOB_TYPE_SELECTOR = "span.whitespace-nowrap.rounded-lg"
JOB_DETAIL_SELECTOR = "span.pl-1.text-xs"
JOB_DATE_SELECTOR = "span.text-xs.lowercase"


def _parse_jobs_from_html(html: str) -> list[dict]:
    """Parse job listings from the server-rendered Wellfound HTML.

    Returns a list of raw dicts with keys:
        title, company, location, url, date_posted
    """
    soup = BeautifulSoup(html, "html.parser")
    cards = soup.select(CARD_SELECTOR)

    if not cards:
        logger.info("No job cards found in Wellfound HTML")
        return []

    raw_jobs: list[dict] = []

    for card in cards:
        try:
            jobs_from_card = _extract_jobs_from_card(card)
            raw_jobs.extend(jobs_from_card)
        except Exception:
            logger.debug("Skipping malformed job card", exc_info=True)

    return raw_jobs


def _extract_jobs_from_card(card: Tag) -> list[dict]:
    """Extract job listings from a single company card.

    A company card contains a company header plus one or more job listings.
    """
    # ── Company name ────────────────────────────────────────────────
    company_name = ""
    company_h2 = card.select_one(COMPANY_NAME_SELECTOR)
    if company_h2:
        company_name = company_h2.get_text(strip=True)

    # ── Company URL (for reference) ─────────────────────────────────
    company_link = card.select_one(COMPANY_LINK_SELECTOR)
    company_url = ""
    if company_link:
        company_url = company_link.get("href", "")

    # ── Find all job listing containers within this card ────────────
    # Each job listing is inside a div.mb-4.w-full.px-4 within the card
    job_containers = card.select("div.mb-4.w-full.px-4")

    results: list[dict] = []
    for container in job_containers:
        try:
            job = _extract_job_from_container(container, company_name)
            if job:
                results.append(job)
        except Exception:
            logger.debug("Skipping malformed job container", exc_info=True)

    return results


def _extract_job_from_container(container: Tag, company_name: str) -> dict | None:
    """Extract a single job listing from its container div."""
    # ── Title + URL ─────────────────────────────────────────────────
    title_link = container.select_one(JOB_TITLE_SELECTOR)
    if not title_link:
        return None

    title = title_link.get_text(strip=True)
    raw_url = title_link.get("href", "")
    url = str(raw_url) if raw_url else ""

    if not title or not url:
        return None

    # Ensure full URL
    if url.startswith("/"):
        url = f"https://wellfound.com{url}"

    # ── Job type (Full-time / Part-time / Contract) ─────────────────
    type_tag = container.select_one(JOB_TYPE_SELECTOR)
    job_type = type_tag.get_text(strip=True) if type_tag else ""

    # ── Details: salary, location, experience level, etc. ──────────
    # The <span class="pl-1 text-xs"> elements contain salary, location,
    # OR experience level ("2 years of exp"). We need to skip the
    # experience spans so they don't overwrite the actual location.
    detail_spans = container.select(JOB_DETAIL_SELECTOR)
    salary = ""
    location = ""

    for span in detail_spans:
        text = span.get_text(strip=True)
        if not text:
            continue
        # Salary indicators: starts with $, contains "k" or "K"
        if text.startswith("$") or ("k" in text.lower() and "$" in text):
            salary = text
        elif _is_experience_text(text):
            # Skip experience/seniority text (e.g. "2 years of exp")
            continue
        else:
            location = text

    # ── Date posted ─────────────────────────────────────────────────
    date_tag = container.select_one(JOB_DATE_SELECTOR)
    date_posted = date_tag.get_text(strip=True) if date_tag else ""

    # ── Normalise location ─────────────────────────────────────────
    if not location:
        location = "Remote"
    else:
        # Strip location-description prefixes like:
        #   "In office • San Francisco"    → "San Francisco"
        #   "Onsite or remote • India"    → "India"
        #   "Remote only • Canada"        → "Remote only • Canada" (keep "Remote" for matching)
        #   "Remote – New York"           → "Remote – New York"  (keep "Remote" for matching)
        # Only strip "In office", "Onsite or remote" prefixes — NOT "Remote"
        location = re.sub(
            r"^(?:In\s+office\s*|Onsite\s+(?:or\s+)?remote\s*)[–•-]\s*",
            "", location
        ).strip()

    return {
        "title": title,
        "company": company_name,
        "location": location,
        "url": url,
        "date_posted": date_posted,
    }


# ── Location matching ────────────────────────────────────────────────────


def _matches_location(job_location: str, requested: str | None) -> bool:
    """Check if a job's location matches the requested location.

    Handles common location patterns:
    - "San Francisco" matches "san francisco"
    - "Bengaluru" matches "bangalore" (fuzzy)
    - Empty requested location matches everything
    """
    if not requested:
        return True

    requested_lower = requested.lower().strip()
    job_location_lower = job_location.lower().strip()

    # Direct substring match
    if requested_lower in job_location_lower:
        return True
    if job_location_lower in requested_lower:
        return True

    # Fuzzy: "Bengaluru" ↔ "Bangalore" (and common misspellings)
    # Also match compound names like "Bangalore Urban" which contain
    # a Bangalore variant as a substring.
    bengaluru_variants = {"bengaluru", "bangalore", "banglore", "bengalore"}
    if requested_lower in bengaluru_variants:
        # Job location contains "bangalore" etc (e.g. "Bangalore Urban")
        for variant in bengaluru_variants:
            if variant in job_location_lower:
                return True
    if job_location_lower in bengaluru_variants:
        # Requested location contains "bangalore" etc (even if misspelled)
        for variant in bengaluru_variants:
            if variant in requested_lower:
                return True

    # Remote jobs are NOT matched when a specific city is requested.
    # If the user wants remote jobs, they should search without a location.
    return False


# ── Location normalisation ───────────────────────────────────────────────


# ── Experience detection ────────────────────────────────────────────────
# Wellfound shows experience levels like "2 years of exp" in the same
# detail spans as salary and location. We need to skip these.

_EXP_PATTERN = re.compile(
    r"\d+\s*(year|yr|month)s?\s*(of\s+)?exp(erience)?",
    re.IGNORECASE,
)


def _is_experience_text(text: str) -> bool:
    """Check if text is an experience/seniority indicator (not a location)."""
    return bool(_EXP_PATTERN.search(text))


# ── Location normalisation ───────────────────────────────────────────────


def _normalise_location(location: str) -> str:
    """Clean up a location string."""
    loc = location.strip()
    if not loc or loc.lower() in ("remote", "anywhere", "worldwide", "🌍 worldwide"):
        return "Remote"
    # If location starts with "Remote" prefix, normalise to "Remote"
    loc_lower = loc.lower()
    if loc_lower.startswith("remote") or "remote" in loc_lower:
        return "Remote"
    return loc


# ── Scraper class ────────────────────────────────────────────────────────


class WellfoundScraper(BaseScraper):
    """Scraper for Wellfound (AngelList Talent) job listings.

    Uses the Firecrawl SDK to render the JS-heavy page and extracts
    job data from the server-rendered HTML via BeautifulSoup.
    """

    source = "wellfound"

    def scrape(self, role: str, location: str | None = None) -> list[Job]:
        """Fetch Wellfound job listings via Firecrawl.

        Args:
            role: Job title / role keyword to search for (required).
            location: Optional location filter (applied client-side).

        Returns:
            A list of matching :class:`Job` objects.
        """
        if not role or not role.strip():
            raise ValueError("`role` is required for Wellfound scraping")

        api_key = os.getenv("FIRECRAWL_API_KEY")
        if not api_key:
            raise RuntimeError(
                "FIRECRAWL_API_KEY is not set. "
                "Add it to your .env file or set the FIRECRAWL_API_KEY "
                "environment variable."
            )

        # ── Firecrawl SDK ────────────────────────────────────────────
        try:
            from firecrawl import FirecrawlApp
        except ImportError:
            raise ImportError(
                "firecrawl-py is not installed. "
                "Run: pip install firecrawl-py"
            )

        app = FirecrawlApp(api_key=api_key)

        # ── Try URLs in priority order ──────────────────────────────
        # 1. Location-specific: wellfound.com/role/l/<role>/<city> (if location given)
        # 2. General:           wellfound.com/role/<role>
        # 3. Remote:            wellfound.com/role/r/<role> (fallback)
        base_urls_to_try: list[str] = []
        if location:
            base_urls_to_try.append(_build_search_url(role.strip(), location))
        base_urls_to_try.append(_build_search_url(role.strip()))
        base_urls_to_try.append(_build_remote_search_url(role.strip()))

        all_raw_jobs: list[dict] = []
        seen_urls: set[str] = set()
        MAX_PAGES = 3  # search up to 3 pages per URL
        # Firecrawl scrape timeout in milliseconds (60s for the page load + buffer for HTTP)
        FC_TIMEOUT_MS = 60_000
        # Polite delay between pages (seconds)
        PAGE_DELAY_S = 1.0

        for base_url in base_urls_to_try:
            logger.info("Calling Firecrawl scrape_url for: %s", base_url)

            consecutive_empty_pages = 0
            page = 1
            while page <= MAX_PAGES:
                url = f"{base_url}?page={page}" if page > 1 else base_url

                try:
                    result = app.scrape_url(
                        url,
                        params={
                            "formats": ["html"],
                            "timeout": FC_TIMEOUT_MS,
                        },
                    )
                except Exception as e:
                    logger.error("Firecrawl request failed for %s: %s", url, e)
                    break

                # ── Extract HTML ────────────────────────────────────
                html = ""
                if isinstance(result, dict):
                    html = result.get("html", "")
                    if not html and "data" in result and isinstance(result["data"], dict):
                        html = result["data"].get("html", "")

                if not html:
                    logger.info("Firecrawl returned no HTML content for: %s", url)
                    break

                # ── Parse ───────────────────────────────────────────
                raw_jobs = _parse_jobs_from_html(html)

                # No jobs at all in the HTML → stop paginating this URL
                if not raw_jobs:
                    logger.info("No jobs found on page %d for %s — stopping pagination", page, base_url)
                    break

                # Deduplicate by URL
                new_count = 0
                for j in raw_jobs:
                    if j["url"] not in seen_urls:
                        seen_urls.add(j["url"])
                        all_raw_jobs.append(j)
                        new_count += 1

                logger.info(
                    "Wellfound page %d: %d jobs (%d new)",
                    page, len(raw_jobs), new_count
                )

                # No *new* jobs on this page — likely hit the end of unique listings
                if new_count == 0:
                    consecutive_empty_pages += 1
                    if consecutive_empty_pages >= 2:
                        logger.info(
                            "No new jobs for %d consecutive pages at %s — stopping pagination",
                            consecutive_empty_pages, base_url
                        )
                        break
                else:
                    consecutive_empty_pages = 0

                # Polite delay before next page
                time.sleep(PAGE_DELAY_S)

                page += 1

            # Continue to next base URL even if we got jobs —
            # dedup will prevent duplicates, and the general/remote
            # URLs may have additional role-matched jobs for the
            # client-side location filter to catch.
            logger.info(
                "Wellfound: %d unique jobs collected so far after %s",
                len(all_raw_jobs), base_url
            )

        # ── Client-side location filter ─────────────────────────────
        if location:
            filtered = [
                j for j in all_raw_jobs
                if _matches_location(j["location"], location)
            ]
            logger.info(
                "Wellfound: %d/%d jobs match location='%s'",
                len(filtered),
                len(all_raw_jobs),
                location,
            )
            all_raw_jobs = filtered

        # ── Map to Job model ────────────────────────────────────────
        jobs = []
        for raw in all_raw_jobs:
            jobs.append(Job(
                title=raw["title"],
                company=raw["company"],
                location=_normalise_location(raw["location"]),
                url=raw["url"],
                source="wellfound",
                date_posted=raw["date_posted"],
            ))

        logger.info(
            "Wellfound: %d total jobs for role='%s' location='%s'",
            len(jobs),
            role,
            location or "(any)",
        )
        return jobs
