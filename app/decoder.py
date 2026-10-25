import base64
import binascii
import codecs
import hashlib
import logging
import re
import subprocess
from typing import List, Tuple
from urllib.parse import urlparse

import httpx

from app.config import config

logger = logging.getLogger(__name__)

# Try to import cryptography; if not available, fallback to openssl CLI
try:
    from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
    from cryptography.hazmat.backends import default_backend
    HAS_CRYPTOGRAPHY = True
except ImportError:
    HAS_CRYPTOGRAPHY = False


def evp_bytes_to_key(passphrase: bytes, salt: bytes, key_len: int = 32, iv_len: int = 16) -> Tuple[bytes, bytes]:
    """OpenSSL EVP_BytesToKey implementation with sha512."""
    d = b""
    d_i = b""
    while len(d) < (key_len + iv_len):
        d_i = hashlib.sha512(d_i + passphrase + salt).digest()
        d += d_i
    return d[:key_len], d[key_len : key_len + iv_len]


def decrypt_paste_sh_crypto(ciphertext_b64: bytes, passphrase: str) -> str:
    """Decrypt paste.sh payload using python cryptography library."""
    ciphertext_raw = base64.b64decode(ciphertext_b64)
    if ciphertext_raw[:8] != b"Salted__":
        raise ValueError("Invalid OpenSSL ciphertext header (missing Salted__)")
    salt = ciphertext_raw[8:16]
    data = ciphertext_raw[16:]

    key, iv = evp_bytes_to_key(passphrase.encode("utf-8"), salt, key_len=32, iv_len=16)
    cipher = Cipher(algorithms.AES(key), modes.CBC(iv), backend=default_backend())
    decryptor = cipher.decryptor()
    padded = decryptor.update(data) + decryptor.finalize()

    pad_len = padded[-1]
    if pad_len > 16:
        raise ValueError("Invalid PKCS7 padding")
    return padded[:-pad_len].decode("utf-8", errors="ignore")


