"""ALPS national sourcing schedule."""
from __future__ import annotations
import re
from datetime import datetime
from bs4 import BeautifulSoup
from tender_scanner.common import fetch_http, stable_id
from tender_scanner.scoring import enrich

LISTING_URL = "https://www.alpshealthcare.com.sg/strategic-procurement/national-sourcing-events/"
SAP_URL = "https://supplier.ariba.com/"
MONTHS = {name.upper(): i for i, name in enumerate(("January","February","March","April","May","June","July","August","September","October","November","December"),1)}


def parse_listing(html: bytes | str, seen_at: str) -> list[dict]:
    soup=BeautifulSoup(html,"html.parser")
    current_month=None; records=[]
    for node in soup.find_all(["h3","h4","table"]):
        if node.name in {"h3","h4"}:
            text=" ".join(node.get_text(" ",strip=True).split())
            m=re.search(r"(?i)\b("+"|".join(MONTHS)+r")\s+(20\d{2})\s+SOURCING EVENTS",text)
            if m: current_month=(MONTHS[m.group(1).upper()],int(m.group(2)))
            continue
        if not current_month: continue
        rows=node.find_all("tr")
        for row in rows:
            cells=[" ".join(c.get_text(" ",strip=True).split()) for c in row.find_all(["th","td"])]
            if len(cells)<3 or cells[0].lower() in {"s/n","sn","no.","no"}: continue
            if not cells[0].strip().isdigit(): continue
            category,title=cells[1].strip(),cells[2].strip()
            if not title: continue
            month,year=current_month
            record={
                "id":stable_id("alps",str(year),str(month),category,title),"kind":"opportunity","source":"ALPS Healthcare","source_key":"alps",
                "title":title,"tender_url":SAP_URL,"source_url":LISTING_URL,"url":SAP_URL,"reference":None,"agency":"ALPS Healthcare",
                "published_at":None,"closing_at":None,"listed_on_source":True,"category":category,"source_period":f"{year:04d}-{month:02d}",
                "summary":f"{category}. Scheduled national sourcing event; final RFP details are available through SAP Business Network.",
                "first_seen_at":seen_at,"last_seen_at":seen_at,
            }
            records.append(enrich(record, f"ALPS Healthcare {category} {title}"))
    if not records: raise ValueError("No ALPS sourcing events found; page structure may have changed")
    return records


def scan(seen_at: str) -> list[dict]:
    payload,_=fetch_http(LISTING_URL,accept="text/html,application/xhtml+xml",attempts=3,timeout=30)
    return parse_listing(payload,seen_at)
