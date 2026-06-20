import queue
import time
from urllib.parse import urlencode

from ..extractors.search import extract_search_listings, extract_pagination
from ..storage.listings import create_scrape_run, update_scrape_run, increment_counter


BASE_URL    = 'https://www.rightmove.co.uk'
SEARCH_PATH = '/property-for-sale/find.html'


def run_stage1(
    http_client,
    conn,
    job_queue: queue.Queue,
    location_identifier: str,
    max_pages: int = None,
) -> tuple:
    
    run_id = create_scrape_run(conn, location_identifier)
    print(f'[stage1] Run {run_id} started for {location_identifier}')

    index           = 0
    total_discovered = 0
    total_errors    = 0
    last_index      = None   
    page_size       = 24     

    try:
        while True:
            url = _build_url(location_identifier, index)

            try:
                response = http_client.get(url)
                html = response.text
            except Exception as e:
                print(f'[stage1] Failed to fetch index={index}: {e}')
                total_errors += 1
                index += page_size
                continue

            listings   = extract_search_listings(html)
            pagination = extract_pagination(html)

            if last_index is None:
                last_index = pagination['last']

            # Use the actual number of listings returned, not the assumed 24,
            # because Rightmove sometimes injects a 25th promoted listing
            page_size = max(pagination['page_size'], len(listings), 1)

            for listing in listings:
                job_queue.put({'listing': listing, 'run_id': run_id})
                total_discovered += 1
                increment_counter(conn, run_id, 'listings_discovered')

            print(
                f'[stage1] index={index}: +{len(listings)} listings '
                f'(total={total_discovered}, resultCount={pagination["result_count"]})'
            )

            index += page_size

            if last_index is not None and index > last_index:
                break
            if max_pages is not None and total_discovered >= max_pages * page_size:
                break

        status = 'partial' if total_errors > 0 else 'completed'
        update_scrape_run(conn, run_id, status, discovered=total_discovered, errored=total_errors)
        print(f'[stage1] Run {run_id} complete. Discovered {total_discovered} listings.')
        return run_id, total_discovered

    except Exception as e:
        update_scrape_run(conn, run_id, 'failed', error_message=str(e))
        raise


def _build_url(location_identifier: str, index: int) -> str:
    params = urlencode({
        'locationIdentifier': location_identifier,
        'index': index,
        'sortType': 6,      # most recently updated — important for incremental runs
        'channel': 'BUY',
        'radius': '0.0',
    })
    return f'{BASE_URL}{SEARCH_PATH}?{params}'
