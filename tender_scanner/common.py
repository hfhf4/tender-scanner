"""Shared helpers for Singapore Tender Radar."""
from __future__ import annotations

import hashlib
import json
import time
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = ROOT / "docs" / "data"
SINGAPORE = ZoneInfo("Asia/Singapore")
USER_AGENT = "SingaporeTenderRadar/2.0 (+https://github.com/hfhf4/tender-scanner)"


def utc_now() -> datetime:
    return datetime.now(timezone.utc).replace(microsecond=0)


def iso(dt: datetime | None) -> str | None:
    return dt.isoformat().replace("+00:00", "Z") if dt else None


def stable_id(source_key: str, *parts: str) -> str:
    raw = "|".join(str(part or "") for part in parts)
    digest = hashlib.sha256(raw.encode()).hexdigest()[:20]
    return f"{source_key}:{digest}"


def fetch_http(url: str, *, accept: str = "*/*", attempts: int = 3, timeout: int = 30) -> tuple[bytes, dict[str, str]]:
    last_error: Exception | None = None
    for attempt in range(1, attempts + 1):
        try:
            request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT, "Accept": accept})
            with urllib.request.urlopen(request, timeout=timeout) as response:
                payload = response.read()
                headers = {key.lower(): value for key, value in response.headers.items()}
            return payload, headers
        except Exception as exc:
            last_error = exc
            if attempt < attempts:
                time.sleep(attempt * 2)
    raise RuntimeError(f"Unable to fetch {url}: {last_error}") from last_error


def load_dataset(path: Path) -> dict[str, dict]:
    if not path.exists():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
        return {record["id"]: record for record in payload.get("records", []) if record.get("id")}
    except (json.JSONDecodeError, OSError, TypeError):
        return {}


def merge_records(existing: dict[str, dict], incoming: list[dict], authoritative_source_keys: set[str] | None = None) -> list[dict]:
    merged = dict(existing)
    incoming_ids = {record["id"] for record in incoming}
    for record_id, record in merged.items():
        if authoritative_source_keys and record.get("source_key") in authoritative_source_keys and record_id not in incoming_ids:
            record["listed_on_source"] = False
    for record in incoming:
        previous = existing.get(record["id"], {})
        if previous.get("first_seen_at"):
            record["first_seen_at"] = previous["first_seen_at"]
        merged[record["id"]] = {**previous, **record}
    return sorted(merged.values(), key=lambda record: record.get("closing_at") or record.get("awarded_at") or record.get("published_at") or "", reverse=True)


def write_dataset(kind: str, incoming: list[dict], generated_at: str, source_urls: list[str], authoritative_source_keys: set[str] | None = None) -> int:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    path = DATA_DIR / f"{kind}.json"
    records = merge_records(load_dataset(path), incoming, authoritative_source_keys)
    payload = {
        "source": "Singapore Tender Radar",
        "source_urls": source_urls,
        "generated_at": generated_at,
        "record_count": len(records),
        "records": records,
    }
    temporary = path.with_suffix(".json.tmp")
    temporary.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    temporary.replace(path)
    return len(records)
