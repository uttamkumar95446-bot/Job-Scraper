# Job Agent

Automated job discovery across **Naukri**, **RemoteOK**, and **Wellfound** -- all in one CLI command.

## Features

- Search across **3 platforms** with a single command
- Filter by **role** (required) and **location** (optional)
- **CSV output** -- one file per run, timestamped
- **Parallel scraping** for speed
- **Extensible** -- add new platforms via `BaseScraper`

## Quick Start

```bash
# 1. Install dependencies
pip install -r requirements.txt

# 2. Set up environment variables
cp .env.example .env
# Edit .env and add your FIRECRAWL_API_KEY

# 3. Run the agent
python src.main "Product Manager roles in Bangalore"
```

## Usage

```bash
# Natural-language query (recommended)
python src.main "Product Manager roles in Bangalore"
python src.main "Data Analyst"
python src.main "Python Developer jobs in Mumbai"

# Explicit flags (backward compatible)
python src.main --role "Software Engineer"
python src.main --role "Data Analyst" --location "Mumbai"

# Specific sources only
python src.main "Backend Developer" --sources naukri,remoteok
python src.main "Product Manager" -s naukri

# Help
python src.main --help
```

### Arguments

| Argument | Required | Description |
|----------|----------|-------------|
| `query` | No* | Natural-language search query (e.g. `"Data Analyst"`, `"Product Manager roles in Bangalore"`) |
| `--role` | No | Job title (e.g. `"Product Manager"`); overrides parsed query |
| `--location` / `-loc` | No | Location filter (e.g. `"Bangalore"`); overrides parsed query |
| `--sources` / `-s` | No | Comma-separated sources -- `naukri`, `remoteok`, `wellfound` (default: all) |

\* Either `query` or `--role` must be provided.

## Output

Results are saved to `output/jobs_<YYYYMMDD_HHMMSS>.csv` with the following columns:

| Column | Description |
|--------|-------------|
| `title` | Job title |
| `company` | Company name |
| `location` | Job location |
| `url` | Link to listing |
| `source` | Platform name |
| `date_posted` | Posting date |
| `scraped_at` | Collection timestamp |

## Architecture

```
job-agent/
├── src/
│   ├── main.py              # CLI entry-point & orchestrator
│   ├── models.py            # Job dataclass
│   ├── csv_writer.py        # CSV output
│   └── scrapers/
│       ├── base.py           # Abstract base scraper
│       ├── naukri.py         # Naukri (undetected-chromedriver + BS4)
│       ├── remoteok.py       # RemoteOK (public API)
│       └── wellfound.py      # Wellfound (Firecrawl)
├── output/                   # Generated CSV files
├── requirements.txt
└── .env.example
```

## Development

```bash
# Install dev dependencies
pip install pytest mypy

# Run tests (when available)
pytest

# Type check
mypy src/
```

## Scraping Strategies

| Platform | Strategy | Tooling |
|----------|----------|---------|
| Naukri | HTML scraping after JS render | undetected-chromedriver + BeautifulSoup |
| RemoteOK | Public JSON API | requests |
| Wellfound | JS-rendered page extraction | Firecrawl SDK |

## Roadmap

- [x] Phase 1 -- Project scaffolding & core models
- [x] Phase 2 -- Naukri scraper (undetected-chromedriver + BeautifulSoup)
- [x] Phase 3 -- RemoteOK scraper (public API)
- [x] Phase 4 -- Wellfound scraper (Firecrawl)
- [x] Phase 5 -- CLI integration & end-to-end run
