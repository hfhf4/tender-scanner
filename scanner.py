#!/usr/bin/env python3
"""Collect and score Singapore GeBIZ professional-services opportunities."""

from __future__ import annotations

import hashlib
import json
import re
import sys
import time
import urllib.request
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import parse_qs, urlparse
from zoneinfo import ZoneInfo


ROOT = Path(__file__).resolve().parent
DATA_DIR = ROOT / "docs" / "data"
SINGAPORE = ZoneInfo("Asia/Singapore")
USER_AGENT = "SingaporeTenderRadar/1.0 (+https://github.com/hfhf4/tender-scanner)"

FEEDS = {
    "opportunities": "https://www.gebiz.gov.sg/rss/Professional_Services-CREATE_BO_FEED.xml",
    "awards": "https://www.gebiz.gov.sg/rss/Professional_Services-CREATE_AWD_FEED.xml",
}

# Scores are intentionally transparent and editable. Longer, specific phrases
# carry more weight than broad practice-area terms.
POSITIVE_RULES = (
    (r"\bpanel of law firms?\b", 95, "panel of law firms"),
    (r"\blegal services?\b", 90, "legal services"),
    (r"\bexternal legal (?:services?|counsel|advis(?:er|or|ory))\b", 85, "external legal work"),
    (r"\blaw firms?\b", 75, "law firm"),
    (r"\blegal counsel\b", 75, "legal counsel"),
    (r"\blegal (?:advice|advisory|adviser|advisor|consultancy)\b", 65, "legal advisory"),
    (r"\bdata protection\b", 40, "data protection"),
    (r"\bprivacy (?:law|advisory|compliance|review)\b", 38, "privacy"),
    (r"\bemployment law\b", 38, "employment law"),
    (r"\bregulatory (?:advice|advisory|compliance|review)\b", 36, "regulatory"),
    (r"\bcorporate governance\b", 34, "corporate governance"),
    (r"\bintellectual property\b|\btrade marks?\b", 32, "intellectual property"),
    (r"\bcontract (?:drafting|review|advisory|management)\b", 30, "contracts"),
    (r"\bcompliance (?:advice|advisory|review|framework)\b", 28, "compliance"),
    (r"\bcorporate (?:secretarial|legal)\b", 28, "corporate"),
)

NEGATIVE_RULES = (
    (r"\b(?:engineering|architectural|construction|quantity surveying)\b", -55, "technical consultancy"),
    (r"\b(?:software|hardware|network|cybersecurity|cloud|sharepoint)\b", -40, "technology services"),
    (r"\b(?:coaching|tuition|training programme|sports?)\b", -38, "training or sports"),
    (r"\b(?:cleaning|catering|guarding|landscaping|pest control)\b", -50, "facilities service"),
    (r"\b(?:installation|maintenance|repair|supply and delivery)\b", -35, "supply or maintenance"),
    (r"\b(?:medical services?|clinical|laboratory)\b", -32, "medical service"),
    (r"\b(?:event management|video production|design and production)\b", -30, "creative or event service"),
)


def utc_now() -> datetime:
    return datetime.now(timezone.utc).replace(microsecond=0)


def iso(dt: datetime | None) -> str | None:
    return dt.isoformat().replace("+00:00", "Z") if dt else None


def parse_sg_datetime(value: str) -> datetime | None:
    value = value.strip()
    if not value:
        return None
    for fmt in ("%d/%m/%Y %H:%M:%S", "%d/%m/%Y"):
        try:
            return datetime.strptime(value, fmt).replace(tzinfo=SINGAPORE).astimezone(timezone.utc)
        except ValueError:
            continue
    return None


def fetch_xml(url: str, attempts: int = 3) -> bytes:
    last_error: Exception | None = None
    for attempt in range(1, attempts + 1):
        try:
            request = urllib.request.Request(
                url,
                headers={"User-Agent": USER_AGENT, "Accept": "application/rss+xml, application/xml, text/xml"},
            )
            with urllib.request.urlopen(request, timeout=35) as response:
                payload = response.read()
            if not payload.lstrip().startswith(b"<?xml"):
                raise ValueError(f"GeBIZ returned non-XML content for {url}")
            return payload
        except Exception as exc:  # network and parsing failures are retried together
            last_error = exc
            if attempt < attempts:
                time.sleep(attempt * 2)
    raise RuntimeError(f"Unable to fetch {url}: {last_error}") from last_error


def item_id(link: str, title: str) -> str:
    query = parse_qs(urlparse(link).query)
    for key in ("code", "OPPORTUNITY_ID"):
        if query.get(key):
            return query[key][0]
    return hashlib.sha256(f"{title}|{link}".encode()).hexdigest()[:20]


