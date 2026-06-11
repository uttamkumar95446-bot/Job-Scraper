"""Unit tests for the Wellfound scraper — HTML parsing logic.

Tests the internal parsing functions (``_parse_jobs_from_html``,
``_matches_location``, ``_build_search_url``, etc.) without
needing a Firecrawl API key.
"""

import json
from pathlib import Path

import pytest

from src.scrapers.wellfound import (
    _build_remote_search_url,
    _build_search_url,
    _matches_location,
    _normalise_location,
    _parse_jobs_from_html,
    _to_wellfound_slug,
)

# ── Fixture helpers ─────────────────────────────────────────────────────

FIXTURES = Path(__file__).resolve().parent / "fixtures"


def _load_html_fixture(name: str) -> str:
    return (FIXTURES / name).read_text(encoding="utf-8")


# ── Sample HTML for parser tests ────────────────────────────────────────

SAMPLE_HTML = """<!DOCTYPE html>
<html lang="en">
<body>
<div class="mb-6 w-full rounded border border-gray-400 bg-white">
  <div class="w-full space-y-2 px-4 pb-2 pt-4">
    <div class="flex-col">
      <div class="flex w-full" data-testid="startup-header">
        <a href="https://wellfound.com/company/acme-corp">
          <h2 class="inline text-md font-semibold">Acme Corp</h2>
        </a>
        <span class="text-xs text-neutral-1000">Making things</span>
        <span class="text-xs italic text-neutral-500">51-200 Employees</span>
      </div>
    </div>
  </div>
  <div class="mb-4 w-full px-4">
    <div class="min-h-[50px] items-end justify-between rounded-2xl px-2 py-2 sm:flex">
      <div class="w-full pb-1 sm:pb-0">
        <div class="mb-1 flex items-start">
          <a class="mr-2 text-sm font-semibold text-brand-burgandy hover:underline"
             href="https://wellfound.com/jobs/123-data-analyst">Data Analyst</a>
          <span class="whitespace-nowrap rounded-lg bg-accent-yellow-100 px-2 py-1 text-[10px] font-semibold text-neutral-800">Full-time</span>
        </div>
        <div class="sm:flex sm:space-x-2">
          <div class="flex items-center text-neutral-500">
            <span class="pl-1 text-xs">$90k - $120k</span>
          </div>
        </div>
        <span class="text-xs lowercase text-dark-a md:hidden">3 days ago</span>
      </div>
    </div>
  </div>
  <div class="mb-4 w-full px-4">
    <div class="min-h-[50px] items-end justify-between rounded-2xl px-2 py-2 sm:flex">
      <div class="w-full pb-1 sm:pb-0">
        <div class="mb-1 flex items-start">
          <a class="mr-2 text-sm font-semibold text-brand-burgandy hover:underline"
             href="https://wellfound.com/jobs/456-senior-engineer">Senior Engineer</a>
          <span class="whitespace-nowrap rounded-lg bg-accent-yellow-100 px-2 py-1 text-[10px] font-semibold text-neutral-800">Full-time</span>
        </div>
        <div class="sm:flex sm:space-x-2">
          <div class="flex items-center text-neutral-500">
            <span class="pl-1 text-xs">In office - Bengaluru</span>
          </div>
        </div>
        <span class="text-xs lowercase text-dark-a md:hidden">1 week ago</span>
      </div>
    </div>
  </div>
</div>
<div class="mb-6 w-full rounded border border-gray-400 bg-white">
  <div class="w-full space-y-2 px-4 pb-2 pt-4">
    <div class="flex-col">
      <div class="flex w-full" data-testid="startup-header">
        <a href="https://wellfound.com/company/techstart">
          <h2 class="inline text-md font-semibold">TechStart Inc</h2>
        </a>
      </div>
    </div>
  </div>
  <div class="mb-4 w-full px-4">
    <div class="min-h-[50px] items-end justify-between rounded-2xl px-2 py-2 sm:flex">
      <div class="w-full pb-1 sm:pb-0">
        <div class="mb-1 flex items-start">
          <a class="mr-2 text-sm font-semibold text-brand-burgandy hover:underline"
             href="https://wellfound.com/jobs/789-remote-designer">Remote Designer</a>
          <span class="whitespace-nowrap rounded-lg bg-accent-yellow-100 px-2 py-1 text-[10px] font-semibold text-neutral-800">Contract</span>
        </div>
        <div class="sm:flex sm:space-x-2">
          <div class="flex items-center text-neutral-500">
            <span class="pl-1 text-xs">Remote</span>
          </div>
        </div>
        <span class="text-xs lowercase text-dark-a md:hidden">2 weeks ago</span>
      </div>
    </div>
  </div>
</div>
</body>
</html>
"""


