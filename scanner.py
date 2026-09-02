#!/usr/bin/env python3
"""Collect and score Singapore tender and professional-services opportunities."""

from __future__ import annotations

import hashlib
import io
import json
import re
import sys
import time
import urllib.request
import xml.etree.ElementTree as ET
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import parse_qs, urlparse
from zoneinfo import ZoneInfo

from bs4 import BeautifulSoup
from pypdf import PdfReader


ROOT = Path(__file__).resolve().parent
DATA_DIR = ROOT / "docs" / "data"
SINGAPORE = ZoneInfo("Asia/Singapore")
USER_AGENT = "SingaporeTenderRadar/1.0 (+https://github.com/hfhf4/tender-scanner)"

FEEDS = {
    "opportunities": "https://www.gebiz.gov.sg/rss/Professional_Services-CREATE_BO_FEED.xml",
    "awards": "https://www.gebiz.gov.sg/rss/Professional_Services-CREATE_AWD_FEED.xml",
}

RENCI_LISTING_URL = "https://www.renci.org.sg/notices-and-tenders/"
RENCI_REFERENCE = re.compile(r"\bRC\d{2}[A-Z]{2}\d+\b", re.IGNORECASE)

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


def fetch_http(
    url: str,
    *,
    accept: str = "*/*",
    attempts: int = 3,
    timeout: int = 30,
) -> tuple[bytes, dict[str, str]]:
    last_error: Exception | None = None
    for attempt in range(1, attempts + 1):
        try:
            request = urllib.request.Request(
                url,
                headers={"User-Agent": USER_AGENT, "Accept": accept},
            )
            with urllib.request.urlopen(request, timeout=timeout) as response:
                payload = response.read()
                headers = {key.lower(): value for key, value in response.headers.items()}
            return payload, headers
        except Exception as exc:  # network and parsing failures are retried together
            last_error = exc
            if attempt < attempts:
                time.sleep(attempt * 2)
    raise RuntimeError(f"Unable to fetch {url}: {last_error}") from last_error


def fetch_xml(url: str, attempts: int = 3) -> bytes:
    payload, _ = fetch_http(
        url,
        accept="application/rss+xml, application/xml, text/xml",
        attempts=attempts,
        timeout=35,
    )
    if not payload.lstrip().startswith(b"<?xml"):
        raise ValueError(f"GeBIZ returned non-XML content for {url}")
    return payload


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
        "source": "GeBIZ",
        "source_key": "gebiz",
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
        "source": "GeBIZ",
        "source_key": "gebiz",
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


def parse_renci_listing(html: bytes | str) -> list[dict]:
    """Extract structured notice entries from Ren Ci's Elementor accordion."""
    soup = BeautifulSoup(html, "html.parser")
    entries: list[dict] = []
    for item in soup.select(".elementor-accordion-item"):
        heading = item.select_one(".elementor-accordion-title")
        content = item.select_one(".elementor-tab-content")
        if not heading or not content:
            continue
        reference_match = RENCI_REFERENCE.search(heading.get_text(" ", strip=True))
        if not reference_match:
            continue
        reference = reference_match.group(0).upper()

        title_node = content.find(["h1", "h2", "h3", "h4", "h5", "h6", "strong"])
        if title_node is None:
            title_node = content.find("p")
        title = " ".join(title_node.get_text(" ", strip=True).split()) if title_node else reference

        pdf_urls = []
        for anchor in content.select("a[href]"):
            href = (anchor.get("href") or "").strip()
            parsed = urlparse(href)
            if (
                parsed.scheme == "https"
                and parsed.hostname in {"renci.org.sg", "www.renci.org.sg"}
                and parsed.path.lower().endswith(".pdf")
            ):
                pdf_urls.append(href)
        if not pdf_urls:
            continue
        document_url = next((url for url in pdf_urls if "nda" not in url.lower()), pdf_urls[0])
        attachments = [url for url in pdf_urls if url != document_url]
        fingerprint_input = json.dumps(
            {"reference": reference, "title": title, "document_url": document_url, "attachments": attachments},
            sort_keys=True,
        )
        entries.append(
            {
                "reference": reference,
                "title": title,
                "document_url": document_url,
                "attachments": attachments,
                "listing_fingerprint": hashlib.sha256(fingerprint_input.encode()).hexdigest(),
            }
        )
    if not entries:
        raise ValueError("No Ren Ci tender entries found; the page structure may have changed")
    return entries


MONTH_PATTERN = (
    r"January|February|March|April|May|June|July|August|September|October|November|December|"
    r"Jan|Feb|Mar|Apr|Jun|Jul|Aug|Sep|Sept|Oct|Nov|Dec"
)


