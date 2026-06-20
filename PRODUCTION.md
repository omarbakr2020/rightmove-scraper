# Production Monitoring: Rightmove Property Scraper

## Architecture Overview

The pipeline runs in two decoupled stages connected by a Redis job queue.

**Stage 1 — Search crawler.** Enumerates UK property listings by outcode,
collecting listing IDs and stub data from `__NEXT_DATA__` embedded in
Rightmove's server-rendered search pages. Pushes each listing ID as a job
to the Redis queue and writes a `scrape_runs` record for observability.

**Stage 2 — Detail workers.** Consumes jobs from the queue. For each
listing ID, fetches the detail page, resolves the `__PAGE_MODEL__` flat-array
encoding (see note below), and upserts the full record to PostgreSQL.
Runs in parallel with a configurable concurrency ceiling.

Both stages write to PostgreSQL. The four tables form the backbone of both
storage and observability: `scrape_runs`, `listings`, `price_history`,
and `listing_images`.

### A note on `__PAGE_MODEL__`

During development I found that Rightmove uses a flyweight/deduplication
pattern in the detail page. The `data` field is not standard nested JSON —
it is a flat array where objects reference other positions by integer index
rather than nesting values directly. A resolver function walks these
references recursively before any field can be read. This is important for
monitoring: if Rightmove adds a nesting level, the resolver silently returns
an integer instead of a string. Type-checking every extracted value is the
guard against this specific failure.

---

## 1. Scaling to Hundreds of Thousands of Listings

**The core constraint.** A broad London search reports 62,475 properties but
Rightmove caps results at approximately 42 pages × 24 listings ≈ 1,008
retrievable results per search query. A naive "search all of London" approach
misses 98% of the inventory regardless of how many workers are running.

**Solution: outcode sub-searches.** The UK has approximately 3,000 outcodes
(SW1X, M1, BS8…), each covering a bounded geographic area with typically
50–500 active listings — well within Rightmove's results cap. A full national
crawl enumerates all outcodes and issues one paginated search per outcode,
merging the results. This gives access to the complete national inventory.

**Queue-based horizontal scaling.** Stage 1 (the search crawler) is a single
producer: it works through outcodes and pushes listing IDs to Redis. Stage 2
(detail workers) is a horizontally scalable consumer pool that autoscales on
queue depth. These two concerns scale independently. If the queue backs up,
add workers. If outcode enumeration is slow, parallelise the producer across
outcode batches. Neither change affects the other stage.

**Database connection pooling.** With 50+ workers each holding a psycopg2
connection, you'll hit PostgreSQL's connection limit (default 100).
The fix is PgBouncer — a connection pooler that sits between your workers
and PostgreSQL. Workers connect to PgBouncer (which supports thousands of
connections), and PgBouncer maintains a pool of ~20 real connections to
PostgreSQL. Workers think they have a direct connection; PostgreSQL only sees the pool.

**Incremental crawling.** Sorting search results by `sortType=6` (most
recently updated) and stopping pagination once `addedOrReduced` dates are
older than the previous run converts a full crawl into a delta crawl. On most
days, 2–5% of listings change. The effective daily request count drops by 95%+
once the initial full crawl is complete.

**Deduplication.** All upserts use `INSERT ... ON CONFLICT (portal,
portal_listing_id) DO UPDATE`, making every run fully idempotent. Re-scraping
a listing never creates duplicates.

---

## 2. Tracking Price Changes Over Time

Price history is handled at the database layer. The `price_history` table is
strictly append-only — no rows are ever updated or deleted. On every scrape,
the worker compares the incoming price against the most recent row for that
listing:

- **First scrape** → insert with `change_type = 'initial'`
- **Price unchanged** → no insert
- **Price decreased** → insert with `change_type = 'reduction'`
- **Price increased** → insert with `change_type = 'increase'`

This gives a complete, auditable trail. It answers: how many times has this
property been reduced? What was the asking price on a specific date? Which
listings dropped price in the last 7 days?

**On price sources.** The search page (`__NEXT_DATA__`) supplies price as a
clean integer (`price.amount = 46000000`). The detail page (`__PAGE_MODEL__`)
only supplies a formatted string (`"£46,000,000"`). The search page integer is
the authoritative source because string parsing is fragile. If Rightmove adds
a qualifier like "Guide Price" or "POA", the integer parse fails silently. The
`price_qualifier` field is stored separately so downstream consumers know when
to treat the integer with caution.

