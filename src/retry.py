import random
import time
import httpx
from requests.exceptions import RequestException

def retry(call, attempts=6, sleeper=time.sleep):
    for attempt in range(attempts):
        try:
            return call()
        except Exception as exc:
            status = getattr(getattr(exc, 'resp', None), 'status', None) or getattr(exc, 'code', None) or getattr(getattr(exc,'response',None),'status_code',None)
            transient = isinstance(exc, (TimeoutError, ConnectionError, OSError, httpx.TransportError, RequestException)) or status in (408, 429, 500, 502, 503, 504)
            if not transient or attempt == attempts - 1:
                raise
            header = getattr(getattr(exc, 'resp', None), 'get', lambda *_: None)('retry-after')
            delay = float(header) if str(header).isdigit() else min(60, 2 ** attempt) + random.uniform(0, 1)
            sleeper(min(delay, 120))

class RateLimiter:
    def __init__(self, rpm, clock=time.monotonic, sleeper=time.sleep):
        self.interval = 60 / rpm
        self.clock, self.sleep = clock, sleeper
        self.next_call = 0.0

    def wait(self):
        delay = self.next_call - self.clock()
        if delay > 0:
            self.sleep(delay)
        self.next_call = self.clock() + self.interval
