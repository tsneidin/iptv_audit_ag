import asyncio
import unittest
from app.auditor import check_adult, format_expiration, audit_iptv_server
from app.parser import IPTVServer

class TestAuditor(unittest.TestCase):
    def test_check_adult_keywords(self):
        self.assertTrue(check_adult("VIP | Adult XXX"))
        self.assertTrue(check_adult("For Adults Only"))
        self.assertFalse(check_adult("US: HBO HD"))
        self.assertTrue(check_adult("Swedish 18+ Live"))
        self.assertFalse(check_adult("Sport 1 Germany"))

    def test_format_expiration(self):
        date_str, countdown = format_expiration(None)
        self.assertEqual(date_str, "Unlimited")

        # Future timestamp
        date_str, countdown = format_expiration(1893456000)
        self.assertEqual(date_str, "2030-01-01")
        self.assertIn("Expires in", countdown)

    def test_dead_host_cache_skipping(self):
        cache = {"http://dead-server.xyz:80": "Connection Timeout"}
        srv = IPTVServer(host="http://dead-server.xyz:80", username="user1", password="pw1")
        
        async def run_check():
            # Pass dummy client None since cached host shouldn't invoke client
            return await audit_iptv_server(srv, None, dead_host_cache=cache)
            
        res = asyncio.run(run_check())
        self.assertFalse(res.is_working)
        self.assertEqual(res.status, "Connection Timeout")
        self.assertIn("Host previously failed", res.error_message)

if __name__ == "__main__":
    unittest.main()
