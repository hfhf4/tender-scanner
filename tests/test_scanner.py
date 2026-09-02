import unittest
from datetime import timezone

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


if __name__ == "__main__":
    unittest.main()
