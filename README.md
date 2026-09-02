# Singapore Legal Tender Radar

A small, zero-database tender monitor for potentially relevant Singapore legal and professional-services work.

## What it does

- reads the official GeBIZ Professional Services opportunity and award RSS feeds;
- runs every three hours through GitHub Actions;
- retains its own JSON history because each GeBIZ RSS feed only exposes recent items;
- applies transparent keyword scoring for legal-panel, corporate/commercial, regulatory, employment, data-protection and related work; and
- publishes a searchable static dashboard through GitHub Pages.

The dashboard is expected at <https://hfhf4.github.io/tender-scanner/> once the first Pages deployment completes.

## Run locally

Python 3.11 or later is required. No third-party packages are used.

```bash
python -m unittest discover -s tests -v
python scanner.py
python -m http.server --directory docs 8000
```

Then open <http://localhost:8000>.

## Configuration

Edit `POSITIVE_RULES` and `NEGATIVE_RULES` in `scanner.py` to tune the relevance model. Scores of 60 or more are marked `high`; scores from 28 to 59 are marked `review`.

## Data-source limitation

GeBIZ states that its RSS feeds list open tenders and quotations published in the preceding two days and award information from the preceding two days. The scanner therefore accumulates history prospectively; it is not a complete historical GeBIZ archive.

Always verify the current status, closing time and tender documents on GeBIZ before relying on a record.
