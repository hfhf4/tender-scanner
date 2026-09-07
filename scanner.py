#!/usr/bin/env python3
"""Collect and score Singapore legal and healthcare procurement opportunities."""
from __future__ import annotations

import json
import sys
from tender_scanner.common import DATA_DIR, iso, utc_now, write_dataset
from tender_scanner.registry import PORTALS, PUBLIC_SOURCES
from tender_scanner.sources import gebiz


def scan_opportunities(seen_at: str) -> tuple[list[dict], list[dict], set[str], list[str]]:
    records: list[dict] = []
    statuses: list[dict] = []
    authoritative: set[str] = set()
    source_urls: list[str] = []
    for source in PUBLIC_SOURCES:
        source_urls.append(source["url"])
        try:
            incoming = source["scanner"](seen_at)
            records.extend(incoming)
            statuses.append({"key":source["key"],"name":source["name"],"status":"ok","record_count":len(incoming),"url":source["url"]})
            if source.get("authoritative"):
                authoritative.add(source["key"])
        except Exception as exc:
            statuses.append({"key":source["key"],"name":source["name"],"status":"error","record_count":0,"url":source["url"],"error":f"{type(exc).__name__}: {exc}"})
            print(f"warning: {source['name']} scan failed: {exc}", file=sys.stderr)
    if not records:
        raise RuntimeError("All public opportunity sources failed")
    return records, statuses, authoritative, source_urls


def write_sources(statuses: list[dict], generated_at: str) -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    payload={"generated_at":generated_at,"sources":statuses,"portals":PORTALS}
    (DATA_DIR/"sources.json").write_text(json.dumps(payload,indent=2,ensure_ascii=False)+"\n",encoding="utf-8")


def run() -> int:
    generated_at=iso(utc_now())
    assert generated_at is not None
    opportunities,statuses,authoritative,source_urls=scan_opportunities(generated_at)
    total=write_dataset("opportunities",opportunities,generated_at,source_urls,authoritative)
    print(f"opportunities: received {len(opportunities)}; retained {total}")

    try:
        awards=gebiz.scan("awards",generated_at)
        award_total=write_dataset("awards",awards,generated_at,[gebiz.FEEDS["awards"]])
        statuses.append({"key":"gebiz-awards","name":"GeBIZ Awards","status":"ok","record_count":len(awards),"url":gebiz.FEEDS["awards"]})
        print(f"awards: received {len(awards)}; retained {award_total}")
    except Exception as exc:
        statuses.append({"key":"gebiz-awards","name":"GeBIZ Awards","status":"error","record_count":0,"url":gebiz.FEEDS["awards"],"error":f"{type(exc).__name__}: {exc}"})
        print(f"warning: GeBIZ awards scan failed: {exc}", file=sys.stderr)

    write_sources(statuses,generated_at)
    return 0


if __name__ == "__main__":
    raise SystemExit(run())
