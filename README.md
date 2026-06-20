# Rightmove Property Scraper

A production-grade Rightmove scraper written in Python. Extracts UK property
listings, tracks price history, and is designed for unattended operation.

## Architecture

Two-stage pipeline connected by an in-process queue:

```
UK outcodes → Stage 1 (search crawler) → queue.Queue → Stage 2 (worker pool) → PostgreSQL
                    ↓                                           ↓
              scrape_runs                              listings + price_history + images
```

**Stage 1** paginates Rightmove search pages, extracting listing stubs from
the `__NEXT_DATA__` script tag embedded in the server-rendered HTML.

**Stage 2** fetches each listing's detail page, resolves Rightmove's custom
`__PAGE_MODEL__` flat-array encoding (see `src/scraper/resolver.py`), and
upserts the full record to PostgreSQL in a single transaction.

If a detail page fetch fails, the listing is saved using search page data only.
The missing field is `description_html`. A future run fills it in via `COALESCE`
in the upsert SQL without overwriting anything else.

See `PRODUCTION.md` for the full monitoring and scaling design.

## Tech stack

- Python 3.11+
- `requests` — HTTP client with session-based cookie management
- `psycopg2` — PostgreSQL driver
- `python-dotenv` — environment config

No Redis dependency for the demo. In production at scale, swap `queue.Queue`
for RQ or Celery backed by Redis, and run Stage 2 as separate worker processes.
The Stage 1 and Stage 2 code doesn't need to change — only the queue wiring in
`src/main.py`.

## Setup

### Prerequisites

- Python 3.11+
- Docker (for PostgreSQL)

### 1. Clone and install

```bash
git clone https://github.com/omarbakr2020/rightmove-scraper
cd rightmove-scraper
python3 -m venv venv
source venv/bin/activate
pip3 install -r requirements.txt
```

### 2. Configure environment

```bash
cp .env.example .env
```

### 3. Start the database

```bash
docker compose up -d
# PostgreSQL starts on port 5433
# Schema is applied automatically on first start
```

### 4. Run a development scrape

```bash
# Scrape first 3 pages of London listings (~75 listings)
MAX_PAGES=3 python3 -m src.main
```

### 5. Inspect results

```bash
psql postgresql://scraper:scraper_dev@localhost:5433/rightmove_scraper

-- Run summary
SELECT id, status, listings_discovered, listings_new, listings_errored,
       started_at, finished_at
FROM scrape_runs ORDER BY started_at DESC LIMIT 5;

-- Sample listings
SELECT portal_listing_id, display_address, price, property_type,
       bedrooms, agent_branch_display_name
FROM listings LIMIT 10;

-- Price history
SELECT l.display_address, ph.price, ph.change_type, ph.observed_at
FROM price_history ph
JOIN listings l ON l.id = ph.listing_id
ORDER BY ph.observed_at DESC LIMIT 10;
```

## Sample Output

Three listings from a London development run (`MAX_PAGES=3`):

