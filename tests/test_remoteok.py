"""Unit tests for the RemoteOK scraper."""

from unittest.mock import MagicMock, patch

import pytest
import requests

from src.scrapers.remoteok import (
    API_URL,
    RemoteOKScraper,
    _build_search_url,
    _job_from_api,
    _matches_location,
    _matches_role_exact,
    _matches_role_keyword,
    _extract_role_keywords,
    _normalise_location,
)


SAMPLE_METADATA = {"version": 1, "terms": "..."}

SAMPLE_JOBS = [
    {"position": "Data Analyst", "company": "Hired", "location": "Worldwide", "url": "/remote-job/data-analyst-hired", "date": "2025-06-01T10:00:00Z"},
    {"position": "Senior Data Analyst", "company": "Stio", "location": "Denver, Colorado", "url": "/remote-job/senior-data-analyst-stio", "date": "2025-05-28T08:30:00Z"},
    {"position": "Product Manager", "company": "Acme Inc", "location": "Remote", "url": "/remote-job/pm-acme", "date": "2025-06-02T12:00:00Z"},
    {"position": "Software Engineer", "company": "TechCorp", "location": "San Francisco, CA", "url": "https://remoteok.com/remote-job/engineer-techcorp", "date": ""},
]

SAMPLE_API_RESPONSE = [SAMPLE_METADATA, *SAMPLE_JOBS]


# ---- Tests for _normalise_location ----

class TestNormaliseLocation:
    def test_empty_string_returns_remote(self):
        from src.scrapers.remoteok import _normalise_location
        assert _normalise_location("") == "Remote"

    def test_worldwide_returns_remote(self):
        from src.scrapers.remoteok import _normalise_location
        assert _normalise_location("Worldwide") == "Remote"

    def test_anywhere_returns_remote(self):
        from src.scrapers.remoteok import _normalise_location
        assert _normalise_location("Anywhere") == "Remote"

    def test_remote_returns_remote(self):
        from src.scrapers.remoteok import _normalise_location
        assert _normalise_location("remote") == "Remote"

    def test_specific_city_preserved(self):
        from src.scrapers.remoteok import _normalise_location
        assert _normalise_location("San Francisco, CA") == "San Francisco, CA"

    def test_strips_whitespace(self):
        from src.scrapers.remoteok import _normalise_location
        assert _normalise_location("  Remote  ") == "Remote"


# ---- Tests for _matches_role_exact ----

class TestMatchesRoleExact:
    def test_exact_match(self):
        from src.scrapers.remoteok import _matches_role_exact
        assert _matches_role_exact({"position": "Data Analyst"}, "Data Analyst") is True

    def test_case_insensitive(self):
        from src.scrapers.remoteok import _matches_role_exact
        assert _matches_role_exact({"position": "data analyst"}, "Data Analyst") is True

    def test_substring_match(self):
        from src.scrapers.remoteok import _matches_role_exact
        assert _matches_role_exact({"position": "Senior Data Analyst"}, "Data Analyst") is True

    def test_no_match(self):
        from src.scrapers.remoteok import _matches_role_exact
        assert _matches_role_exact({"position": "Product Manager"}, "Data Analyst") is False

    def test_empty_position_fails(self):
        from src.scrapers.remoteok import _matches_role_exact
        assert _matches_role_exact({"position": ""}, "engineer") is False

    def test_missing_position_key(self):
        from src.scrapers.remoteok import _matches_role_exact
        assert _matches_role_exact({}, "engineer") is False


# ---- Tests for _matches_role_keyword ----

class TestMatchesRoleKeyword:
    def test_matches_one_keyword(self):
        from src.scrapers.remoteok import _matches_role_keyword
        assert _matches_role_keyword({"position": "Applied AI Engineer"}, ["engineer"]) is True

    def test_matches_any_keyword(self):
        from src.scrapers.remoteok import _matches_role_keyword
        assert _matches_role_keyword({"position": "Senior ML Engineer"}, ["software", "engineer"]) is True

    def test_no_keyword_match(self):
        from src.scrapers.remoteok import _matches_role_keyword
        assert _matches_role_keyword({"position": "Product Manager"}, ["data", "analyst"]) is False

    def test_case_insensitive(self):
        from src.scrapers.remoteok import _matches_role_keyword
        assert _matches_role_keyword({"position": "Applied AI Engineer"}, ["engineer"]) is True

    def test_empty_keywords(self):
        from src.scrapers.remoteok import _matches_role_keyword
        assert _matches_role_keyword({"position": "Engineer"}, []) is False


# ---- Tests for _extract_role_keywords ----

