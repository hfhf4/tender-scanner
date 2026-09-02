import unittest
from datetime import timezone
from unittest.mock import patch

import scanner


class ScannerTests(unittest.TestCase):
    def test_specific_legal_work_scores_high(self):
        score, reasons = scanner.score_text("Appointment of a Panel of Law Firms for external legal services")
        self.assertEqual(score, 100)
        self.assertIn("panel of law firms", reasons)

    def test_technical_professional_service_scores_low(self):
        score, _ = scanner.score_text("Professional engineering consultancy for building construction")
        self.assertEqual(score, 0)

    def test_broader_practice_area_is_for_review(self):
        score, _ = scanner.score_text("Data protection assessment")
        self.assertGreaterEqual(score, 28)
        self.assertLess(score, 60)

    def test_singapore_time_is_converted_to_utc(self):
        parsed = scanner.parse_sg_datetime("02/09/2026 16:00:00")
        self.assertIsNotNone(parsed)
        self.assertEqual(parsed.tzinfo, timezone.utc)
        self.assertEqual(parsed.hour, 8)

    def test_renci_listing_extracts_notice_and_excludes_nda(self):
        html = b"""
        <div class="elementor-accordion-item">
          <a class="elementor-accordion-title">REQUEST FOR PROPOSAL NO: RC25MM06</a>
          <div class="elementor-tab-content">
            <h4>PROVISION OF CLIENT MANAGEMENT SYSTEM</h4>
            <a href="https://www.renci.org.sg/wp-content/uploads/RFP-Notice-RC25MM06.pdf">Notice</a>
            <a href="https://www.renci.org.sg/wp-content/uploads/NDA-for-RC25MM06.pdf">NDA</a>
          </div>
        </div>
        """
        records = scanner.parse_renci_listing(html)
        self.assertEqual(len(records), 1)
        self.assertEqual(records[0]["reference"], "RC25MM06")
        self.assertIn("RFP-Notice", records[0]["document_url"])
        self.assertEqual(len(records[0]["attachments"]), 1)
        self.assertIn("NDA", records[0]["attachments"][0])

    def test_renci_deadline_with_month_name_and_time(self):
        parsed, precision = scanner.parse_renci_deadline(
            "Registration Closing Date: 14 April 2026 (Tuesday), 12:00 pm"
        )
        self.assertIsNotNone(parsed)
        self.assertEqual(parsed.hour, 4)
        self.assertEqual(precision, "datetime")

    def test_renci_deadline_with_numeric_date_and_time(self):
        parsed, precision = scanner.parse_renci_deadline("Submission deadline: 11/08/2026 at 15:30")
        self.assertIsNotNone(parsed)
        self.assertEqual(parsed.hour, 7)
        self.assertEqual(precision, "datetime")

    def test_renci_deadline_accepts_ordinal_day(self):
        parsed, precision = scanner.parse_renci_deadline(
            "Registration Closing date: 21st May 2025, Wednesday, 12pm"
        )
        self.assertIsNotNone(parsed)
        self.assertEqual(parsed.hour, 4)
        self.assertEqual(precision, "datetime")

    def test_unchanged_renci_notice_reuses_pdf_result(self):
        entry = {
            "reference": "RC26MM08",
            "title": "PROVISION OF FOOD SERVICES",
            "document_url": "https://www.renci.org.sg/notice.pdf",
            "attachments": [],
            "listing_fingerprint": "unchanged",
        }
        previous = {
            "id": "renci:RC26MM08",
            "listing_fingerprint": "unchanged",
            "document_sha256": "abc123",
            "closing_at": "2026-08-11T07:00:00Z",
            "first_seen_at": "2026-08-01T00:00:00Z",
        }
        with patch("scanner.fetch_http", side_effect=AssertionError("PDF should not be fetched")):
            record = scanner.build_renci_record(entry, "2026-09-02T00:00:00Z", previous)
        self.assertEqual(record["closing_at"], previous["closing_at"])
        self.assertEqual(record["last_seen_at"], "2026-09-02T00:00:00Z")

    def test_removed_renci_notice_is_archived(self):
        existing = {
            "renci:RC26MM01": {
                "id": "renci:RC26MM01",
                "source_key": "renci",
                "listed_on_source": True,
            }
        }
        records = scanner.merge_records(existing, [], authoritative_source_keys={"renci"})
        self.assertFalse(records[0]["listed_on_source"])


if __name__ == "__main__":
    unittest.main()