---

## 3. Detecting Silent Stoppage

_Silent_ is the operative word. A crash is easy to detect. What is dangerous
is a scraper that reports success while producing nothing — the process is up,
no exceptions are thrown, but the queue is stalled or the extractors are
returning empty arrays.

Three independent detection layers:

### Layer 1 — Freshness SLO on `scrape_runs`

A monitoring query runs every 15 minutes:

```sql
SELECT COUNT(*) FROM scrape_runs
WHERE started_at > NOW() - INTERVAL '2 hours'
AND status = 'completed';
```

If this returns zero, the pipeline has not produced a completed run in two
hours. Fire a P1 alert. This catches: scheduler died, scraper hung without
throwing, database connection failed on startup.

### Layer 2 — Volume anomaly detection

Even when a run "completes", the `scrape_runs` counters let you distinguish
failure modes:

| Pattern                                                                   | Diagnosis                                         |
| ------------------------------------------------------------------------- | ------------------------------------------------- |
| `listings_discovered` drops to zero                                       | Stage 1 broken — `__NEXT_DATA__` parse failing    |
| `listings_discovered` normal, `listings_new + listings_updated` near zero | Stage 2 broken — detail fetch or resolver failing |
| Both normal, downstream data quality degrades                             | Extraction logic broken silently                  |

Compare `listings_discovered` against the 7-day rolling average for the same
outcode. A run that discovers 0 listings in a region that normally yields 300
fires a P2 alert.

### Layer 3 — Canary listings

A set of 20 known-stable listing IDs (properties that have been live for
several months) are scraped on every run and their extracted fields verified
against expected values. If any canary fails to extract or returns null on a
non-nullable field, something broke in the resolver or extraction logic.

---

## 4. Identifying Silent Data-Quality Issues

Quality issues are distinct from pipeline failure. The scraper runs
successfully, but the data it produces is incomplete or wrong in ways that
accumulate undetected until a downstream consumer reports a problem.

### Per-field null rates

After every scrape run, compute the null/empty rate for each column. Alert
when a rate crosses its threshold:

| Field              | Normal null rate   | Alert threshold | Likely cause                 |
| ------------------ | ------------------ | --------------- | ---------------------------- |
| `price`            | ~1% (POA listings) | > 5%            | Price format change          |
| `bedrooms`         | ~2%                | > 8%            | Schema key rename            |
| `description_html` | 0%                 | > 0.5%          | Detail page structure change |
| `display_address`  | 0%                 | > 0.1%          | Address schema change        |
| `agent_branch_id`  | 0%                 | > 1%            | Customer object restructure  |
| Images (count = 0) | 0%                 | > 1%            | Image array path change      |

When Rightmove renames a JSON key, the extractor does not throw an error — it
silently returns null for every listing. The null rate spikes from 1% to 98%
overnight. That spike is the signal.

### Type validation

Because `__PAGE_MODEL__` uses integer references, the resolver can silently
return an integer instead of a string if Rightmove adds a nesting level. Every
extracted value is type-checked: is price a number? is address a non-empty
string? is bedrooms an integer in 0–20? These checks run before the upsert,
and failures are counted in the run's `listings_errored` column.

### Distribution drift on categorical fields

Track the frequency distribution of `property_type` weekly. If "Apartment"
drops from 40% to 2%, the `propertySubType` resolver is broken. A large
relative shift in a categorical distribution is a reliable signal that an
extractor path has changed.

---

## 5. Monitoring Extraction Accuracy

Accuracy is distinct from completeness. A null rate monitors whether a field
is _present_. Accuracy monitors whether the value is _correct_.

### Golden set verification

A hand-labelled dataset of 100 listings with manually verified field values is
re-scraped on every code deploy. Extracted values are diffed against ground
truth. Any field that changes in the golden set without the source listing
having changed on Rightmove flags an extraction regression. This catches bugs
that survive type-checking and null-rate monitoring because the wrong value is
present and plausible — a transposed price, a truncated description, a
bedroom count read from the wrong field.

### Cross-source validation

Stage 1 and Stage 2 extract overlapping fields: address, price, bedrooms,
agent. After every listing is processed, these are compared. A mismatch
between the two sources for the same field on the same listing surfaces
extractor bugs that unit tests miss — for example, the search page and detail
page disagreeing on bedroom count is a reliable sign that one resolver path is
reading the wrong index.

