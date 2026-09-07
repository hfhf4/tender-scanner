"""GeBIZ RSS source."""
from __future__ import annotations
import hashlib
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from urllib.parse import parse_qs, urlparse

from tender_scanner.common import SINGAPORE, fetch_http, iso
from tender_scanner.scoring import enrich

FEEDS = {
    "opportunities": "https://www.gebiz.gov.sg/rss/Professional_Services-CREATE_BO_FEED.xml",
    "awards": "https://www.gebiz.gov.sg/rss/Professional_Services-CREATE_AWD_FEED.xml",
}


def _fetch_xml(url: str) -> bytes:
    payload, _ = fetch_http(url, accept="application/rss+xml, application/xml, text/xml", attempts=3, timeout=35)
    if not payload.lstrip().startswith(b"<?xml"):
        raise ValueError(f"GeBIZ returned non-XML content for {url}")
    return payload


def _parse_sg_datetime(value: str) -> datetime | None:
    value = (value or "").strip()
    for fmt in ("%d/%m/%Y %H:%M:%S", "%d/%m/%Y"):
        try:
            return datetime.strptime(value, fmt).replace(tzinfo=SINGAPORE).astimezone(timezone.utc)
        except ValueError:
            continue
    return None


def _fields(description: str) -> dict[str, str]:
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


def _id(link: str, title: str) -> str:
    query = parse_qs(urlparse(link).query)
    for key in ("code", "OPPORTUNITY_ID"):
        if query.get(key):
            return query[key][0]
    return "gebiz:" + hashlib.sha256(f"{title}|{link}".encode()).hexdigest()[:20]


def _opportunity(item: ET.Element, seen_at: str) -> dict:
    title = (item.findtext("title") or "Untitled opportunity").strip()
    link = (item.findtext("link") or "").strip()
    description = (item.findtext("description") or "").strip()
    fields = _fields(description)
    return enrich({
        "id": _id(link, title),
        "kind": "opportunity",
        "source": "GeBIZ",
        "source_key": "gebiz",
        "title": title,
        "tender_url": link,
        "source_url": FEEDS["opportunities"],
        "url": link,
        "reference": fields.get("reference"),
        "agency": fields.get("calling entity", "Agency not stated"),
        "published_at": iso(_parse_sg_datetime(fields.get("published date", ""))),
        "closing_at": iso(_parse_sg_datetime(fields.get("closing date", ""))),
        "listed_on_source": True,
        "first_seen_at": seen_at,
        "last_seen_at": seen_at,
    }, description)


def _award(item: ET.Element, seen_at: str) -> dict:
    title = (item.findtext("title") or "Untitled award").strip()
    link = (item.findtext("link") or "").strip()
    description = (item.findtext("description") or "").strip()
    fields = _fields(description)
    record = enrich({
        "id": _id(link, title),
        "kind": "award",
        "source": "GeBIZ",
        "source_key": "gebiz",
        "title": title,
        "tender_url": link,
        "source_url": FEEDS["awards"],
        "url": link,
        "award_summary": description.split("|", 1)[0].strip(),
        "awarded_at": iso(_parse_sg_datetime(fields.get("awarded date", ""))),
        "first_seen_at": seen_at,
        "last_seen_at": seen_at,
    }, description)
    return record


def scan(kind: str, seen_at: str) -> list[dict]:
    payload = _fetch_xml(FEEDS[kind])
    root = ET.fromstring(payload)
    channel = root.find("channel")
    if channel is None:
        raise ValueError(f"RSS channel missing from {kind} feed")
    parser = _opportunity if kind == "opportunities" else _award
    return [parser(item, seen_at) for item in channel.findall("item")]