# =====================================================================
#  _to_wellfound_slug
# =====================================================================


class TestToWellfoundSlug:
    def test_basic_role(self):
        assert _to_wellfound_slug("Software Engineer") == "software-engineer"

    def test_single_word(self):
        assert _to_wellfound_slug("Designer") == "designer"

    def test_special_chars_stripped(self):
        assert _to_wellfound_slug("C++ Developer") == "c-developer"

    def test_extra_whitespace_collapsed(self):
        assert _to_wellfound_slug("  Senior   DevOps   ") == "senior-devops"

    def test_trailing_hyphen_stripped(self):
        assert _to_wellfound_slug("Engineer-") == "engineer"

    def test_location_slug(self):
        assert _to_wellfound_slug("San Francisco") == "san-francisco"


# =====================================================================
#  _build_search_url (corrected URL pattern)
# =====================================================================


class TestBuildSearchUrl:
    def test_without_location(self):
        url = _build_search_url("Software Engineer")
        assert url == "https://wellfound.com/role/software-engineer"

    def test_special_chars_handled(self):
        url = _build_search_url("C++ Developer")
        assert url == "https://wellfound.com/role/c-developer"

    def test_location_param_used_in_url(self):
        """Location is now embedded in URL for server-side filtering."""
        url = _build_search_url("Product Manager", "Bangalore")
        assert url == "https://wellfound.com/role/l/product-manager/bangalore"

    def test_banglore_mapped_to_bangalore(self):
        """Banglore misspelling should map to bangalore slug."""
        url = _build_search_url("Software Engineer", "Banglore")
        assert url == "https://wellfound.com/role/l/software-engineer/bangalore"

    def test_bengaluru_mapped_to_bangalore(self):
        """Bengaluru should map to bangalore slug for best results."""
        url = _build_search_url("Software Engineer", "Bengaluru")
        assert url == "https://wellfound.com/role/l/software-engineer/bangalore"

    def test_mumbai_slug(self):
        """Mumbai should use its own slug."""
        url = _build_search_url("Data Analyst", "Mumbai")
        assert url == "https://wellfound.com/role/l/data-analyst/mumbai"

    def test_location_with_spaces(self):
        """Multi-word locations like San Francisco."""
        url = _build_search_url("Engineer", "San Francisco")
        assert url == "https://wellfound.com/role/l/engineer/san-francisco"


class TestBuildRemoteSearchUrl:
    def test_remote_url(self):
        url = _build_remote_search_url("Data Analyst")
        assert url == "https://wellfound.com/role/r/data-analyst"

    def test_remote_url_special_chars(self):
        url = _build_remote_search_url("C++ Developer")
        assert url == "https://wellfound.com/role/r/c-developer"


# =====================================================================
#  _normalise_location
# =====================================================================


class TestNormaliseLocation:
    def test_empty_string_returns_remote(self):
        assert _normalise_location("") == "Remote"

    def test_remote_returns_remote(self):
        assert _normalise_location("Remote") == "Remote"

    def test_anywhere_returns_remote(self):
        assert _normalise_location("Anywhere") == "Remote"

    def test_worldwide_returns_remote(self):
        assert _normalise_location("Worldwide") == "Remote"

    def test_specific_city_preserved(self):
        assert _normalise_location("San Francisco, CA") == "San Francisco, CA"

    def test_strips_whitespace(self):
        assert _normalise_location("  Remote  ") == "Remote"


# =====================================================================
#  _parse_jobs_from_html
# =====================================================================


