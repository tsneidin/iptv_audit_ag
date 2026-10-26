import asyncio
import time
import unittest
from unittest.mock import AsyncMock, MagicMock, patch
import httpx

from app.auditor import audit_iptv_server, get_player_headers
from app.limiter import HostRateLimiter
from app.parser import IPTVServer


class TestHostRateLimiter(unittest.TestCase):
    def test_presets_configuration(self):
        safe = HostRateLimiter(mode="safe")
        self.assertEqual(safe.max_per_host, 2)
        self.assertEqual(safe.min_delay, 0.35)

        stealth = HostRateLimiter(mode="stealth")
        self.assertEqual(stealth.max_per_host, 1)
        self.assertEqual(stealth.min_delay, 0.75)

        fast = HostRateLimiter(mode="fast")
        self.assertEqual(fast.max_per_host, 5)
        self.assertEqual(fast.min_delay, 0.10)

    def test_rate_limited_cooldown_and_recovery(self):
        limiter = HostRateLimiter(mode="safe")
        host = "http://provider.tv:8080"

        self.assertFalse(limiter.is_cooling_down(host))
        self.assertFalse(limiter.should_mark_dead(host))

        # Report 503
        cooldown = limiter.report_rate_limited(host, 503)
        self.assertTrue(cooldown > 0)
        self.assertTrue(limiter.is_cooling_down(host))
        self.assertFalse(limiter.should_mark_dead(host))

        # Report success clears error count
        limiter.report_success(host)
        self.assertFalse(limiter.should_mark_dead(host))

        # Repeated 503s hit threshold
        for _ in range(4):
            limiter.report_rate_limited(host, 503)
        self.assertTrue(limiter.should_mark_dead(host))

    def test_user_agents_rotation(self):
        headers1 = get_player_headers()
        self.assertIn("User-Agent", headers1)
        self.assertIn("Accept", headers1)
        self.assertIn("Connection", headers1)
        self.assertEqual(headers1["Connection"], "keep-alive")

    def test_throttle_concurrency(self):
        async def run_test():
            limiter = HostRateLimiter(mode="safe")
            limiter.min_delay = 0.01  # fast for testing
            active_counts = []
            current_active = 0

            async def worker(host):
                nonlocal current_active
                async with limiter.throttle(host):
                    current_active += 1
                    active_counts.append(current_active)
                    await asyncio.sleep(0.02)
                    current_active -= 1

            tasks = [asyncio.create_task(worker("http://samehost.com")) for _ in range(5)]
            await asyncio.gather(*tasks)
            # max_per_host is 2, so current_active should never exceed 2
            self.assertTrue(max(active_counts) <= 2)

        asyncio.run(run_test())

    def test_audit_503_retry_and_backoff(self):
        async def run_test():
            limiter = HostRateLimiter(mode="safe")
            limiter.backoff_base = 0.01  # fast backoff for test
            limiter.max_retries = 2

            srv = IPTVServer(host="http://fragile-host.tv", username="user1", password="pass1")
            dead_cache = {}

            # Mock client that returns 503 on first try, then 200 on retry
            mock_client = AsyncMock()
            resp_503 = MagicMock()
            resp_503.status_code = 503

            resp_200 = MagicMock()
            resp_200.status_code = 200
            resp_200.json.return_value = {
                "user_info": {
                    "auth": 1,
                    "status": "Active",
                    "exp_date": "1893456000",
                    "max_connections": 1,
                    "active_cons": 0,
                }
            }

            mock_client.get = AsyncMock(side_effect=[resp_503, resp_200, MagicMock(status_code=200, json=MagicMock(return_value=[]))])

            res = await audit_iptv_server(
                srv,
                mock_client,
                probe_stream=False,
                audit_mode="turbo",
                dead_host_cache=dead_cache,
                rate_limiter=limiter,
            )

            # Verification:
            # 1. Host was NOT killed on first 503
            self.assertNotIn(srv.host, dead_cache)
            # 2. Successfully recovered on retry
            self.assertTrue(res.is_working)
            self.assertEqual(res.status, "Active")

        asyncio.run(run_test())


if __name__ == "__main__":
    unittest.main()
