import base64
import unittest
from app.decoder import decode_token_to_url, extract_urls_from_input

class TestDecoder(unittest.TestCase):
    def test_decode_base64_url(self):
        raw_url = "https://paste.sh/w4TbRm0Z#n94NYqmbOOK3y2rdrh7efmfM"
        encoded = base64.b64encode(raw_url.encode()).decode()
        decoded = decode_token_to_url(encoded)
        self.assertEqual(decoded, raw_url)

    def test_extract_urls_multiple_formats(self):
        input_str = """
        aHR0cHM6Ly9wYXN0ZS5zaC93NFRiUm0wWiNuOTROWXFtYk9PSzN5MnJkcmg3ZWZtZk0= , aHR0cHM6Ly9wYXN0ZS5zaC9fWnhsQTlWNSMyZVgyT1U3cjdwODNuUnQ4V1M1V2JKUVg=
        https://direct.example.com/test#key
        """
        urls = extract_urls_from_input(input_str)
        self.assertEqual(len(urls), 3)
        self.assertIn("https://paste.sh/w4TbRm0Z#n94NYqmbOOK3y2rdrh7efmfM", urls)
        self.assertIn("https://paste.sh/_ZxlA9V5#2eX2OU7r7p83nRt8WS5WbJQX", urls)
        self.assertIn("https://direct.example.com/test#key", urls)

if __name__ == "__main__":
    unittest.main()
