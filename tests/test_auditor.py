import asyncio
import unittest
from app.auditor import check_adult, format_expiration, audit_iptv_server, pick_test_channel
from app.parser import IPTVServer

class TestAuditor(unittest.TestCase):
    def test_pick_test_channel_priority(self):
        # 1. Prioritizes BBC News
        sample_streams = [
            {"stream_id": 1, "name": "=== US ENTERTAINMENT ==="},
            {"stream_id": 2, "name": "US: HBO HD"},
            {"stream_id": 3, "name": "UK: BBC News HD"},
            {"stream_id": 4, "name": "US: CNN International"},
        ]
        name, sid = pick_test_channel(sample_streams)
        self.assertEqual(name, "UK: BBC News HD")
        self.assertEqual(sid, "3")

        # 2. Falls back to CNN or other news channel
        no_bbc = [
            {"stream_id": 10, "name": "FR: Canal+"},
            {"stream_id": 11, "name": "US: CNN Live"},
        ]
        name, sid = pick_test_channel(no_bbc)
        self.assertEqual(name, "US: CNN Live")
        self.assertEqual(sid, "11")

        # 3. Falls back to first valid non-header channel
        no_news = [
            {"stream_id": 20, "name": "### VIP MOVIES ###"},
            {"stream_id": 21, "name": "Sky Cinema Action"},
        ]
        name, sid = pick_test_channel(no_news)
        self.assertEqual(name, "Sky Cinema Action")
        self.assertEqual(sid, "21")

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

    def test_m3u_endpoint(self):
        from starlette.testclient import TestClient
        from app.main import app
        client = TestClient(app)

        # 1. Direct stream m3u
        resp = client.get("/api/play/m3u?url=http://example.com/live/u/p/1.ts&title=BBC%20News")
        self.assertEqual(resp.status_code, 200)
        self.assertIn("#EXTINF:-1,BBC News", resp.text)
        self.assertIn("http://example.com/live/u/p/1.ts", resp.text)
        self.assertEqual(resp.headers["content-type"], "audio/x-mpegurl; charset=utf-8")

        # 2. Proxy stream m3u (for VPN routing)
        resp_proxy = client.get("/api/play/m3u?url=http://example.com/live/u/p/1.ts&title=BBC%20News&proxy=true")
        self.assertEqual(resp_proxy.status_code, 200)
        self.assertIn("/api/stream/proxy?url=", resp_proxy.text)

        # 3. Invalid stream proxy check
        resp_invalid = client.get("/api/stream/proxy?url=ftp://bad-url")
        self.assertEqual(resp_invalid.status_code, 400)

if __name__ == "__main__":
    unittest.main()