### LLM-assisted spot-checking

A nightly batch job samples 50–100 random listings, re-fetches the raw HTML,
and passes both the HTML and the extracted data to a language model. The model
verifies each field: "does the extracted address match what the page says?",
"is this description truncated?". This catches subtle extraction errors that
rule-based checks miss, without requiring a pre-labelled golden set for every
field. The approach mirrors the semantic verification layer built in the Plutio
Ask & Memory project, where LLM verification was used to confirm data accuracy
across 12 entity types.

---

## 6. Alerting When Something Breaks

The design principle: an alert that fires without telling you what to do is
worse than no alert. Every alert includes the failure type, magnitude, affected
region or outcode, and a link to the relevant runbook.

### Severity tiers

| Tier                | Trigger                                                                     | Channel                  | Response         |
| ------------------- | --------------------------------------------------------------------------- | ------------------------ | ---------------- |
| P1 — Pipeline down  | No completed run in 2h / fatal unhandled error / DB unreachable             | PagerDuty                | Immediate        |
| P2 — Silent failure | Volume drop >50% vs 7-day baseline / canary extraction failed               | Slack `#scraper-alerts`  | Within 1 hour    |
| P3 — Quality drift  | Null rate spike on any field / distribution shift / type check failures >1% | Slack `#scraper-quality` | Within 4 hours   |
| Info                | Run completed with summary counts                                           | Slack `#scraper-logs`    | No action needed |

### Alert fatigue prevention

Thresholds are calibrated against two weeks of observed baseline data, not
guessed. Volume anomaly detection uses a 7-day rolling average rather than a
fixed threshold to handle weekly patterns (weekend listing activity is
measurably lower than weekday). An alert that fires every Saturday at 9am
because the threshold doesn't account for weekends gets disabled within a week.

### Runbooks

Every P1 and P2 alert links to a runbook file in the repository. The runbook
for "volume drop" says: check `scrape_runs` for the last three runs, check
Rightmove manually for the affected outcode, check Stage 1 logs for
`__NEXT_DATA__` parse errors. Runbooks exist because the person responding at
2am should not have to invent the debugging sequence.

---

### Rate limiting

A jittered delay of 1–3 seconds between requests (randomised per request, not
fixed) keeps the crawl rate below detectable patterns. Fixed delays are
fingerprintable; jitter is not. Heavy crawl jobs are scheduled between 1am–5am
UK time to avoid peak-hour load. On a 429 response, exponential backoff with
the server's `Retry-After` header honoured.

### Anti-bot detection

Realistic browser headers are sent on every request: a current Chrome
`User-Agent`, `Accept-Language: en-GB`, `Referer` set to a Rightmove search
page, and session cookies maintained across requests within a run. A stateless
request on every detail page is a strong bot fingerprint; session continuity
reduces it significantly. During development, a `curl` test with these headers
against both `__NEXT_DATA__` and `__PAGE_MODEL__` endpoints returned HTTP 200
with complete data, confirming that basic browser-mimicking headers are
sufficient at this volume.

### CAPTCHAs

Detect by scanning the response body for CAPTCHA indicators before attempting
to parse. On detection: log the event, back off, rotate the session, retry
after an exponential delay. Third-party solving services (2captcha, etc.) are
noted as a production option for high-volume commercial use but are not
appropriate here — they add cost, latency, and an external dependency that a
polite, rate-limited crawler should not need.

### Dynamic JavaScript content

The most operationally significant finding from development recon: Rightmove's
core listing data is fully server-rendered. Both `__NEXT_DATA__` on search
pages and `__PAGE_MODEL__` on detail pages are present in the initial HTTP
response before any JavaScript executes. A headless browser costs 10–50× more
per page in CPU, memory, and time. The architecture uses plain HTTP requests
throughout specifically because `curl` confirmed this approach works reliably.

If Rightmove migrates to client-side rendering in future, only the Stage 2
detail worker layer would need upgrading to a headless browser (Playwright).
Stage 1, the queue, and all storage logic would be unchanged — another benefit
of the two-stage decoupled design.

### Terms of service

Rightmove's `__NEXT_DATA__` response contains an explicit notice that their
internal API is for Rightmove's use only. This scraper extracts only publicly
visible listing data, respects rate limits, and is built for portfolio and
demonstration purposes. A commercial deployment would require a data licensing
agreement with Rightmove or use of an authorised data partner such as
Rightmove's Data Services offering.
