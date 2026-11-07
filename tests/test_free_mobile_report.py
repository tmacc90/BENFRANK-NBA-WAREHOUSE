"""Tests for receipt-only, HTML-escaped offline report rendering."""
import unittest
from scripts.build_free_mobile_report import build

class FreeMobileReportTests(unittest.TestCase):
    def test_incomplete_run_is_not_reported_as_success(self):
        result=build({"status":"INCOMPLETE_EXACT_BLOCKERS_RECORDED",
                      "fatal_blocker":"SOURCE_FETCH_FAILED",
                      "all_requested_props_executed":False,
                      "preservation_verified":True,"props":[]})
        self.assertIn("INCOMPLETE_EXACT_BLOCKERS_RECORDED",result)
        self.assertIn("SOURCE_FETCH_FAILED",result)
        self.assertIn("No verified props",result)
        self.assertIn("Research only",result)
    def test_escapes_untrusted_source_fields(self):
        result=build({"status":"INCOMPLETE","props":[{
            "prop":{"player":"<script>alert(1)</script>","market":"points","line":24.5},
            "status":"BLOCKED","direction":"MAYBE",
            "exact_blocker":"<img src=x onerror=alert(1)>",
            "stage_results":{"source":{"status":"FAILED","exact_reason":"<b>bad</b>"}}}]})
        self.assertNotIn("<script>alert(1)</script>",result)
        self.assertIn("&lt;script&gt;",result)
        self.assertIn("&lt;b&gt;bad&lt;/b&gt;",result)
        self.assertIn("NO VERIFIED SIDE",result)
    def test_valid_side_not_certification(self):
        result=build({"status":"FORWARD_RESEARCH_EXECUTED","all_requested_props_executed":True,
                      "preservation_verified":True,
                      "props":[{"prop":{"player":"Example","market":"rebounds","line":9.5},
                                "direction":"OVER","status":"FORWARD_TEST_READY_UNCALIBRATED",
                                "stage_results":{}}]})
        self.assertIn("OVER",result)
        self.assertIn("FORWARD_TEST_READY_UNCALIBRATED",result)
        self.assertIn("not certify betting accuracy",result)

if __name__=="__main__":unittest.main()
