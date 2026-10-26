import asyncio
from contextlib import asynccontextmanager
import logging
import random
import time
from typing import Dict, Set

logger = logging.getLogger(__name__)


class HostRateLimiter:
    """
    Adaptive per-host rate limiter.
    In 'adaptive' mode (default), runs at maximum unthrottled speed (zero delay).
    If and only if a host returns HTTP 503 / 429 / 502, it dynamically switches that
    specific host into throttled safe mode (concurrency cap, cooldown, inter-request pacing, and retries).
    Other hosts that don't trigger errors continue at unthrottled full speed.
    """

    PACING_PRESETS = {
        "adaptive": {
            "max_per_host": 2,
            "min_delay": 0.35,
            "max_retries": 2,
            "backoff_base": 1.8,
            "max_consecutive_errors": 4,
            "always_throttled": False,
        },
        "safe": {
            "max_per_host": 2,
            "min_delay": 0.35,
            "max_retries": 2,
            "backoff_base": 2.0,
            "max_consecutive_errors": 4,
            "always_throttled": True,
        },
        "stealth": {
            "max_per_host": 1,
            "min_delay": 0.75,
            "max_retries": 3,
            "backoff_base": 3.0,
            "max_consecutive_errors": 3,
            "always_throttled": True,
        },
        "fast": {
            "max_per_host": 5,
            "min_delay": 0.05,
            "max_retries": 1,
            "backoff_base": 1.0,
            "max_consecutive_errors": 5,
            "always_throttled": False,
        },
    }

    def __init__(self, mode: str = "adaptive"):
        cfg = self.PACING_PRESETS.get(mode, self.PACING_PRESETS["adaptive"])
        self.mode = mode
        self.max_per_host: int = cfg["max_per_host"]
        self.min_delay: float = cfg["min_delay"]
        self.max_retries: int = cfg["max_retries"]
        self.backoff_base: float = cfg["backoff_base"]
        self.max_consecutive_errors: int = cfg["max_consecutive_errors"]
        self.always_throttled: bool = cfg["always_throttled"]

        self._throttled_hosts: Set[str] = set()
        self._semaphores: Dict[str, asyncio.Semaphore] = {}
        self._last_request_time: Dict[str, float] = {}
        self._cooldown_until: Dict[str, float] = {}
        self._consecutive_errors: Dict[str, int] = {}
        self._lock = asyncio.Lock()

    def is_host_throttled(self, host: str) -> bool:
        """Returns True if the host is configured or dynamically marked to be throttled."""
        if self.always_throttled:
            return True
        return host in self._throttled_hosts

    def get_semaphore(self, host: str) -> asyncio.Semaphore:
        if host not in self._semaphores:
            self._semaphores[host] = asyncio.Semaphore(self.max_per_host)
        return self._semaphores[host]

    @asynccontextmanager
    async def throttle(self, host: str):
        """
        Context manager for host-level concurrency and pacing.
        FAST PATH: If host hasn't encountered errors, runs immediately without delay.
        THROTTLED PATH: If host returned 503/429, enforces concurrency cap, cooldown, and delay.
        """
        if not self.is_host_throttled(host):
            # Fast path: unthrottled maximum speed
            yield
            return

        # Throttled path: domain is under rate-limiting protection
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

            # 2. Pacing delay to avoid tripping burst limits again
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
        Dynamically activates throttled mode for this host, increments error count,
        and sets an exponential backoff cooldown with jitter.
        """
        # Dynamically activate throttling for this specific host
        self._throttled_hosts.add(host)

        count = self._consecutive_errors.get(host, 0) + 1
        self._consecutive_errors[host] = count

        # Exponential backoff: base * (1.5 ** count) + random jitter
        jitter = random.uniform(0.2, 0.6)
        cooldown_secs = (self.backoff_base * (1.5 ** min(count - 1, 4))) + jitter
        now = time.time()
        self._cooldown_until[host] = max(self._cooldown_until.get(host, 0), now + cooldown_secs)
        logger.info(
            "Host %s dynamically throttled due to HTTP %d (count %d): cooling down for %.2fs",
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
