import time
import random
import requests


def _jitter(min_ms: int, max_ms: int) -> float:
    return random.randint(min_ms, max_ms) / 1000


class RateLimitedSession(requests.Session):
    def __init__(self):
        super().__init__()
        self._last_request_time: float = 0


        self.headers.update({
            'User-Agent': (
                'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) '
                'AppleWebKit/537.36 (KHTML, like Gecko) '
                'Chrome/125.0.0.0 Safari/537.36'
            ),
            'Accept': (
                'text/html,application/xhtml+xml,application/xml;'
                'q=0.9,image/avif,image/webp,*/*;q=0.8'
            ),
            'Accept-Language': 'en-GB,en;q=0.9',
            'Cache-Control': 'no-cache',
            'Referer': 'https://www.rightmove.co.uk/',
        })

    def request(self, method, url, **kwargs):
        elapsed = time.time() - self._last_request_time
        delay = _jitter(500, 1500)  # 0.5–1.5s for dev; increase to (1000, 3000) for production
        if elapsed < delay:
            time.sleep(delay - elapsed)

        self._last_request_time = time.time()

        kwargs.setdefault('timeout', 20)
        response = super().request(method, url, **kwargs)

        if response.status_code == 429:
            retry_after = int(response.headers.get('Retry-After', 30))
            print(f'[http] Rate limited (429). Waiting {retry_after}s...')
            time.sleep(retry_after)
            self._last_request_time = time.time()
            response = super().request(method, url, **kwargs)

        return response


def create_http_client() -> RateLimitedSession:
    session = RateLimitedSession()

    print('[http] Warming up session...')
    session.get('https://www.rightmove.co.uk/')
    time.sleep(2)  # pause like a human who just opened the page
    print('[http] Session ready.')

    return session