```json
[
  {
    "url": "https://www.rightmove.co.uk/properties/88659360",
    "display_address": "High Road, North Finchley, N12",
    "price": 285000,
    "price_raw": "£285,000",
    "property_type": "Apartment",
    "bedrooms": 1,
    "description_preview": "A beautiful one bedroom first floor purpose-built lift serviced apartment set back off North Finchley High Road, within easy access to multiple shopping and transport facilities, East Finchley Tube St",
    "agent_branch_display_name": "Adam Hayes Estate Agents, North Finchley, N12",
    "key_features": [
      "One Bedroom",
      "First Floor Apartment",
      "Modern Kitchen",
      "Chain Free",
      "Communal Gardens",
      "Secure Gated Allocated Parking"
    ]
  },
  {
    "url": "https://www.rightmove.co.uk/properties/174328301",
    "display_address": "Pan Peninsula Square, Canary Wharf, London, E14",
    "price": 375000,
    "price_raw": "£375,000",
    "property_type": "Flat",
    "bedrooms": 1,
    "description_preview": "Luxury one bedroom apartment set within the stunning East Tower of Pan Peninsula, spacious open plan living room with a private balcony, a well-equipped open plan stylish kitchen, modern bedroom with",
    "agent_branch_display_name": "Chase Evans, Pan Peninsula",
    "key_features": [
      "LUXURY ONE BEDROOM",
      "BALCONY",
      "ONSITE LEISURE & FITNESS FACILITIES",
      "24-HOUR CONCIERGE",
      "CLOSE TO ALL THE AMENITIES",
      "0.1 MI TO SOUTH QUAY DLR",
      "0.5 MI TO CANARY WHARF STATION"
    ]
  },
  {
    "url": "https://www.rightmove.co.uk/properties/89949297",
    "display_address": "Skyline Apartments, Makers Yard, London",
    "price": 370000,
    "price_raw": "£370,000",
    "property_type": "Flat",
    "bedrooms": 1,
    "description_preview": "A beautifully designed apartment within the sought-after Three Waters development, offering contemporary living in a vibrant waterside setting. The property features a bright open-plan living and dini",
    "agent_branch_display_name": "Imperial Dragon Property Management, London",
    "key_features": [
      "Spacious high floor unit",
      "Open city view",
      "Great condition"
    ]
  }
]
```

Full image URLs are stored in the `listing_images` table. Query with:

```sql
SELECT l.display_address, i.position, i.url_large
FROM listings l
JOIN listing_images i ON i.listing_id = l.id
ORDER BY l.id, i.position;
```

## Project structure

```
rightmove-scraper/
├── src/
│   ├── main.py                    Entry point — wires stages together
│   ├── types.py                   Shared dataclasses (SearchListing, DetailListing, etc.)
│   ├── scraper/
│   │   ├── resolver.py            __PAGE_MODEL__ flat-array resolver
│   │   ├── http_client.py         Rate-limited requests.Session with cookie support
│   │   ├── stage1.py              Search page crawler (producer)
│   │   └── stage2.py              Detail page worker pool (consumers)
│   ├── extractors/
│   │   ├── search.py              Parse __NEXT_DATA__ from search pages
│   │   └── detail.py              Parse __PAGE_MODEL__ from detail pages
│   └── storage/
│       └── listings.py            Upsert logic with price history tracking
├── migrations/
│   └── 001_schema.sql             PostgreSQL schema
├── PRODUCTION.md                  Monitoring and scaling design document
├── docker-compose.yml
├── requirements.txt
└── .env.example
```

## Database schema

| Table            | Purpose                                                          |
| ---------------- | ---------------------------------------------------------------- |
| `scrape_runs`    | One row per pipeline execution. Heartbeat for monitoring.        |
| `listings`       | One row per property. Upserted on `(portal, portal_listing_id)`. |
| `price_history`  | Append-only. One row per observed price change.                  |
| `listing_images` | One row per photo, ordered by position.                          |

Full schema: `migrations/001_schema.sql`

## Key implementation notes

**Why `queue.Queue` instead of Redis:** For a demo that runs in one command,
Python's built-in queue is sufficient. The architecture is identical (producer
fills queue, consumer pool drains it). Swapping to Redis/RQ for production requires
changing only `src/main.py` — the stage1 and stage2 logic is unchanged.

## Known edge cases

**Large listing IDs** (e.g. `757097812420945`): Non-standard IDs for new-build
developments. Filtered out in `src/extractors/search.py` (`id > 999_999_999`).

**`price_qualifier` non-empty:** When Rightmove shows "Guide Price" or "POA",
`price` may be null. The `price_qualifier` column carries this context.

**Terms of service:** This project scrapes publicly visible listing data for
portfolio and educational purposes. A commercial deployment would require a data
licensing agreement with Rightmove.
