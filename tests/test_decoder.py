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

    def test_ignore_channel_streams_in_m3u(self):
        # Channel stream URLs in an M3U file should NOT be returned as external playlist sources
        m3u_text = """#EXTM3U
#EXTINF:-1,Channel 1
http://example.com:8080/live/user1/pass1/1001.ts
#EXTINF:-1,Channel 2
http://example.com:8080/live/user1/pass1/1002.ts
https://paste.sh/real-source#key123
"""
        urls = extract_urls_from_input(m3u_text)
        self.assertEqual(len(urls), 1)
        self.assertEqual(urls[0], "https://paste.sh/real-source#key123")

    def test_naked_paste_sh_url_extraction(self):
        input_str = "paste.sh/7eI0JaKO#13sFCkA_Ilf6COft6az-CxHS"
        urls = extract_urls_from_input(input_str)
        self.assertEqual(len(urls), 1)
        self.assertEqual(urls[0], "https://paste.sh/7eI0JaKO#13sFCkA_Ilf6COft6az-CxHS")

    def test_paste_sh_v3_decryption_and_unicode_parsing(self):
        from app.decoder import decrypt_paste_sh
        from app.parser import extract_iptv_servers
        import base64
        import hashlib
        from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
        from cryptography.hazmat.backends import default_backend

        # Encrypt a test v3 payload using PBKDF2 sha512 iter=1
        salt = b"12345678"
        passphrase = "7eI0JaKO13sFCkA_Ilf6COft6az-CxHShttps://paste.sh"
        derived = hashlib.pbkdf2_hmac("sha512", passphrase.encode(), salt, iterations=1, dklen=48)
        key, iv = derived[:32], derived[32:48]

        plaintext = (
            "Subject: 📋🔐 paste.sh\n\n"
            "𝙋𝙤𝙧𝙩𝙖𝙡 : http://pqgmyhja.msostvip.com\n"
            "𝙐𝙨𝙚𝙧 : MD2ST667\n"
            "𝙋𝙖𝙨𝙨 : 85FTYAMV\n"
            "𝙋𝙤𝙧𝙩 : 80\n\n"
            "Portal : http://hr129.vmyjfhnzpw.top\n"
            "User : vip4591765831780\n"
            "Pass : 4e1a0860d388\n"
            "Port : 8080\n"
        )
        data = plaintext.encode("utf-8")
        pad_len = 16 - (len(data) % 16)
        padded = data + bytes([pad_len]) * pad_len

        cipher = Cipher(algorithms.AES(key), modes.CBC(iv), backend=default_backend())
        enc = cipher.encryptor()
        ct = enc.update(padded) + enc.finalize()
        b64_payload = base64.b64encode(b"Salted__" + salt + ct)

        decrypted = decrypt_paste_sh(b64_payload, passphrase)
        self.assertIn("MD2ST667", decrypted)
        self.assertIn("vip4591765831780", decrypted)

        # Parse servers from decrypted text
        servers = extract_iptv_servers(decrypted)
        self.assertEqual(len(servers), 2)
        self.assertEqual(servers[0].host, "http://pqgmyhja.msostvip.com:80")
        self.assertEqual(servers[0].username, "MD2ST667")
        self.assertEqual(servers[0].password, "85FTYAMV")

        self.assertEqual(servers[1].host, "http://hr129.vmyjfhnzpw.top:8080")
        self.assertEqual(servers[1].username, "vip4591765831780")
        self.assertEqual(servers[1].password, "4e1a0860d388")

if __name__ == "__main__":
    unittest.main()
