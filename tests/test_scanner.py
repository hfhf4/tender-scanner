import unittest
from datetime import timezone
from tender_scanner.common import merge_records
from tender_scanner.scoring import legal_score, healthcare_score, enrich
from tender_scanner.sources import alps, nkf, renci

class ScannerV2Tests(unittest.TestCase):
    def test_specific_legal_work_scores_high(self):
        score,reasons=legal_score("Appointment of a Panel of Law Firms for external legal services")
        self.assertEqual(score,100); self.assertIn("panel of law firms",reasons)

    def test_technical_consultancy_scores_low(self):
        score,_=legal_score("Professional engineering consultancy for building construction")
        self.assertEqual(score,0)

    def test_healthcare_classifier(self):
        score,reasons=healthcare_score("Ministry of Health hospital legal services")
        self.assertEqual(score,100); self.assertTrue(reasons)

    def test_enrichment_preserves_separate_links(self):
        record=enrich({"title":"Legal services","agency":"Ren Ci Hospital","source":"Ren Ci Hospital","tender_url":"https://www.renci.org.sg/a.pdf","source_url":"https://www.renci.org.sg/notices-and-tenders/"})
        self.assertEqual(record["tender_url"],"https://www.renci.org.sg/a.pdf")
        self.assertEqual(record["source_url"],"https://www.renci.org.sg/notices-and-tenders/")

    def test_renci_listing_extracts_notice_and_nda(self):
        html=b'''<div class="elementor-accordion-item"><a class="elementor-accordion-title">REQUEST FOR PROPOSAL NO: RC25MM06</a><div class="elementor-tab-content"><h4>PROVISION OF CLIENT MANAGEMENT SYSTEM</h4><a href="https://www.renci.org.sg/wp-content/uploads/RFP-Notice-RC25MM06.pdf">Notice</a><a href="https://www.renci.org.sg/wp-content/uploads/NDA-for-RC25MM06.pdf">NDA</a></div></div>'''
        records=renci.parse_listing(html)
        self.assertEqual(records[0]["reference"],"RC25MM06")
        self.assertIn("RFP-Notice",records[0]["tender_url"])
        self.assertEqual(len(records[0]["attachments"]),1)

    def test_renci_deadline(self):
        parsed=renci._deadline("Registration Closing Date: 14 April 2026 (Tuesday), 12:00 pm")
        self.assertIsNotNone(parsed); self.assertEqual(parsed.tzinfo,timezone.utc); self.assertEqual(parsed.hour,4)

    def test_removed_authoritative_notice_is_archived(self):
        existing={"renci:1":{"id":"renci:1","source_key":"renci","listed_on_source":True}}
        records=merge_records(existing,[],{"renci"})
        self.assertFalse(records[0]["listed_on_source"])

    def test_alps_table_parser(self):
        html='''<h4>SEPTEMBER 2026 SOURCING EVENTS</h4><table><tr><th>S/N</th><th>CATEGORY</th><th>RFP TITLE</th></tr><tr><td>1</td><td>Services</td><td>Provision of Legal Services</td></tr></table>'''
        rows=alps.parse_listing(html,"2026-09-07T00:00:00Z")
        self.assertEqual(len(rows),1); self.assertEqual(rows[0]["source_key"],"alps"); self.assertEqual(rows[0]["relevance"],"high")

    def test_nkf_table_parser(self):
        html='''<table><tr><td>Title</td><td><a href="/notice.pdf">RFP for Data Protection Legal Advisory</a></td></tr><tr><td>Reference No</td><td>20260901</td></tr><tr><td>Closing Date & Time</td><td>3pm on 23 September 2026</td></tr></table>'''
        rows=nkf.parse_page(html,"RFP",nkf.PAGES["RFP"],"2026-09-07T00:00:00Z")
        self.assertEqual(rows[0]["id"],"nkf:20260901"); self.assertIn("nkfs.org",rows[0]["tender_url"]); self.assertEqual(rows[0]["relevance"],"high")

if __name__=="__main__": unittest.main()
