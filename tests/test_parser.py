import unittest
from app.parser import extract_iptv_servers, parse_m3u_or_api_url

class TestParser(unittest.TestCase):
    def test_parse_m3u_url(self):
        url = "http://totalhost.org:8080/get.php?username=00671987&password=61791210&type=m3u_plus&output=m3u8"
        server = parse_m3u_or_api_url(url)
        self.assertIsNotNone(server)
        self.assertEqual(server.host, "http://totalhost.org:8080")
        self.assertEqual(server.username, "00671987")
        self.assertEqual(server.password, "61791210")

    def test_parse_key_value_blocks(self):
        text = """
        Host: n2ip.tv:2095
        User: Christian1
        Pass: christian1
        Status: Active
        Expires: 2027-07-21
        --------------------------------------------------------------------------------------------------------------
        Host: n2ip.tv:2095
        User: Martin1
        Pass: Martin1
        Status: Active
        """
        servers = extract_iptv_servers(text)
        self.assertEqual(len(servers), 2)
        self.assertEqual(servers[0].host, "http://n2ip.tv:2095")
        self.assertEqual(servers[0].username, "Christian1")
        self.assertEqual(servers[0].password, "christian1")
        self.assertEqual(servers[1].username, "Martin1")

    def test_deduplication(self):
        text = """
        http://totalhost.org:8080/get.php?username=00671987&password=61791210
        http://totalhost.org:8080/get.php?username=00671987&password=61791210
        Host: totalhost.org:8080
        User: 00671987
        Pass: 61791210
        """
        servers = extract_iptv_servers(text)
        self.assertEqual(len(servers), 1)

if __name__ == "__main__":
    unittest.main()
