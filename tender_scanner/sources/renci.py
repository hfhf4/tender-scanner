"""Ren Ci direct tender source."""
from __future__ import annotations
import hashlib, io, re
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from urllib.parse import urlparse
from bs4 import BeautifulSoup
from pypdf import PdfReader
from tender_scanner.common import SINGAPORE, fetch_http, iso
from tender_scanner.scoring import enrich

LISTING_URL = "https://www.renci.org.sg/notices-and-tenders/"
REFERENCE = re.compile(r"\bRC\d{2}[A-Z]{2}\d+\b", re.I)
MONTHS = r"January|February|March|April|May|June|July|August|September|October|November|December|Jan|Feb|Mar|Apr|Jun|Jul|Aug|Sep|Sept|Oct|Nov|Dec"


def parse_listing(html: bytes | str) -> list[dict]:
    soup = BeautifulSoup(html, "html.parser")
    entries=[]
    for item in soup.select(".elementor-accordion-item"):
        heading=item.select_one(".elementor-accordion-title"); content=item.select_one(".elementor-tab-content")
        if not heading or not content: continue
        match=REFERENCE.search(heading.get_text(" ", strip=True))
        if not match: continue
        ref=match.group(0).upper()
        node=content.find(["h1","h2","h3","h4","h5","h6","strong"]) or content.find("p")
        title=" ".join(node.get_text(" ",strip=True).split()) if node else ref
        pdfs=[]
        for a in content.select("a[href]"):
            href=(a.get("href") or "").strip(); p=urlparse(href)
            if p.scheme=="https" and p.hostname in {"renci.org.sg","www.renci.org.sg"} and p.path.lower().endswith(".pdf"): pdfs.append(href)
        if not pdfs: continue
        tender=next((u for u in pdfs if "nda" not in u.lower()), pdfs[0])
        entries.append({"reference":ref,"title":title,"tender_url":tender,"attachments":[u for u in pdfs if u!=tender]})
    if not entries: raise ValueError("No Ren Ci tender entries found; page structure may have changed")
    return entries


def _pdf_text(payload: bytes) -> str:
    reader=PdfReader(io.BytesIO(payload), strict=False); parts=[]
    for page in reader.pages[:30]:
        parts.append(page.extract_text() or "")
        if sum(map(len,parts))>=500000: break
    return "\n".join(parts)[:500000]


def _deadline(text: str) -> datetime | None:
    text=" ".join(text.replace("\u00a0"," ").split())
    marker=re.search(r"(?i)(?:registration|proposal|tender|rfp|submission)?\s*(?:closing\s+date|deadline|close\s+of\s+submission)", text)
    if not marker: return None
    seg=text[marker.start():marker.start()+300]
    m=re.search(rf"(?i)\b(\d{{1,2}})(?:st|nd|rd|th)?\s+({MONTHS})\s+(\d{{4}})\b",seg)
    fmts=("%d %B %Y","%d %b %Y"); value=None
    if m: value=f"{m.group(1)} {m.group(2)} {m.group(3)}".replace("Sept ","Sep ")
    else:
        m=re.search(r"\b(\d{1,2}[/-]\d{1,2}[/-]\d{4})\b",seg); fmts=("%d/%m/%Y","%d-%m-%Y")
        value=m.group(1) if m else None
    if not value: return None
    d=None
    for fmt in fmts:
        try: d=datetime.strptime(value,fmt); break
        except ValueError: pass
    if d is None: return None
    after=seg[m.end():m.end()+120]; tm=re.search(r"(?i)\b(\d{1,2})(?:[:.](\d{2}))?\s*(a\.?m\.?|p\.?m\.?)\b",after)
    h,minute=23,59
    if tm:
        h=int(tm.group(1)); minute=int(tm.group(2) or 0); mer=re.sub(r"\W","",tm.group(3)).lower()
        if mer=="pm" and h!=12: h+=12
        if mer=="am" and h==12: h=0
    else:
        tm=re.search(r"\b([01]?\d|2[0-3])[:.](\d{2})\b",after)
        if tm: h,minute=int(tm.group(1)),int(tm.group(2))
    return d.replace(hour=h,minute=minute,tzinfo=SINGAPORE).astimezone(timezone.utc)


def _build(entry: dict, seen_at: str) -> dict:
    text=""; warning=None; sha=None
    try:
        payload,_=fetch_http(entry["tender_url"],accept="application/pdf",attempts=2,timeout=25)
        if not payload.startswith(b"%PDF"): raise ValueError("notice link did not return PDF")
        sha=hashlib.sha256(payload).hexdigest(); text=_pdf_text(payload)
    except Exception as exc: warning=f"PDF extraction failed: {type(exc).__name__}"
    deadline=_deadline(text)
    record={
        "id":f"renci:{entry['reference']}","kind":"opportunity","source":"Ren Ci Hospital","source_key":"renci",
        "title":entry["title"],"tender_url":entry["tender_url"],"source_url":LISTING_URL,"url":entry["tender_url"],
        "document_url":entry["tender_url"],"attachments":entry["attachments"],"reference":entry["reference"],"agency":"Ren Ci Hospital",
        "published_at":None,"closing_at":iso(deadline),"listed_on_source":True,"scan_warning":warning,"document_sha256":sha,
        "first_seen_at":seen_at,"last_seen_at":seen_at,
    }
    return enrich(record,text)


def scan(seen_at: str) -> list[dict]:
    payload,_=fetch_http(LISTING_URL,accept="text/html,application/xhtml+xml",attempts=3,timeout=30)
    entries=parse_listing(payload)
    with ThreadPoolExecutor(max_workers=4) as pool: return list(pool.map(lambda e:_build(e,seen_at),entries))
