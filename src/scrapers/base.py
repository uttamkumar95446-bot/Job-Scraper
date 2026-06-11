"""Abstract base class for all job-board scrapers."""

from abc import ABC, abstractmethod

from src.models import Job


class BaseScraper(ABC):
    """Every platform scraper inherits from this ABC.

    Subclasses **must** implement ``scrape()`` and populate the
    ``source`` class attribute.
    """

    #: Human-readable platform identifier, e.g. "naukri".
    source: str = ""

    @abstractmethod
    def scrape(self, role: str, location: str | None = None) -> list[Job]:
        """Fetch job listings from the platform.

        Args:
            role: Job title / role keyword to search for.
            location: Optional location string (city, country, etc.).

        Returns:
            A list of normalised :class:`Job` objects.
        """
        ...
