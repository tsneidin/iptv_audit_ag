import re
from typing import Dict, List, Optional
from urllib.parse import parse_qs, urlparse
from pydantic import BaseModel


class IPTVServer(BaseModel):
    host: str
    username: str
    password: str
    source_url: Optional[str] = ""
    raw_m3u_url: Optional[str] = ""

    @property
    def key(self) -> str:
        """Unique key for deduplication."""
        clean_host = self.host.rstrip("/").lower()
        return f"{clean_host}|{self.username}|{self.password}"

    @property
    def standard_m3u_url(self) -> str:
        """Constructs a clean M3U Plus URL."""
        if self.raw_m3u_url:
            return self.raw_m3u_url
        clean_host = self.host.rstrip("/")
        return f"{clean_host}/get.php?username={self.username}&password={self.password}&type=m3u_plus&output=m3u8"


def normalize_host(host: str) -> str:
    """Ensures host has protocol (default http://) and strips trailing slash."""
    host = host.strip()
    if not host.startswith("http://") and not host.startswith("https://"):
        host = f"http://{host}"
    return host.rstrip("/")


def parse_m3u_or_api_url(url_str: str, source_url: str = "") -> Optional[IPTVServer]:
    """Extracts credentials from a get.php or player_api.php URL."""
    try:
        parsed = urlparse(url_str.strip())
        if not parsed.netloc:
            return None

        qs = parse_qs(parsed.query)
        username = qs.get("username", [None])[0] or qs.get("user", [None])[0]
        password = qs.get("password", [None])[0] or qs.get("pass", [None])[0]

        host = f"{parsed.scheme}://{parsed.netloc}"

        if username and password:
            return IPTVServer(
                host=host,
                username=username,
                password=password,
                source_url=source_url,
                raw_m3u_url=url_str.strip(),
            )

        path_parts = [p for p in parsed.path.split("/") if p]
        if len(path_parts) >= 3 and path_parts[0] in ("live", "movie", "series"):
            user, pwd = path_parts[1], path_parts[2]
            return IPTVServer(
                host=host,
                username=user,
                password=pwd,
                source_url=source_url,
                raw_m3u_url=url_str.strip(),
            )
    except Exception:
        pass
    return None


def parse_key_value_blocks(text: str, source_url: str = "") -> List[IPTVServer]:
    """
    Parses multi-line blocks with Host, User, Pass keys.
    Example:
        Host: n2ip.tv:2095
        User: Christian1
        Pass: christian1
    """
    servers: List[IPTVServer] = []
    blocks = re.split(r"(?:-{3,}|\n\s*\n)", text)

    for block in blocks:
        host_match = re.search(r"^\s*(?:Host|Server|Domain|URL)\s*:\s*(.+)$", block, re.IGNORECASE | re.MULTILINE)
        user_match = re.search(r"^\s*(?:User|Username)\s*:\s*(.+)$", block, re.IGNORECASE | re.MULTILINE)
        pass_match = re.search(r"^\s*(?:Pass|Password)\s*:\s*(.+)$", block, re.IGNORECASE | re.MULTILINE)
        m3u_match = re.search(r"^\s*(?:M3U|Playlist)\s*:\s*(https?://\S+)", block, re.IGNORECASE | re.MULTILINE)

        if host_match and user_match and pass_match:
            raw_host = host_match.group(1).strip()
            username = user_match.group(1).strip()
            password = pass_match.group(1).strip()
            raw_m3u = m3u_match.group(1).strip() if m3u_match else ""

            server = IPTVServer(
                host=normalize_host(raw_host),
                username=username,
                password=password,
                source_url=source_url,
                raw_m3u_url=raw_m3u,
            )
            servers.append(server)

    return servers


