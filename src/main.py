import os
import queue
import faulthandler

import psycopg2
from dotenv import load_dotenv

from .scraper.http_client import create_http_client
from .scraper.stage1 import run_stage1
from .scraper.stage2 import run_stage2_workers

load_dotenv()
faulthandler.enable()

def main():
    database_url = os.environ['DATABASE_URL']
    location_id  = os.getenv('LOCATION_ID', 'REGION^87490')
    max_pages    = int(os.getenv('MAX_PAGES', 0)) or None
    concurrency  = int(os.getenv('WORKER_CONCURRENCY', '1'))

    http = create_http_client()
    conn = psycopg2.connect(database_url)
    job_queue: queue.Queue = queue.Queue()

    try:
        run_id, total_discovered = run_stage1(
            http_client=http,
            conn=conn,
            job_queue=job_queue,
            location_identifier=location_id,
            max_pages=max_pages,
        )
        print(f'[main] Stage 1 complete (run={run_id}). {total_discovered} listings queued.')

        run_stage2_workers(
            job_queue=job_queue,
            database_url=database_url,
            concurrency=concurrency,
        )

        print('[main] All done.')
    finally:
        conn.close()


if __name__ == '__main__':
    main()