def parse_renci_deadline(text: str) -> tuple[datetime | None, str | None]:
    """Find a Singapore closing deadline near a closing/deadline label."""
    normalized = " ".join(text.replace("\u00a0", " ").split())
    marker = re.search(
        r"(?i)(?:registration|proposal|tender|rfp|submission)?\s*(?:closing\s+date|deadline|close\s+of\s+submission)",
        normalized,
    )
    if not marker:
        return None, None
    segment = normalized[marker.start() : marker.start() + 280]
    date_match = re.search(
        rf"(?i)\b(\d{{1,2}})(?:st|nd|rd|th)?\s+({MONTH_PATTERN})\s+(\d{{4}})\b",
        segment,
    )
    date_formats = ("%d %B %Y", "%d %b %Y")
    date_value = None
    if date_match is not None:
        date_value = f"{date_match.group(1)} {date_match.group(2)} {date_match.group(3)}".replace("Sept ", "Sep ")
    if date_match is None:
        date_match = re.search(r"\b(\d{1,2}[/-]\d{1,2}[/-]\d{4})\b", segment)
        date_formats = ("%d/%m/%Y", "%d-%m-%Y")
        date_value = date_match.group(1) if date_match is not None else None
    if date_match is None:
        return None, None

    parsed_date = None
    for fmt in date_formats:
        try:
            parsed_date = datetime.strptime(date_value, fmt)
            break
        except ValueError:
            continue
    if parsed_date is None:
        return None, None

    after_date = segment[date_match.end() : date_match.end() + 120]
    time_match = re.search(
        r"(?i)\b(\d{1,2})(?:[:.](\d{2}))?\s*(a\.?m\.?|p\.?m\.?)\b",
        after_date,
    )
    hour, minute, precision = 23, 59, "date"
    if time_match:
        hour = int(time_match.group(1))
        minute = int(time_match.group(2) or 0)
        meridiem = re.sub(r"\W", "", time_match.group(3)).lower()
        if meridiem == "pm" and hour != 12:
            hour += 12
        elif meridiem == "am" and hour == 12:
            hour = 0
        precision = "datetime"
    else:
        time_match = re.search(r"\b([01]?\d|2[0-3])[:.](\d{2})\b", after_date)
        if time_match:
            hour, minute, precision = int(time_match.group(1)), int(time_match.group(2)), "datetime"
        else:
            time_match = re.search(r"(?i)\b([01]?\d|2[0-3])(\d{2})\s*(?:hrs?|hours?)\b", after_date)
            if time_match:
                hour, minute, precision = int(time_match.group(1)), int(time_match.group(2)), "datetime"

    if hour > 23 or minute > 59:
        return None, None
    deadline = parsed_date.replace(hour=hour, minute=minute, second=0, tzinfo=SINGAPORE)
    return deadline.astimezone(timezone.utc), precision


def extract_pdf_text(payload: bytes) -> str:
    reader = PdfReader(io.BytesIO(payload), strict=False)
    pages = []
    for page in reader.pages[:30]:
        pages.append(page.extract_text() or "")
        if sum(map(len, pages)) >= 500_000:
            break
    return "\n".join(pages)[:500_000]


def build_renci_record(entry: dict, seen_at: str, previous: dict | None = None) -> dict:
    previous = previous or {}
    if (
        previous.get("listing_fingerprint") == entry["listing_fingerprint"]
        and previous.get("document_sha256")
        and not previous.get("scan_warning")
    ):
        return {
            **previous,
            **entry,
            "listed_on_source": True,
            "last_seen_at": seen_at,
        }

    pdf_text = ""
    document_sha = None
    document_etag = None
    document_last_modified = None
    warning = None
    try:
        payload, headers = fetch_http(
            entry["document_url"],
            accept="application/pdf",
            attempts=2,
            timeout=25,
        )
        if not payload.startswith(b"%PDF"):
            raise ValueError("notice link did not return a PDF")
        document_sha = hashlib.sha256(payload).hexdigest()
        document_etag = headers.get("etag")
        document_last_modified = headers.get("last-modified")
        pdf_text = extract_pdf_text(payload)
    except Exception as error:
        warning = f"PDF extraction failed: {type(error).__name__}"

    deadline, precision = parse_renci_deadline(pdf_text)
    if pdf_text:
        score, reasons = score_text(f"{entry['title']} {pdf_text}")
    else:
        score, reasons = score_text(entry["title"])
        score = previous.get("relevance_score", score)
        reasons = previous.get("score_reasons", reasons)
    if not deadline and not warning:
        warning = "Closing date was not found in the notice"
    return {
        "id": f"renci:{entry['reference']}",
        "kind": "opportunity",
        "source": "Ren Ci Hospital",
        "source_key": "renci",
        "title": entry["title"],
        "url": RENCI_LISTING_URL,
        "document_url": entry["document_url"],
        "attachments": entry["attachments"],
        "reference": entry["reference"],
        "agency": "Ren Ci Hospital",
        "published_at": None,
        "closing_at": iso(deadline) or previous.get("closing_at"),
        "deadline_precision": precision or previous.get("deadline_precision"),
        "relevance_score": score,
        "relevance": relevance_label(score),
        "score_reasons": reasons,
        "listing_fingerprint": entry["listing_fingerprint"],
        "document_sha256": document_sha or previous.get("document_sha256"),
        "document_etag": document_etag or previous.get("document_etag"),
        "document_last_modified": document_last_modified or previous.get("document_last_modified"),
        "listed_on_source": True,
        "scan_warning": warning,
        "first_seen_at": previous.get("first_seen_at", seen_at),
        "last_seen_at": seen_at,
    }


