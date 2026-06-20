import queue
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed

import psycopg2

from ..extractors.detail import extract_detail_listing
from ..scraper.http_client import create_http_client
from ..storage.listings import upsert_listing, increment_counter

_thread_local = threading.local()


def _get_session():
    if not hasattr(_thread_local, 'http'):
        _thread_local.http = create_http_client()
    return _thread_local.http


def _get_conn(database_url: str):
    if not hasattr(_thread_local, 'conn') or _thread_local.conn.closed:
        _thread_local.conn = psycopg2.connect(database_url)
    return _thread_local.conn


def _process_job(job: dict, database_url: str) -> dict:
    listing = job['listing']
    run_id  = job['run_id']
    http    = _get_session()
    conn    = _get_conn(database_url)

    detail        = None
    detail_failed = False

    try:
        url = f'https://www.rightmove.co.uk/properties/{listing.id}'
        print(f'[stage2] Fetching {listing.id}...', flush=True)
        response = http.get(url)
        print(f'[stage2] Got {listing.id}: {response.status_code}, {len(response.text):,} chars', flush=True)
        detail = extract_detail_listing(response.text)
        print(f'[stage2] Parsed {listing.id}', flush=True)
    except Exception as e:
        print(f'[stage2] Detail fetch failed for {listing.id}: {e}')
        detail_failed = True

    listing_id, is_new, price_changed = upsert_listing(conn, listing, detail, run_id)
    print(f'[stage2] Upserted {listing.id} (is_new={is_new}, price_changed={price_changed})')

    if is_new:
        increment_counter(conn, run_id, 'listings_new')
    elif price_changed:
        increment_counter(conn, run_id, 'listings_updated')
    else:
        increment_counter(conn, run_id, 'listings_unchanged')

    if detail_failed:
        increment_counter(conn, run_id, 'listings_errored')

    tag    = 'NEW' if is_new else 'PRICE CHANGE' if price_changed else 'unchanged'
    suffix = ' (search-only)' if detail_failed else ''
    print(f'[stage2] {listing.id} → {tag}{suffix}')

    return {'listing_id': listing_id, 'is_new': is_new, 'price_changed': price_changed}


def run_stage2_workers(
    job_queue: queue.Queue,
    database_url: str,
    concurrency: int = 1,
) -> None:
    print(f'[stage2] Workers started. Concurrency: {concurrency}')

    jobs = []
    while not job_queue.empty():
        try:
            jobs.append(job_queue.get_nowait())
        except queue.Empty:
            break

    if not jobs:
        print('[stage2] No jobs to process.')
        return

    print(f'[stage2] Processing {len(jobs)} listings...')

    with ThreadPoolExecutor(max_workers=concurrency) as executor:
        futures = {
            executor.submit(_process_job, job, database_url): job
            for job in jobs
        }
        for future in as_completed(futures):
            try:
                future.result()
            except Exception as e:
                job = futures[future]
                print(f'[stage2] Job failed for {job["listing"].id}: {e}')

    print(f'[stage2] All {len(jobs)} jobs complete.')