def decrypt_paste_sh_openssl(ciphertext_b64: bytes, passphrase: str) -> str:
    """Fallback decrypt paste.sh payload using openssl CLI."""
    cmd = [
        "openssl",
        "enc",
        "-d",
        "-aes-256-cbc",
        "-md",
        "sha512",
        "-pass",
        f"pass:{passphrase}",
        "-iter",
        "1",
        "-base64",
    ]
    proc = subprocess.run(cmd, input=ciphertext_b64, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    if proc.returncode != 0:
        raise RuntimeError(f"OpenSSL decryption failed: {proc.stderr.decode('utf-8', errors='ignore')}")
    return proc.stdout.decode("utf-8", errors="ignore")


def decrypt_paste_sh(ciphertext_b64: bytes, passphrase: str) -> str:
    """Decrypt paste.sh encrypted string using best available method."""
    if HAS_CRYPTOGRAPHY:
        try:
            return decrypt_paste_sh_crypto(ciphertext_b64, passphrase)
        except Exception as e:
            logger.warning("Python cryptography decryption failed, trying OpenSSL CLI: %s", e)
    return decrypt_paste_sh_openssl(ciphertext_b64, passphrase)


def decode_token_to_url(token: str) -> str:
    """
    Decodes an individual token into a URL.
    Handles raw URLs, Base64 strings, and UUEncoded strings.
    """
    token = token.strip()
    if not token:
        return ""

    # Direct URL
    if token.startswith("http://") or token.startswith("https://"):
        return token

    # Check for Unix uuencode formatted text
    if "begin " in token and "\n" in token:
        try:
            decoded_bytes = codecs.decode(token.encode("utf-8"), "uu_codec")
            decoded_str = decoded_bytes.decode("utf-8", errors="ignore").strip()
            if decoded_str.startswith("http://") or decoded_str.startswith("https://"):
                return decoded_str
        except Exception:
            pass

    # Try standard uuencode line format
    try:
        decoded_bytes = binascii.a2b_uu(token.encode("utf-8"))
        decoded_str = decoded_bytes.decode("utf-8", errors="ignore").strip()
        if decoded_str.startswith("http://") or decoded_str.startswith("https://"):
            return decoded_str
    except Exception:
        pass

    # Base64 decoding (the most common scheme, including sample URLs)
    clean_b64 = re.sub(r"[^A-Za-z0-9+/=_-]", "", token)
    if len(clean_b64) >= 8:
        # Standardize URL-safe base64
        std_b64 = clean_b64.replace("-", "+").replace("_", "/")
        # Pad properly
        padded = std_b64 + "=" * (-len(std_b64) % 4)
        try:
            decoded_bytes = base64.b64decode(padded)
            decoded_str = decoded_bytes.decode("utf-8", errors="ignore").strip()
            if decoded_str.startswith("http://") or decoded_str.startswith("https://"):
                return decoded_str
        except Exception:
            pass

    return ""


def is_stream_channel_url(url: str) -> bool:
    """
    Returns True if the URL is an individual channel/movie/series stream
    (e.g. http://host:port/live/user/pass/123.ts), which should be parsed directly
    as credentials rather than fetched as an external playlist source.
    """
    try:
        parsed = urlparse(url)
        parts = [p for p in parsed.path.split("/") if p]
        if len(parts) >= 4 and parts[0] in ("live", "movie", "series"):
            return True
        if parts and parts[-1].endswith((".ts", ".mp4", ".mkv", ".avi")):
            return True
    except Exception:
        pass
    return False


def extract_urls_from_input(user_input: str) -> List[str]:
    """
    Parses user input containing multiple lines, comma-separated tokens,
    or mixed raw URLs and encoded strings.
    Ignores individual channel stream URLs (which are parsed directly by parser).
    """
    # Split by commas or newlines
    tokens = re.split(r"[\n,\r\t]+", user_input)
    urls: List[str] = []
    seen = set()

    for token in tokens:
        token = token.strip()
        if not token:
            continue

        # Extract embedded http/https URLs if pasted inline
        raw_matches = re.findall(r"https?://[^\s\"'<>]+", token)
        if raw_matches:
            for u in raw_matches:
                if not is_stream_channel_url(u) and u not in seen:
                    seen.add(u)
                    urls.append(u)
            continue

        url = decode_token_to_url(token)
        if url and not is_stream_channel_url(url) and url not in seen:
            seen.add(url)
            urls.append(url)

    return urls


async def fetch_url_content(url: str, client: httpx.AsyncClient) -> Tuple[str, str]:
    """
    Fetches the content of a target URL.
    If the URL is a paste.sh encrypted link (e.g. https://paste.sh/<id>#<key>),
    it fetches the raw ciphertext and decrypts it with the fragment key.
    Returns (url, content_text).
    """
    parsed = urlparse(url)
    fragment = parsed.fragment

    # Check for paste.sh with decryption key
    if "paste.sh" in parsed.netloc and fragment:
        paste_url = f"{parsed.scheme}://{parsed.netloc}{parsed.path}"
        paste_id = parsed.path.strip("/").split("/")[-1]
        client_key = fragment

        resp = await client.get(
            f"{paste_url}.txt",
            headers={
                "Accept": "text/plain, text/vnd.paste.sh-v2, text/vnd.paste.sh-v3",
                "User-Agent": config.USER_AGENT,
            },
            timeout=config.REQUEST_TIMEOUT,
        )
        resp.raise_for_status()

        lines = resp.content.split(b"\n", 1)
        server_key = lines[0].decode("utf-8", errors="ignore").strip()
        ciphertext_b64 = lines[1].strip() if len(lines) > 1 else b""

        passphrase = f"{paste_id}{server_key}{client_key}https://paste.sh"
        plaintext = decrypt_paste_sh(ciphertext_b64, passphrase)
        return url, plaintext

    # Standard URL or raw pastebin
    resp = await client.get(
        url,
        headers={"User-Agent": config.USER_AGENT},
        follow_redirects=True,
        timeout=config.REQUEST_TIMEOUT,
    )
    resp.raise_for_status()
    return url, resp.text
