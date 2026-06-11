# Job Agent — Project Context

## Problem Statement

Manually searching for relevant job listings across multiple platforms is time-consuming and repetitive. Job seekers need to visit Naukri, RemoteOK, and Wellfound individually, apply filters, and sift through results — often missing opportunities due to the overhead.

## Solution

Build a **Job Agent** that automates job discovery across three platforms:

| # | Platform | URL | Scraping Strategy |
|---|----------|-----|-------------------|
| 1 | **Naukri** | https://www.naukri.com | undetected-chromedriver + Selenium + BeautifulSoup |
| 2 | **RemoteOK** | https://remoteok.com | Public JSON API (`/api` endpoint) |
| 3 | **Wellfound** | https://wellfound.com | Firecrawl (JS-rendered page extraction) |

The agent will:

1. **Accept a job role and location** as explicit CLI arguments.
2. **Fetch listings** from each platform using its designated strategy (see table above).
3. **Normalise** the results into a common schema.
4. **Store** all collected jobs in a single **CSV file** for easy review and filtering.

### CLI Usage

```bash
# Natural-language query (recommended)
python src.main "Product Manager roles in Bangalore"
python src.main "Software Engineer jobs in Mumbai"
python src.main "Data Analyst"

# Explicit flags (backward compatible)
python -m src.main --role "Product Manager" --location "Bangalore"
python -m src.main --role "Software Engineer" --location "Mumbai"
python -m src.main --role "Data Analyst"   # location is optional

# With source selection
python src.main "Product Manager roles in Bangalore" --sources naukri
python src.main "Python Developer" --sources naukri,remoteok
python src.main "Data Analyst" sources naukri    # 'sources' keyword shorthand (no --)

# Natural-language query = role + location parsed automatically
python src.main "Find product manager roles in Bangalore"  # role="product manager", location="Bangalore"
python src.main "I need a Python Developer"               # role="Python Developer", location=None
```

> **Note**: Use `python src.main <query>` (module syntax) or `python src/main.py <query>` (script syntax).

### Platform URL Construction

Each scraper uses the role + location to build the correct search URL:

| Platform | URL pattern |
| --- | --- |
| **Naukri** | `naukri.com/<role>-jobs-in-<location>` or `naukri.com/<role>-jobs` |
| **RemoteOK** | `remoteok.com/api?search=<role>` then client-side filtered by role keyword |
| **Wellfound** | `wellfound.com/role/<role>` (general), `wellfound.com/role/r/<role>` (remote-only), `wellfound.com/role/l/<role>/<location>` (location-scoped) |

## Output Schema (CSV columns)

| Column | Description |
|--------|-------------|
| `title` | Job title |
| `company` | Company name |
| `location` | Job location or "Remote" |
| `url` | Direct link to the listing |
| `source` | Platform name (naukri / remoteok / wellfound) |
| `date_posted` | Posting date (if available) |
| `scraped_at` | Timestamp when the agent collected the listing |

## Key Constraints & Decisions

- **Language**: Python 3.10+
- **Output format**: CSV (one file per run, e.g. `jobs_<timestamp>.csv`)
- **No database** required — CSV is the single source of truth for each run.
- **Rate-limiting / politeness**: respect `robots.txt` and add reasonable delays between requests.
- **Extensibility**: design scrapers behind a common interface so new platforms can be added easily.

## Implementation Phases

### Phase 1 — Project Scaffolding & Core Models

Set up the repository structure, dependencies, and shared data models.

```
job-agent/
├── docs/
│   └── context.md
├── src/
│   ├── __init__.py
│   ├── main.py              # CLI entry-point
│   ├── models.py            # Job dataclass / schema
│   ├── csv_writer.py        # CSV output logic
│   └── scrapers/
│       ├── __init__.py
│       ├── base.py           # Abstract BaseScraper interface
│       ├── naukri.py         # Phase 2
│       ├── remoteok.py       # Phase 3
│       └── wellfound.py      # Phase 4
├── output/                   # Generated CSV files (gitignored)
├── requirements.txt
├── .env.example              # API keys (FIRECRAWL_API_KEY)
└── README.md
```

**Deliverables:**
- `models.py` — `Job` dataclass matching the CSV schema.
- `base.py` — `BaseScraper` ABC with `scrape(title: str) -> list[Job]`.
- `csv_writer.py` — accepts `list[Job]`, writes to `output/jobs_<timestamp>.csv`.
- `requirements.txt` — initial dependencies (`requests`, `beautifulsoup4`, `firecrawl-py`, `python-dotenv`).

---

### Phase 2 — Naukri Scraper (HTML Scraping)

Implement the Naukri scraper using `undetected-chromedriver` (Selenium) + `BeautifulSoup`.

Naukri uses heavy JavaScript rendering, so a real (undetected) Chrome browser is driven via Selenium to render the page before parsing.

**Steps:**
1. Build the search URL from the job title (e.g. `naukri.com/<title>-jobs[-in-<location>]`).
2. Launch `undetected-chromedriver` Chrome instance.
3. Navigate to the search URL; wait for job cards to render via `WebDriverWait`.
4. Parse the rendered HTML with BeautifulSoup — extract job cards (title, company, location, link, date).
5. Handle pagination (first 3 pages, with polite delay between pages).
6. Add error handling and rate-limiting (1.5–2 s delay between pages).
7. Quit the Chrome driver cleanly in a `finally` block.

**Deliverables:**
- `scrapers/naukri.py` — working `NaukriScraper(BaseScraper)` using `undetected-chromedriver` + `BeautifulSoup`.
- Manual verification with a sample title.

