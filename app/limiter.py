import asyncio
from contextlib import asynccontextmanager
import logging
import random
import time
from typing import Dict

logger = logging.getLogger(__name__)

class HostRateLimiter:
    """
    Per-host concurrency limiter, adaptive pacing, and anti-ban cooldown manager.
    Prevents tripping anti-DDoS / Nginx limit_req (HTTP 503 / 429) when auditing
    multiple accounts on the same IPTV provider.
    """

    PACING_PRESETS = {
        "fast": {
            "max_per_host": 5,
            "min_delay": 0.10,
            "max_retries": 1,
            "backoff_base": 1.0,
            "max_consecutive_errors": 5,
        },
        "safe": {
            "max_per_host": 2,
            "min_delay": 0.35,
            "max_retries": 2,
            "backoff_base": 2.0,
            "max_consecutive_errors": 4,
        },
        "stealth": {
            "max_per_host": 1,
            "min_delay": 0.75,
            "max_retries": 3,
            "backoff_base": 3.0,
            "max_consecutive_errors": 3,
        },
    }

    def __init__(self, mode: str = "safe"):
        cfg = self.PACING_PRESETS.get(mode, self.PACING_PRESETS["safe"])
        self.mode = mode
        self.max_per_host: int = cfg["max_per_host"]
        self.min_delay: float = cfg["min_delay"]
        self.max_retries: int = cfg["max_retries"]
        self.backoff_base: float = cfg["backoff_base"]
        self.max_consecutive_errors: int = cfg["max_consecutive_errors"]

        self._semaphores: Dict[str, asyncio.Semaphore] = {}
        self._last_request_time: Dict[str, float] = {}
        self._cooldown_until: Dict[str, float] = {}
        self._consecutive_errors: Dict[str, int] = {}
        self._lock = asyncio.Lock()

    def get_semaphore(self, host: str) -> asyncio.Semaphore:
        if host not in self._semaphores:
            self._semaphores[host] = asyncio.Semaphore(self.max_per_host)
        return self._semaphores[host]

    @asynccontextmanager
    async def throttle(self, host: str):
        """
        Context manager that enforces per-host concurrency, honors cooldowns,
        and spaces out requests to the same host with small random jitter.
        """
        async with self._lock:
            sem = self.get_semaphore(host)

        async with sem:
            # 1. Honor active host cooldown from previous 503/429
            now = time.time()
            cooldown = self._cooldown_until.get(host, 0)
            if cooldown > now:
                wait_time = cooldown - now
                logger.debug("Host %s in cooldown: waiting %.2fs", host, wait_time)
                await asyncio.sleep(wait_time)

            # 2. Pacing delay to avoid burst limits
            last_time = self._last_request_time.get(host, 0)
            elapsed = time.time() - last_time
            if elapsed < self.min_delay:
                jitter = random.uniform(0.05, 0.20)
                delay = (self.min_delay - elapsed) + jitter
                await asyncio.sleep(delay)

            self._last_request_time[host] = time.time()
            yield

    def report_rate_limited(self, host: str, status_code: int = 503) -> float:
        """
        Registers a 503/429/502 response on a host.
        Increases consecutive error count and sets an exponential cooldown with jitter.
        Returns the duration of the cooldown in seconds.
        """
        count = self._consecutive_errors.get(host, 0) + 1
        self._consecutive_errors[host] = count

        # Exponential backoff: base * (1.5 ** count) + random jitter
        jitter = random.uniform(0.3, 0.8)
        cooldown_secs = (self.backoff_base * (1.5 ** min(count - 1, 4))) + jitter
        now = time.time()
        self._cooldown_until[host] = max(self._cooldown_until.get(host, 0), now + cooldown_secs)
        logger.info(
            "Host %s rate-limited (HTTP %d, count %d): backing off for %.2fs",
            host, status_code, count, cooldown_secs
        )
        return cooldown_secs

    def report_success(self, host: str):
        """Clears consecutive error counter on a successful API exchange."""
        self._consecutive_errors[host] = 0

    def is_cooling_down(self, host: str) -> bool:
        return self._cooldown_until.get(host, 0) > time.time()

    def should_mark_dead(self, host: str) -> bool:
        """
        Returns True only if the host has repeatedly failed with 503/429
        across multiple distinct accounts even after consecutive cooldowns.
        """
        return self._consecutive_errors.get(host, 0) >= self.max_consecutive_errors
