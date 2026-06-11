"""RemoteOK scraper — uses the public JSON API.

Strategy:
    1. Hit ``https://remoteok.com/api`` with a ``User-Agent`` header.
    2. Parse the returned JSON array (first element is metadata, skip it).
    3. Filter by role keyword (case-insensitive match on ``position``).
    4. If a location is specified, client-side filter on the ``location``
       field (all RemoteOK jobs are remote by nature).
    5. Map fields to the :class:`Job` model and return.
    6. No pagination needed — the API returns all recent listings in one call.
"""

import logging
from typing import Any

import requests

from src.models import Job
from src.scrapers.base import BaseScraper

logger = logging.getLogger(__name__)

#: RemoteOK public API endpoint.
API_URL = "https://remoteok.com/api"

#: Default request headers to avoid being blocked.
HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/125.0.0.0 Safari/537.36"
    ),
    "Accept": "application/json",
}

#: Request timeout in seconds.
REQUEST_TIMEOUT_S = 15


def _normalise_location(raw: str) -> str:
    """Clean up a location string from the API."""
    loc = raw.strip()
    # RemoteOK sometimes returns "🌍 Worldwide" or "Worldwide" → "Remote"
    if not loc or loc.lower() in ("worldwide", "🌍 worldwide", "anywhere", "remote"):
        return "Remote"
    return loc


def _build_search_url(role: str) -> str:
    """Build a RemoteOK API URL with an optional role-based tag filter.

    RemoteOK's tag-based filtering uses slugified role keywords.
    We use the first meaningful word of the role as a tag hint to
    narrow results server-side before client-side filtering.
    """
    slug = role.strip().lower()
    # Use the role as a search term if it's short (single keyword)
    # for broader matching; otherwise use the first meaningful word.
    return f"{API_URL}?search={slug}"


def _matches_role_exact(job: dict[str, Any], role: str) -> bool:
    """Check if a job's ``position`` field contains the full role string."""
    position = (job.get("position") or "").lower()
    return role.lower() in position


def _matches_role_keyword(job: dict[str, Any], role_keywords: list[str]) -> bool:
    """Check if a job's ``position`` field contains any of the given keywords."""
    position = (job.get("position") or "").lower()
    return any(kw in position for kw in role_keywords)


def _extract_role_keywords(role: str) -> list[str]:
    """Extract meaningful keywords from a multi-word role for broad matching.

    Filters out very short words (under 3 chars) and common filler words like
    ``senior``, ``junior``, ``lead``, ``principal``, ``staff``.

    Examples:
        ``"Software Engineer"``       → ``["software", "engineer"]``
        ``"Senior ML Engineer"``      → ``["ml", "engineer"]``
        ``"Python Developer"``        → ``["python", "developer"]``
        ``"Data Analyst"``            → ``["data", "analyst"]``
    """
    FILLER = {"senior", "junior", "lead", "principal", "staff", "entry", "level", "mid"}
    words = role.lower().split()
    return [w for w in words if len(w) >= 3 and w not in FILLER]


# Common Indian city spelling variants for fuzzy location matching
_INDIAN_CITY_VARIANTS: dict[str, set[str]] = {
    "bangalore": {"bengaluru", "bangalore", "banglore", "bengalore"},
}


def _matches_location(job: dict[str, Any], location: str | None) -> bool:
    """Check if a job matches the requested location.

    When a specific location is requested:
      - Remote / Worldwide / Anywhere jobs are always included.
      - Jobs with an **empty location** are included (RemoteOK is a remote-job
        board; many listings omit the location field entirely).
      - Jobs whose ``location`` field matches the requested location
        (case-insensitive substring match or fuzzy variant match) are also included.

    When no location is requested, every role-matched job qualifies.
    """
    if not location:
        return True

    job_location = (job.get("location") or "").strip().lower()
    requested_lower = location.lower().strip()

    # Empty location — include it (RemoteOK is a remote-job board;
    # many listings simply omit the location field)
    if not job_location:
        return True

    # Always include remote/worldwide jobs when a location is specified
    if job_location in ("remote", "worldwide", "🌍 worldwide", "anywhere"):
        return True

    # Direct substring match
    if requested_lower in job_location or job_location in requested_lower:
        return True

    # Fuzzy match: check common city spelling variants
    # e.g. "Banglore" ↔ "Bangalore", "Bengaluru" ↔ "Bangalore"
    for _city, variants in _INDIAN_CITY_VARIANTS.items():
        if requested_lower in variants or requested_lower == _city:
            # Requested location is a variant of this city
            # Check if job location contains any variant
            for variant in variants:
                if variant in job_location:
                    return True
        if job_location in variants or job_location == _city:
            # Job location is a variant of this city
            # Check if requested location contains any variant
            for variant in variants:
                if variant in requested_lower:
                    return True

    return False