---

### Phase 3 — RemoteOK Scraper (Public API)

Implement the RemoteOK scraper using their public JSON API.

**Steps:**
1. Hit `https://remoteok.com/api` with a `User-Agent` header.
2. Filter the returned JSON array by matching the job title (case-insensitive).
3. Map fields (`position`, `company`, `location`, `url`, `date`) to `Job` model.
4. No pagination needed — the API returns all recent listings in one call.

**Deliverables:**
- `scrapers/remoteok.py` — working `RemoteOKScraper(BaseScraper)`.
- Unit test / manual verification.

---

### Phase 4 — Wellfound Scraper (Firecrawl)

Implement the Wellfound scraper using the Firecrawl SDK for JS-rendered pages.

**Steps:**
1. Load `FIRECRAWL_API_KEY` from `.env`.
2. Construct the Wellfound search URL for the given title.
3. Use Firecrawl's `scrape_url` to get rendered page content.
4. Parse the returned markdown / structured data — extract job cards.
5. Map to `Job` model and return.

**Deliverables:**
- `scrapers/wellfound.py` — working `WellfoundScraper(BaseScraper)`.
- `.env.example` updated with `FIRECRAWL_API_KEY=`.
- Unit test / manual verification.

---

### Phase 5 — CLI Integration & End-to-End Run

Wire everything together in `main.py`. The user provides a natural-language
**query** string (or explicit **--role** + optional **--location** flags);
the agent triggers all three boards with those values in **parallel**.

**Input:**

```bash
# Natural-language queries (query string is parsed for role + location)
python src.main "Product Manager roles in Bangalore"
python src.main "Software Engineer"  # location optional
python src.main "Data Analyst jobs in Mumbai" --sources naukri,remoteok

# Explicit flags (backward compatible)
python src.main --role "Product Manager" --location "Bangalore"
python src.main --role "Software Engineer"
python src.main --role "Data Analyst" --location "Mumbai" --sources naukri,remoteok

# Bare 'sources' keyword (no -- prefix)
python src.main "Data Analyst" sources naukri,remoteok
```

**Steps:**
1. Accept a positional `query` string and/or explicit `--role` + `--location` flags.
2. **Parse natural-language query** using regex:
   - Strips leading filler phrases (`"find me"`, `"I am looking for"`, etc.).
   - Strips trailing filler words (`jobs`, `positions`, `roles`, etc.).
   - Extracts location after `in`/`at`/`near`/`around` keywords.
   - Returns `(role, location)` tuple.
3. **Explicit flags override** parsed values (`--role` and `--location` take precedence).
4. **Parallel execution**: Instantiate all 3 scrapers and run via `ThreadPoolExecutor` — each scraper receives the same `role` and `location`.
5. Run each scraper with `scraper.scrape(role, location)` — every board receives the same role and location.
6. Collect results into a single `list[Job]`.
7. Pass to `csv_writer` → write `output/jobs_<timestamp>.csv`.
8. Print summary to stdout (role, location, per-source counts, total jobs, output file path).
9. Support `--sources` / `-s` flag to optionally run a subset (e.g. `--sources naukri,remoteok`).
10. A `_preprocess_argv` function converts bare `sources` keyword into `--sources` flag for convenience.

**Threading model:**
```python
with ThreadPoolExecutor(max_workers=len(scrapers)) as executor:
    futures = {executor.submit(run_scraper, s, role, location): s for s in scrapers}
    for future in as_completed(futures):
        all_jobs.extend(future.result())
```

**Platform behaviour with location:**

| Platform | How location is used |
| --- | --- |
| **Naukri** | Appended to URL: `naukri.com/<role>-jobs-in-<location>`. If no location, `naukri.com/<role>-jobs`. |
| **RemoteOK** | Location filter is **not applied** — all RemoteOK jobs are inherently remote; every role-matched job is included regardless of requested location. |
| **Wellfound** | Embedded in URL for server-side filtering: `wellfound.com/role/l/<role>/<location>`. Falls back to generic `/role/<role>` then `/role/r/<role>` (remote-only) as fallbacks. City name variants are normalised (e.g. `"Banglore"` → `"bangalore"`). Client-side fuzzy matching also applied. |

**Arguments reference:**

| Argument | Required | Description |
|----------|----------|-------------|
| `query` | No* | Natural-language search query (parsed for role + location) |
| `--role` | No | Job title; overrides parsed query |
| `--location` / `-loc` | No | Location filter; overrides parsed query |
| `--sources` / `-s` / `-sources` | No | Comma-separated sources (default: all) |

\* Either `query` or `--role` must be provided.

**Deliverables:**
- Fully functional CLI: natural-language query, `--role`/`--location` flags, `--sources` flag, bare `sources` keyword.
- Parallel execution via `ThreadPoolExecutor` for speed.
- End-to-end run: all three boards produce results in a single CSV.
- Updated `README.md` with usage instructions and example commands.

---

## Completed Phases

- [x] **Phase 1** — Project scaffolding & core models
- [x] **Phase 2** — Naukri scraper (undetected-chromedriver + BeautifulSoup)
- [x] **Phase 3** — RemoteOK scraper (public JSON API)
- [x] **Phase 4** — Wellfound scraper (Firecrawl)
- [x] **Phase 5** — CLI integration & end-to-end run

## Out of Scope (for now)

- Automatic application / form-filling.
- Deduplication across runs.
- UI / dashboard — CLI-only for the first iteration.