def parse_tabular_lines(text: str, source_url: str = "") -> List[IPTVServer]:
    """
    Parses tabular IPTV audit reports such as:
    http://skybacon.xyz:80   nPQmGZNQmmqf : cLac2Q7BaNNf   Guayaquil, America ...
    or under section headers:
    === http://host:port (count) ===
    user : pass
    """
    servers: List[IPTVServer] = []
    current_host: Optional[str] = None

    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue

        # Section header tracker
        header_match = re.search(r"===\s*(https?://[^\s\)]+)", line)
        if header_match:
            current_host = normalize_host(header_match.group(1))
            continue

        # Tabular line: http://host:port <spaces> user : pass ...
        table_match = re.search(r"^(https?://[^\s:]+(?::\d+)?)\s+([^\s:]+)\s*:\s*(\S+)", line)
        if table_match:
            servers.append(
                IPTVServer(
                    host=normalize_host(table_match.group(1)),
                    username=table_match.group(2).strip(),
                    password=table_match.group(3).strip(),
                    source_url=source_url,
                )
            )
            continue

        # Line with user : pass under active section host
        if current_host and not line.lower().startswith("portal"):
            user_pass_match = re.search(r"^([^\s:]+)\s*:\s*(\S+)", line)
            if user_pass_match:
                user = user_pass_match.group(1).strip()
                pwd = user_pass_match.group(2).strip()
                if user.lower() not in ("user", "username", "host", "server", "portal", "status", "subject"):
                    servers.append(
                        IPTVServer(
                            host=current_host,
                            username=user,
                            password=pwd,
                            source_url=source_url,
                        )
                    )

    return servers


def parse_raw_credential_lines(text: str, source_url: str = "") -> List[IPTVServer]:
    """
    Parses line-based delimiter formats like:
    host:port:user:pass or host:port,user,pass
    """
    servers: List[IPTVServer] = []
    lines = text.splitlines()

    for line in lines:
        line = line.strip()
        if not line or line.startswith("#"):
            continue

        colon_parts = line.split(":")
        if len(colon_parts) == 4 and not line.startswith("http"):
            host_str = f"{colon_parts[0]}:{colon_parts[1]}"
            user = colon_parts[2].strip()
            pwd = colon_parts[3].strip()
            if user and pwd and "." in colon_parts[0]:
                servers.append(
                    IPTVServer(
                        host=normalize_host(host_str),
                        username=user,
                        password=pwd,
                        source_url=source_url,
                    )
                )
                continue

        comma_parts = line.split(",")
        if len(comma_parts) >= 3 and ("." in comma_parts[0] or "http" in comma_parts[0]):
            host_str = comma_parts[0].strip()
            user = comma_parts[1].strip()
            pwd = comma_parts[2].strip()
            if user and pwd:
                servers.append(
                    IPTVServer(
                        host=normalize_host(host_str),
                        username=user,
                        password=pwd,
                        source_url=source_url,
                    )
                )

    return servers


def extract_iptv_servers(text: str, source_url: str = "") -> List[IPTVServer]:
    """
    Comprehensive parser that extracts all IPTV server credentials
    from decrypted text, M3U links, key-value blocks, or tabular reports.
    Deduplicates results.
    """
    servers: List[IPTVServer] = []
    seen: Dict[str, IPTVServer] = {}

    def add_server(s: IPTVServer):
        if s.key not in seen:
            seen[s.key] = s
            servers.append(s)

    # 1. Tabular reports (e.g. Portal User : Pass ...)
    tab_servers = parse_tabular_lines(text, source_url)
    for s in tab_servers:
        add_server(s)

    # 2. Key-value blocks (Host: ..., User: ..., Pass: ...)
    kv_servers = parse_key_value_blocks(text, source_url)
    for s in kv_servers:
        add_server(s)

    # 3. Embedded get.php / player_api.php URLs
    url_matches = re.findall(r"https?://[^\s\"'<>\)\]]+", text)
    for url in url_matches:
        server = parse_m3u_or_api_url(url, source_url)
        if server:
            add_server(server)

    # 4. Delimiter-based lines (host:port:user:pass)
    raw_line_servers = parse_raw_credential_lines(text, source_url)
    for s in raw_line_servers:
        add_server(s)

    return servers
