import json
import os
from typing import Any, Dict, Iterable, List, Tuple
from urllib.parse import urlparse

from dotenv import load_dotenv


def load_environment(env_path: str = ".env") -> None:
    """Load environment variables from a .env file if present."""
    if os.path.exists(env_path):
        load_dotenv(env_path)


def load_google_credentials() -> Dict[str, Any]:
    """Parse Google credentials JSON stored in the GOOGLE_CREDENTIALS_JSON env var."""
    raw_json = os.getenv("GOOGLE_CREDENTIALS_JSON")
    if not raw_json:
        raise ValueError("GOOGLE_CREDENTIALS_JSON environment variable is not set.")

    try:
        return json.loads(raw_json)
    except json.JSONDecodeError as exc:
        raise ValueError("GOOGLE_CREDENTIALS_JSON is not valid JSON.") from exc


def chunked(iterable: Iterable[Any], size: int) -> Iterable[Tuple[Any, ...]]:
    """Yield fixed-size chunks from an iterable."""
    chunk: List[Any] = []
    for item in iterable:
        chunk.append(item)
        if len(chunk) == size:
            yield tuple(chunk)
            chunk.clear()
    if chunk:
        yield tuple(chunk)


def sanitize_status(value: str) -> str:
    """Normalize status values coming from Google Sheets."""
    return (value or "").strip().lower()


def extract_slug(value: str) -> str:
    """Derive a slug from a raw slug or a full URL."""
    if not value:
        return ""

    raw = value.strip()
    if not raw:
        return ""

    if raw.startswith("http://") or raw.startswith("https://"):
        parsed = urlparse(raw)
        path = parsed.path or ""
        slug_candidate = path.rstrip("/").split("/")[-1]
    else:
        slug_candidate = raw

    return slug_candidate.strip().lower()


def build_post_url(base_url: str, slug: str) -> str:
    """Compose a canonical post URL from base URL and slug."""
    if not base_url or not slug:
        return ""
    return f"{base_url.rstrip('/')}/{slug.lstrip('/')}"
