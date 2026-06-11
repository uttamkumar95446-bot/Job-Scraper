"""Shared data models for the Job Agent."""

from dataclasses import dataclass, field
from datetime import datetime, timezone


@dataclass
class Job:
    """A single job listing normalised across all platforms."""

    title: str
    """Job title (e.g. "Software Engineer")."""

    company: str
    """Company name."""

    location: str
    """Job location or "Remote"."""

    url: str
    """Direct link to the listing."""

    source: str
    """Platform name: naukri / remoteok / wellfound."""

    date_posted: str = ""
    """Posting date (free-text, may be empty)."""

    scraped_at: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )
    """Timestamp when the agent collected the listing."""

    def to_csv_row(self) -> dict[str, str]:
        """Return a dict suitable for csv.DictWriter."""
        return {
            "title": self.title,
            "company": self.company,
            "location": self.location,
            "url": self.url,
            "source": self.source,
            "date_posted": self.date_posted,
            "scraped_at": self.scraped_at,
        }

    @staticmethod
    def csv_columns() -> list[str]:
        """Return the canonical column order for CSV output."""
        return [
            "title",
            "company",
            "location",
            "url",
            "source",
            "date_posted",
            "scraped_at",
        ]
