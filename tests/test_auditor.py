import unittest
from app.auditor import check_adult, format_expiration

class TestAuditor(unittest.TestCase):
    def test_check_adult_keywords(self):
        self.assertTrue(check_adult("VIP | Adult XXX"))
        self.assertTrue(check_adult("For Adults Only"))
        self.assertFalse(check_adult("US: HBO HD"))
        self.assertTrue(check_adult("Swedish 18+ Live"))
        self.assertFalse(check_adult("Sport 1 Germany"))

    def test_format_expiration(self):
        date_str, countdown = format_expiration(None)
        self.assertEqual(date_str, "Unlimited")

        # Future timestamp
        date_str, countdown = format_expiration(1893456000)
        self.assertEqual(date_str, "2030-01-01")
        self.assertIn("Expires in", countdown)

if __name__ == "__main__":
    unittest.main()