class TestExtractRoleKeywords:
    def test_software_engineer(self):
        from src.scrapers.remoteok import _extract_role_keywords
        assert _extract_role_keywords("Software Engineer") == ["software", "engineer"]

    def test_senior_filler_removed(self):
        from src.scrapers.remoteok import _extract_role_keywords
        assert "senior" not in _extract_role_keywords("Senior Data Analyst")
        assert "data" in _extract_role_keywords("Senior Data Analyst")
        assert "analyst" in _extract_role_keywords("Senior Data Analyst")

    def test_skip_short_words(self):
        from src.scrapers.remoteok import _extract_role_keywords
        assert _extract_role_keywords("ML Engineer") == ["engineer"]

    def test_single_word(self):
        from src.scrapers.remoteok import _extract_role_keywords
        assert _extract_role_keywords("Designer") == ["designer"]

    def test_no_filler(self):
        from src.scrapers.remoteok import _extract_role_keywords
        kw = _extract_role_keywords("Lead Principal Engineer")
        assert "lead" not in kw
        assert "principal" not in kw
        assert "engineer" in kw


# ---- Tests for _matches_location ----

class TestMatchesLocation:
    """RemoteOK location filter: includes remote jobs AND matches the requested location."""

    def test_none_location_matches_everything(self):
        from src.scrapers.remoteok import _matches_location
        assert _matches_location({"location": "Remote"}, None) is True

    def test_remote_job_matches_any_location(self):
        """Remote jobs should always match when a location is specified."""
        from src.scrapers.remoteok import _matches_location
        assert _matches_location({"location": "Remote"}, "Banglore") is True
        assert _matches_location({"location": "Worldwide"}, "Banglore") is True

    def test_city_specific_job_does_not_match_different_city(self):
        """A job in San Francisco should NOT match a search for Bangalore."""
        from src.scrapers.remoteok import _matches_location
        assert _matches_location({"location": "San Francisco, CA"}, "Banglore") is False

    def test_city_specific_job_matches_requested_city(self):
        """A job in Bangalore should match a search for Bangalore."""
        from src.scrapers.remoteok import _matches_location
        assert _matches_location({"location": "Bangalore"}, "Banglore") is True

    def test_empty_location_field_matches_with_location(self):
        """Empty job location should match (RemoteOK is a remote board; many jobs omit location)."""
        from src.scrapers.remoteok import _matches_location
        assert _matches_location({"location": ""}, "Banglore") is True

    def test_missing_location_key_matches_with_location(self):
        """Missing location key should match (RemoteOK is a remote board; many jobs omit location)."""
        from src.scrapers.remoteok import _matches_location
        assert _matches_location({}, "Banglore") is True

    def test_worldwide_matches_any_location(self):
        """Worldwide jobs should always match when a location is specified."""
        from src.scrapers.remoteok import _matches_location
        assert _matches_location({"location": "Worldwide"}, "Mumbai") is True
        assert _matches_location({"location": "🌍 Worldwide"}, "Bangalore") is True


# ---- Tests for _build_search_url ----

class TestBuildSearchUrl:
    def test_basic_role(self):
        from src.scrapers.remoteok import API_URL, _build_search_url
        url = _build_search_url("Data Analyst")
        # The URL slug is not URL-encoded here; requests auto-encodes.
        assert url == API_URL + "?search=data analyst"

    def test_single_word(self):
        from src.scrapers.remoteok import API_URL, _build_search_url
        url = _build_search_url("Engineer")
        assert url == API_URL + "?search=engineer"


# ---- Tests for _job_from_api ----

class TestJobFromApi:
    def test_full_job(self):
        from src.scrapers.remoteok import _job_from_api
        job = _job_from_api({
            "position": "Data Analyst", "company": "Hired",
            "location": "Worldwide", "url": "/remote-job/x",
            "date": "2025-06-01T10:00:00Z"
        })
        assert job is not None
        assert job.title == "Data Analyst"
        assert job.company == "Hired"
        assert job.location == "Remote"
        assert job.url == "https://remoteok.com/remote-job/x"
        assert job.source == "remoteok"
        assert job.date_posted == "2025-06-01T10:00:00Z"

    def test_specific_location_preserved(self):
        from src.scrapers.remoteok import _job_from_api
        job = _job_from_api({
            "position": "Engineer", "company": "X",
            "location": "Denver, Colorado", "url": "/job", "date": ""
        })
        assert job is not None
        assert job.location == "Denver, Colorado"

    def test_absolute_url_preserved(self):
        from src.scrapers.remoteok import _job_from_api
        job = _job_from_api({
            "position": "Engineer", "company": "X",
            "location": "Remote", "url": "https://remoteok.com/job", "date": ""
        })
        assert job is not None
        assert job.url == "https://remoteok.com/job"

    def test_empty_position_returns_none(self):
        from src.scrapers.remoteok import _job_from_api
        assert _job_from_api({"position": "", "company": "X", "url": "/x"}) is None

    def test_missing_url_returns_none(self):
        from src.scrapers.remoteok import _job_from_api
        assert _job_from_api({"position": "Role", "company": "X"}) is None