def score_text(text: str) -> tuple[int, list[str]]:
    normalized = " ".join(text.lower().split())
    score = 0
    reasons: list[str] = []
    for pattern, weight, label in POSITIVE_RULES:
        if re.search(pattern, normalized):
            score += weight
            reasons.append(label)
    for pattern, weight, label in NEGATIVE_RULES:
        if re.search(pattern, normalized):
            score += weight
            reasons.append(label)
    return max(0, min(100, score)), reasons


def relevance_label(score: int) -> str:
    if score >= 60:
        return "high"
    if score >= 28:
        return "review"
    return "low"


def description_fields(description: str) -> dict[str, str]:
    fields: dict[str, str] = {}
    for segment in description.split("|"):
        segment = segment.strip()
        if not segment:
            continue
        if ":" in segment:
            key, value = segment.split(":", 1)
            fields[key.strip().lower()] = value.strip()
        elif not fields.get("reference"):
            fields["reference"] = segment
    return fields


def parse_opportunity(item: ET.Element, seen_at: str) -> dict:
    title = (item.findtext("title") or "Untitled opportunity").strip()
    link = (item.findtext("link") or "").strip()
    description = (item.findtext("description") or "").strip()
    fields = description_fields(description)
    score, reasons = score_text(f"{title} {description}")
    return {
        "id": item_id(link, title),
        "kind": "opportunity",
        "title": title,
        "url": link,
        "reference": fields.get("reference"),
        "agency": fields.get("calling entity", "Agency not stated"),
        "published_at": iso(parse_sg_datetime(fields.get("published date", ""))),
        "closing_at": iso(parse_sg_datetime(fields.get("closing date", ""))),
        "relevance_score": score,
        "relevance": relevance_label(score),
        "score_reasons": reasons,
        "first_seen_at": seen_at,
        "last_seen_at": seen_at,
    }


def parse_award(item: ET.Element, seen_at: str) -> dict:
    title = (item.findtext("title") or "Untitled award").strip()
    link = (item.findtext("link") or "").strip()
    description = (item.findtext("description") or "").strip()
    fields = description_fields(description)
    score, reasons = score_text(f"{title} {description}")
    vendor_text = description.split("|", 1)[0].strip()
    return {
        "id": item_id(link, title),
        "kind": "award",
        "title": title,
        "url": link,
        "award_summary": vendor_text,
        "awarded_at": iso(parse_sg_datetime(fields.get("awarded date", ""))),
        "relevance_score": score,
        "relevance": relevance_label(score),
        "score_reasons": reasons,
        "first_seen_at": seen_at,
        "last_seen_at": seen_at,
    }


def parse_feed(payload: bytes, kind: str, seen_at: str) -> tuple[str | None, list[dict]]:
    root = ET.fromstring(payload)
    channel = root.find("channel")
    if channel is None:
        raise ValueError(f"RSS channel missing from {kind} feed")
    feed_published = (channel.findtext("pubDate") or "").strip() or None
    parser = parse_opportunity if kind == "opportunities" else parse_award
    return feed_published, [parser(item, seen_at) for item in channel.findall("item")]


def load_records(path: Path) -> dict[str, dict]:
    if not path.exists():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
        return {record["id"]: record for record in payload.get("records", []) if record.get("id")}
    except (json.JSONDecodeError, OSError, TypeError):
        return {}


def merge_records(existing: dict[str, dict], incoming: list[dict]) -> list[dict]:
    merged = dict(existing)
    for record in incoming:
        previous = existing.get(record["id"], {})
        if previous.get("first_seen_at"):
            record["first_seen_at"] = previous["first_seen_at"]
        merged[record["id"]] = {**previous, **record}

    def sort_key(record: dict) -> str:
        return record.get("closing_at") or record.get("awarded_at") or record.get("published_at") or ""

    return sorted(merged.values(), key=sort_key, reverse=True)


def write_dataset(kind: str, feed_url: str, feed_published: str | None, incoming: list[dict], generated_at: str) -> int:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    path = DATA_DIR / f"{kind}.json"
    records = merge_records(load_records(path), incoming)
    payload = {
        "source": "GeBIZ Professional Services RSS",
        "source_url": feed_url,
        "feed_published": feed_published,
        "generated_at": generated_at,
        "record_count": len(records),
        "records": records,
    }
    temporary = path.with_suffix(".json.tmp")
    temporary.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    temporary.replace(path)
    return len(records)


def run() -> int:
    generated_at = iso(utc_now())
    assert generated_at is not None
    for kind, url in FEEDS.items():
        payload = fetch_xml(url)
        feed_published, incoming = parse_feed(payload, kind, generated_at)
        total = write_dataset(kind, url, feed_published, incoming, generated_at)
        print(f"{kind}: fetched {len(incoming)}; retained {total}")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(run())
    except Exception as error:
        print(f"scanner failed: {error}", file=sys.stderr)
        raise
