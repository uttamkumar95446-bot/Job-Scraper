# Job Agent — Scrapers sub-package
#
# IMPORTANT: Do NOT import individual scrapers here.
# Each scraper has heavy dependencies (e.g. undetected_chromedriver, selenium)
# that may not be compatible with the current Python version.
# Scrapers are lazily imported in app.py via importlib.import_module().

from .base import BaseScraper

__all__ = [
    "BaseScraper",
]
