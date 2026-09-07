"""National Kidney Foundation tender pages."""
from __future__ import annotations
import re
from datetime import datetime, timezone
from urllib.parse import urljoin
from bs4 import BeautifulSoup
from tender_scanner.common import SINGAPORE, fetch_http, iso, stable_id
from tender_scanner.scoring import enrich

PAGES = {
    "RFP": "https://nkfs.org/tender/request-for-information/request-for-proposals/",
    "RFI": "https://nkfs.org/tender/request-for-information/",
    "ITT": "https://nkfs.org/tender/invitation-to-tender/",
    "ITQ": "https://nkfs.org/tender/invitation-to-quote/",
}
DATE_RE = re.compile(r"\b(\d{1,2})\s+(January|February|March|April|May|June|July|August|September|October|November|December)\s+(20\d{2})\b", re.I)
TIME_RE = re.compile(r"\b(\d{1,2})(?:[:.](\d{2}))?\s*(am|pm)\b", re.I)
REF_RE = re.compile(r"\b20\d{6}\b")
TITLE_RE = re.compile(r"^(?:RFP|RFI|ITT|ITQ)\b|request for (?:proposal|information)|invitation to (?:tender|quote)", re.I)


def _parse_deadline(text: str) -> datetime | None:
    text = " ".join((text or "").split())
    m = DATE_RE.search(text)
    if not m:
        return None
    try:
        d = datetime.strptime(f"{m.group(1)} {m.group(2)} {m.group(3)}", "%d %B %Y")
    except ValueError:
        return None
    tm = TIME_RE.search(text[max(0, m.start() - 50):m.end() + 80])
    h, minute = 23, 59
    if tm:
        h = int(tm.group(1)); minute = int(tm.group(2) or 0); mer = tm.group(3).lower()
        if mer == "pm" and h != 12: h += 12
        if mer == "am" and h == 12: h = 0
    return d.replace(hour=h, minute=minute, tzinfo=SINGAPORE).astimezone(timezone.utc)


def _table_blocks(soup: BeautifulSoup):
    for table in soup.find_all("table"):
        fields = {}; title_url = None
        for row in table.find_all("tr"):
            cells = row.find_all(["th", "td"])
            if len(cells) < 2:
                continue
            key = " ".join(cells[0].get_text(" ", strip=True).split()).rstrip(":").lower()
            value = " ".join(cells[1].get_text(" ", strip=True).split())
            fields[key] = value
            if key == "title":
                a = cells[1].find("a", href=True)
                if a: title_url = a.get("href")
        if fields.get("title"):
            yield fields, title_url


def _fallback_blocks(soup: BeautifulSoup):
    seen = set()
    for anchor in soup.find_all("a", href=True):
        title = " ".join(anchor.get_text(" ", strip=True).split())
        href = (anchor.get("href") or "").strip()
        if len(title) < 12 or not TITLE_RE.search(title):
            continue
        key = (title, href)
        if key in seen:
            continue
        seen.add(key)
        container = None
        for parent in anchor.parents:
            if getattr(parent, "name", None) in {"body", "html"}:
                break
            text = " ".join(parent.get_text(" ", strip=True).split())
            refs = REF_RE.findall(text)
            if refs and len(set(refs)) == 1 and len(text) < 12000:
                container = parent
                break
        text = " ".join((container or anchor.parent or anchor).get_text(" ", strip=True).split())
        ref_match = REF_RE.search(text)
        ref = ref_match.group(0) if ref_match else None
        closing = ""
        m = re.search(r"(?i)Closing Date\s*&?\s*Time\s*[:|]?\s*(.+?)(?=(?:Submission Requirements|RFP/ITQ Box|Compulsory Site Briefing|Registration of Interest|Eligibility Criteria|Title\s*[:|]|$))", text)
        if not m:
            m = re.search(r"(?i)Closing Date\s*[:|]?\s*(.+?)(?=(?:Submission Requirements|RFP/ITQ Box|Compulsory Site Briefing|Registration of Interest|Eligibility Criteria|Title\s*[:|]|$))", text)
        if m:
            closing = m.group(1).strip()
        yield {"title": title, "reference no": ref, "closing date & time": closing, "_context": text}, href


def _blocks(soup: BeautifulSoup):
    rows = list(_table_blocks(soup))
    if rows:
        yield from rows
        return
    yield from _fallback_blocks(soup)


def parse_page(html: bytes | str, kind: str, source_url: str, seen_at: str) -> list[dict]:
    soup = BeautifulSoup(html, "html.parser"); records = []
    for fields, href in _blocks(soup):
        title = (fields.get("title") or "").strip()
        if not title:
            continue
        ref = fields.get("reference no") or fields.get("reference number")
        if not ref:
            m = REF_RE.search(" ".join(str(v or "") for v in fields.values())); ref = m.group(0) if m else None
        closing = fields.get("closing date & time") or fields.get("closing date") or ""
        tender_url = urljoin(source_url, href) if href else source_url
        context = fields.get("_context") or " ".join(str(v or "") for v in fields.values())
        record = {
            "id": f"nkf:{ref}" if ref else stable_id("nkf", kind, title),
            "kind": "opportunity", "source": "National Kidney Foundation", "source_key": "nkf",
            "title": title, "tender_url": tender_url, "source_url": source_url, "url": tender_url,
            "reference": ref, "agency": "National Kidney Foundation", "published_at": None,
            "closing_at": iso(_parse_deadline(closing)), "listed_on_source": True, "category": kind,
            "summary": closing[:700] if closing else None, "first_seen_at": seen_at, "last_seen_at": seen_at,
        }
        records.append(enrich(record, context))
    dedup = {r["id"]: r for r in records}
    return list(dedup.values())


def scan(seen_at: str) -> list[dict]:
    records = []
    for kind, url in PAGES.items():
        try:
            payload, _ = fetch_http(url, accept="text/html,application/xhtml+xml", attempts=2, timeout=30)
            records.extend(parse_page(payload, kind, url, seen_at))
        except Exception:
            continue
    if not records:
        raise ValueError("No NKF procurement records found; page structure may have changed")
    return list({r["id"]: r for r in records}.values())