class TestParseJobsFromHtml:
    def test_parse_sample_html(self):
        jobs = _parse_jobs_from_html(SAMPLE_HTML)
        assert len(jobs) == 3

    def test_job_titles(self):
        jobs = _parse_jobs_from_html(SAMPLE_HTML)
        titles = {j["title"] for j in jobs}
        assert titles == {"Data Analyst", "Senior Engineer", "Remote Designer"}

    def test_companies(self):
        jobs = _parse_jobs_from_html(SAMPLE_HTML)
        companies = {j["company"] for j in jobs}
        assert companies == {"Acme Corp", "TechStart Inc"}

    def test_locations(self):
        jobs = _parse_jobs_from_html(SAMPLE_HTML)
        locs = {j["title"]: j["location"] for j in jobs}
        # Data Analyst only has a salary span → no location → defaults to "Remote"
        assert locs["Data Analyst"] == "Remote"
        # Senior Engineer has "In office - Bengaluru" → stripped to "Bengaluru"
        assert locs["Senior Engineer"] == "Bengaluru"
        assert locs["Remote Designer"] == "Remote"

    def test_urls(self):
        jobs = _parse_jobs_from_html(SAMPLE_HTML)
        urls = {j["url"] for j in jobs}
        assert urls == {
            "https://wellfound.com/jobs/123-data-analyst",
            "https://wellfound.com/jobs/456-senior-engineer",
            "https://wellfound.com/jobs/789-remote-designer",
        }

    def test_dates(self):
        jobs = _parse_jobs_from_html(SAMPLE_HTML)
        dates = {j["title"]: j["date_posted"] for j in jobs}
        assert dates["Data Analyst"] == "3 days ago"
        assert dates["Senior Engineer"] == "1 week ago"

    def test_empty_html(self):
        assert _parse_jobs_from_html("<html></html>") == []

    def test_no_job_cards(self):
        assert _parse_jobs_from_html("<html><body><p>No jobs</p></body></html>") == []

    def test_experience_span_does_not_overwrite_location(self):
        """Experience level spans (e.g. '2 years of exp') should not overwrite the location."""
        html = """<!DOCTYPE html><html><body>
        <div class="mb-6 w-full rounded border border-gray-400 bg-white">
          <div class="w-full space-y-2 px-4 pb-2 pt-4">
            <div class="flex w-full" data-testid="startup-header">
              <a href="https://wellfound.com/company/acme-corp">
                <h2 class="inline text-md font-semibold">Acme Corp</h2>
              </a>
            </div>
          </div>
          <div class="mb-4 w-full px-4">
            <div class="min-h-[50px] items-end justify-between rounded-2xl px-2 py-2 sm:flex">
              <div class="w-full pb-1 sm:pb-0">
                <div class="mb-1 flex items-start">
                  <a class="mr-2 text-sm font-semibold text-brand-burgandy hover:underline"
                     href="https://wellfound.com/jobs/123-engineer">Engineer</a>
                  <span class="whitespace-nowrap rounded-lg bg-accent-yellow-100 px-2 py-1 text-[10px] font-semibold text-neutral-800">Full-time</span>
                </div>
                <div class="sm:flex sm:space-x-2">
                  <div class="flex items-center text-neutral-500">
                    <span class="pl-1 text-xs">$90k – $120k</span>
                  </div>
                  <div class="flex items-center text-neutral-500">
                    <span class="pl-1 text-xs">In office • Bengaluru</span>
                  </div>
                  <div class="flex items-center text-neutral-500">
                    <span class="pl-1 text-xs">3 years of exp</span>
                  </div>
                </div>
                <span class="text-xs lowercase text-dark-a md:hidden">3 days ago</span>
              </div>
            </div>
          </div>
        </div>
        </body></html>
        """
        jobs = _parse_jobs_from_html(html)
        assert len(jobs) == 1
        # Location should be "Bengaluru" (after normalisation strips "In office • ")
        # NOT "3 years of exp"
        assert jobs[0]["location"] == "Bengaluru"


# =====================================================================
#  _matches_location
# =====================================================================


class TestMatchesLocation:
    def test_none_location_matches_everything(self):
        assert _matches_location("San Francisco", None) is True

    def test_exact_city_match(self):
        assert _matches_location("San Francisco", "San Francisco") is True

    def test_substring_city_match(self):
        assert _matches_location("San Francisco, CA", "San Francisco") is True

    def test_no_match(self):
        assert _matches_location("San Francisco", "Denver") is False

    def test_bengaluru_bangalore_fuzzy_match(self):
        assert _matches_location("Bengaluru", "Bangalore") is True

    def test_banglore_bangalore_fuzzy_match(self):
        assert _matches_location("Bangalore", "Banglore") is True

    def test_bangalore_urban_contains_variant(self):
        """'Bangalore Urban' contains 'bangalore' → should match 'Banglore'."""
        assert _matches_location("Bangalore Urban", "Banglore") is True

    def test_bengaluru_to_banglore_urban(self):
        """'Banglore Urban' → variant not exact but checking."""
        assert _matches_location("Bengaluru", "Banglore") is True

    def test_remote_does_not_match_city(self):
        """Remote jobs should NOT match a city-specific search."""
        assert _matches_location("Remote", "Bangalore") is False

    def test_remote_india_does_not_match_city(self):
        """Remote • India should NOT match a city-specific search."""
        assert _matches_location("Remote • India", "Bangalore") is False

    def test_case_insensitive(self):
        assert _matches_location("san francisco", "San Francisco") is True

    def test_job_location_reverse_substring(self):
        assert _matches_location("New York, NY", "New York") is True