def scan_renci(existing: dict[str, dict], seen_at: str) -> list[dict]:
    payload, _ = fetch_http(
        RENCI_LISTING_URL,
        accept="text/html,application/xhtml+xml",
        attempts=3,
        timeout=30,
    )
    entries = parse_renci_listing(payload)

    def build(entry: dict) -> dict:
        return build_renci_record(entry, seen_at, existing.get(f"renci:{entry['reference']}"))

    with ThreadPoolExecutor(max_workers=4) as executor:
        return list(executor.map(build, entries))


def load_records(path: Path) -> dict[str, dict]:
    if not path.exists():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
        return {record["id"]: record for record in payload.get("records", []) if record.get("id")}
    except (json.JSONDecodeError, OSError, TypeError):
        return {}


def merge_records(
    existing: dict[str, dict],
    incoming: list[dict],
    authoritative_source_keys: set[str] | None = None,
) -> list[dict]:
    merged = dict(existing)
    incoming_ids = {record["id"] for record in incoming}
    for record_id, record in merged.items():
        if (
            authoritative_source_keys
            and record.get("source_key") in authoritative_source_keys
            and record_id not in incoming_ids
        ):
            record["listed_on_source"] = False
    for record in incoming:
        previous = existing.get(record["id"], {})
        if previous.get("first_seen_at"):
            record["first_seen_at"] = previous["first_seen_at"]
        merged[record["id"]] = {**previous, **record}

    def sort_key(record: dict) -> str:
        return record.get("closing_at") or record.get("awarded_at") or record.get("published_at") or ""

    return sorted(merged.values(), key=sort_key, reverse=True)


def write_dataset(
    kind: str,
    source_urls: list[str],
    feed_published: str | None,
    incoming: list[dict],
    generated_at: str,
    authoritative_source_keys: set[str] | None = None,
) -> int:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    path = DATA_DIR / f"{kind}.json"
    records = merge_records(load_records(path), incoming, authoritative_source_keys)
    payload = {
        "source": "Singapore Tender Radar",
        "source_urls": source_urls,
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

    opportunity_path = DATA_DIR / "opportunities.json"
    existing_opportunities = load_records(opportunity_path)
    opportunity_payload = fetch_xml(FEEDS["opportunities"])
    opportunity_published, gebiz_opportunities = parse_feed(
        opportunity_payload, "opportunities", generated_at
    )
    renci_opportunities = scan_renci(existing_opportunities, generated_at)
    incoming_opportunities = gebiz_opportunities + renci_opportunities
    opportunity_total = write_dataset(
        "opportunities",
        [FEEDS["opportunities"], RENCI_LISTING_URL],
        opportunity_published,
        incoming_opportunities,
        generated_at,
        authoritative_source_keys={"renci"},
    )
    print(
        f"opportunities: GeBIZ {len(gebiz_opportunities)}, "
        f"Ren Ci {len(renci_opportunities)}; retained {opportunity_total}"
    )

    award_payload = fetch_xml(FEEDS["awards"])
    award_published, awards = parse_feed(award_payload, "awards", generated_at)
    award_total = write_dataset(
        "awards",
        [FEEDS["awards"]],
        award_published,
        awards,
        generated_at,
    )
    print(f"awards: GeBIZ {len(awards)}; retained {award_total}")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(run())
    except Exception as error:
        print(f"scanner failed: {error}", file=sys.stderr)
        raise
