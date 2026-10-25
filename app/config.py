import os

class Config:
    HOST: str = os.getenv("HOST", "0.0.0.0")
    PORT: int = int(os.getenv("PORT", "8180"))
    MAX_CONCURRENT_CHECKS: int = int(os.getenv("MAX_CONCURRENT_CHECKS", "8"))
    REQUEST_TIMEOUT: float = float(os.getenv("REQUEST_TIMEOUT", "6.0"))
    PROBE_STREAMS: bool = os.getenv("PROBE_STREAMS", "true").lower() in ("true", "1", "yes")
    PROBE_TIMEOUT: float = float(os.getenv("PROBE_TIMEOUT", "4.0"))
    USER_AGENT: str = os.getenv("USER_AGENT", "IPTVSmartersPlayer")

config = Config()