def _job_from_api(job: dict[str, Any]) -> Job | None:
    """Convert a single RemoteOK API response object into a :class:`Job`."""
    position = (job.get("position") or "").strip()
    company = (job.get("company") or "").strip()
    raw_url = (job.get("url") or "").strip()
    raw_location = (job.get("location") or "").strip()
    raw_date = (job.get("date") or "").strip()

    # Skip entries missing essential fields
    if not position or not raw_url:
        return None

    # Ensure full URL
    url = raw_url
    if url.startswith("/"):
        url = f"https://remoteok.com{url}"

    return Job(
        title=position,
        company=company,
        location=_normalise_location(raw_location),
        url=url,
        source="remoteok",
        date_posted=raw_date,
    )


class RemoteOKScraper(BaseScraper):
    """Scraper for RemoteOK job listings via the public JSON API."""

    source = "remoteok"

    def scrape(self, role: str, location: str | None = None) -> list[Job]:
        """Fetch RemoteOK job listings.

        Fetches all recent listings from the public API, then
        filters by role keyword and (optionally) location.

        Args:
            role: Job title / role keyword to search for (required).
            location: Optional location filter.

        Returns:
            A list of matching :class:`Job` objects.
        """
        if not role or not role.strip():
            raise ValueError("`role` is required for RemoteOK scraping")

        search_url = _build_search_url(role.strip())
        logger.info("RemoteOK API URL: %s", search_url)

        try:
            resp = requests.get(
                search_url,
                headers=HEADERS,
                timeout=REQUEST_TIMEOUT_S,
            )
            resp.raise_for_status()
            data: list[dict[str, Any]] = resp.json()
        except requests.RequestException as e:
            logger.error("Failed to fetch RemoteOK API: %s", e)
            raise
        except ValueError as e:
            logger.error("Failed to parse RemoteOK API response as JSON: %s", e)
            raise

        if not data:
            logger.info("RemoteOK API returned empty response")
            return []

        # The first element is always metadata (version, terms, etc.)
        # Subsequent elements are job listings.
        raw_jobs = data[1:] if len(data) > 1 else []

        # Phase 1: Try exact role substring match first
        matched: list[Job] = []
        for raw in raw_jobs:
            if not isinstance(raw, dict):
                continue

            if not _matches_role_exact(raw, role):
                continue
            if not _matches_location(raw, location):
                continue

            job = _job_from_api(raw)
            if job:
                matched.append(job)

        # Phase 2: If exact match returned 0 results, fall back to
        # individual keyword matching — RemoteOK has niche job titles
        # (e.g. "Applied AI Engineer" won't match "Software Engineer"
        # but should still be found)
        if not matched:
            keywords = _extract_role_keywords(role)
            if keywords:
                logger.info(
                    "RemoteOK: exact role match returned 0 jobs — "
                    "trying keyword fallback with %s", keywords
                )
                for raw in raw_jobs:
                    if not isinstance(raw, dict):
                        continue

                    if not _matches_role_keyword(raw, keywords):
                        continue
                    if not _matches_location(raw, location):
                        continue

                    job = _job_from_api(raw)
                    if job:
                        matched.append(job)

        logger.info(
            "RemoteOK: %d jobs fetched, %d matched role='%s' location='%s'",
            len(raw_jobs),
            len(matched),
            role,
            location or "(any)",
        )
        return matched
