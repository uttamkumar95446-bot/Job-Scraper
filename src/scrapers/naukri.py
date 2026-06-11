"""Naukri.com scraper — uses undetected-chromedriver + BeautifulSoup.

The site uses heavy JavaScript rendering, so we drive a real (undetected)
Chrome via Selenium, then parse the rendered HTML with BeautifulSoup.
"""

import logging
import re
import time

from bs4 import BeautifulSoup
from bs4.element import Tag
import undetected_chromedriver as uc
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as ec

from src.models import Job
from src.scrapers.base import BaseScraper

logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO, format="%(levelname)s  %(message)s")

# Number of pages to scrape (first N pages).
MAX_PAGES = 3

# Delay between page loads (seconds) to be polite.
PAGE_DELAY_S = 2.0

# ── Selectors (discovered via live inspection) ──────────────────────────
# These are relatively stable class names on Naukri's current markup.
CARD_SELECTOR = "div.srp-jobtuple-wrapper"
TITLE_SELECTOR = "div.row1 a"
COMPANY_SELECTOR = "span.comp-dtls-wrap a.comp-name"
LOCATION_SELECTOR = "span[class*='loc']"
DATE_SELECTOR = "span.job-post-day"


def _role_to_slug(role: str) -> str:
    """Convert a job role into the hyphenated slug Naukri expects.

    Examples:
        "Software Engineer" -> "software-engineer"
        "Product Manager"   -> "product-manager"
        "C++ Developer"     -> "c-developer"
    """
    # Lowercase, strip special chars that break URLs, collapse whitespace
    slug = role.lower().strip()
    slug = re.sub(r"[^a-z0-9\s-]", "", slug)  # remove special chars
    slug = re.sub(r"[\s-]+", "-", slug)         # spaces/hyphens → single hyphen
    return slug.strip("-")


def _build_search_url(role: str, location: str | None = None) -> str:
    """Build the Naukri search URL for a role and optional location."""
    slug = _role_to_slug(role)
    if location:
        loc_slug = "-".join(location.lower().split())
        return f"https://www.naukri.com/{slug}-jobs-in-{loc_slug}"
    return f"https://www.naukri.com/{slug}-jobs"


def _build_page_url(base_url: str, page: int) -> str:
    """Append the Naukri page suffix (page 1 has no suffix)."""
    if page <= 1:
        return base_url
    return f"{base_url}-{page}"


def _parse_jobs_from_html(html: str) -> list[Job]:
    """Parse job listings from the rendered HTML of a Naukri page."""
    soup = BeautifulSoup(html, "html.parser")
    cards = soup.select(CARD_SELECTOR)
    jobs: list[Job] = []

    for card in cards:
        try:
            job = _extract_job_from_card(card)
            if job:
                jobs.append(job)
        except Exception:
            logger.warning("Skipping a malformed job card", exc_info=True)

    return jobs


def _extract_job_from_card(card: Tag) -> Job | None:
    """Extract a single ``Job`` from a BeautifulSoup job-card element."""
    # ── Title + URL ─────────────────────────────────────────────────
    title_tag = card.select_one(TITLE_SELECTOR)
    if not title_tag:
        return None

    title = title_tag.get_text(strip=True)
    raw_url = title_tag.get("href", "")
    # Ensure it's a string (BeautifulSoup may return a list)
    url = str(raw_url) if raw_url else ""
    # Relative → absolute
    if url.startswith("/"):
        url = f"https://www.naukri.com{url}"

    if not title or not url:
        return None

    # ── Company ─────────────────────────────────────────────────────
    company_tag = card.select_one(COMPANY_SELECTOR)
    company = company_tag.get_text(strip=True) if company_tag else ""

    # ── Location ────────────────────────────────────────────────────
    loc_tag = card.select_one(LOCATION_SELECTOR)
    location = loc_tag.get_text(strip=True) if loc_tag else ""

    # ── Date posted ─────────────────────────────────────────────────
    date_tag = card.select_one(DATE_SELECTOR)
    date_posted = date_tag.get_text(strip=True) if date_tag else ""

    # ── Build & return ──────────────────────────────────────────────
    return Job(
        title=title,
        company=company,
        location=location,
        url=url,
        source="naukri",
        date_posted=date_posted,
    )


class NaukriScraper(BaseScraper):
    """Scraper for Naukri.com job listings."""

    source = "naukri"

    def scrape(self, role: str, location: str | None = None) -> list[Job]:
        """Fetch Naukri job listings.

        Uses ``undetected-chromedriver`` to render the JS-heavy page, then
        parses the HTML with BeautifulSoup.  Scrapes the first
        ``MAX_PAGES`` (default 3) search-result pages.
        """
        if not role or not role.strip():
            raise ValueError("`role` is required for Naukri scraping")

        base_url = _build_search_url(role.strip(), location)
        logger.info("Naukri base URL: %s", base_url)

        driver: uc.Chrome | None = None
        all_jobs: list[Job] = []

        try:
            driver = uc.Chrome()
            driver.set_window_size(1280, 900)

            for page_num in range(1, MAX_PAGES + 1):
                page_url = _build_page_url(base_url, page_num)
                logger.info("Fetching page %d: %s", page_num, page_url)

                try:
                    driver.get(page_url)
                    # Wait for job cards to appear
                    WebDriverWait(driver, 15).until(
                        ec.presence_of_element_located((By.CSS_SELECTOR, CARD_SELECTOR))
                    )
                    # Give a tiny extra moment for dynamic content
                    time.sleep(1.5)
                except Exception:
                    logger.warning(
                        "Timed out waiting for job cards on page %d", page_num
                    )
                    # If page 1 fails, there's nothing more to do
                    if page_num == 1:
                        raise
                    break

                html = driver.page_source
                page_jobs = _parse_jobs_from_html(html)
                logger.info("  → %d jobs from page %d", len(page_jobs), page_num)
                all_jobs.extend(page_jobs)

                # Polite delay before next page (skip after last page)
                if page_num < MAX_PAGES:
                    time.sleep(PAGE_DELAY_S)

        except Exception:
            logger.exception("Naukri scraping failed")
            raise
        finally:
            if driver is not None:
                try:
                    driver.quit()
                except Exception:
                    logger.warning("Failed to quit Chrome driver cleanly")
                # Prevent __del__ from calling quit() again on garbage collection
                driver = None

        return all_jobs
