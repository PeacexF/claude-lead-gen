import unittest

from leadgen import score
from leadgen.core import schema


def lead(**kw):
    l = schema.empty_lead()
    l.update(id="x.test", **kw)
    return l


class ValuesTest(unittest.TestCase):
    def test_paths_fan_out_through_lists(self):
        l = lead(emails=[{"value": "a@x.test", "verified": "mx"}, {"value": "b@x.test", "verified": "none"}],
                 site={"reachable": True, "tech": ["wordpress"]})
        self.assertEqual(score.values(l, "emails.verified"), ["mx", "none"])
        self.assertEqual(score.values(l, "site.reachable"), [True])
        self.assertEqual(score.values(l, "site.tech"), ["wordpress"])
        self.assertEqual(score.values(l, "dns.mx"), [])
        self.assertEqual(score.values(l, "socials.linkedin"), [])


class RuleTest(unittest.TestCase):
    def test_ops(self):
        l = lead(name="Harbor Dental", reviews=42, rating=4.6, categories=["amenity=dentist"], segment="dentist",
                 emails=[{"value": "a@x.test", "verified": "mx"}], site={"reachable": True, "tech": ["wix"]},
                 signals=[{"type": "hiring"}], country="PT")
        yes = [{"has": "emails"}, {"missing": "website"}, {"field": "reviews", "gte": 20},
               {"field": "rating", "lte": 5}, {"field": "emails.verified", "eq": "mx"}, {"field": "country", "in": ["PT", "ES"]},
               {"field": "name", "contains": "dental"}, {"field": "name", "matches": "^harbor"}, {"signal": "hiring"},
               {"signal": ["funding", "hiring"]}, {"tech": ["wix", "squarespace"]}, {"category": "dent"},
               {"field": "country", "ne": "US"}, {"has": "emails", "field": "reviews", "gte": 40}]
        no = [{"missing": "emails"}, {"has": "website"}, {"field": "reviews", "gte": 100}, {"field": "reviews", "lte": 10},
              {"field": "emails.verified", "eq": "smtp"}, {"field": "country", "ne": "PT"}, {"signal": "funding"},
              {"tech": "shopify"}, {"category": "lawyer"}, {"has": "emails", "field": "reviews", "gte": 100},
              {"field": "missing.path", "gte": 0}]
        for r in yes:
            with self.subTest(rule=r):
                self.assertTrue(score.matches(r, l))
        for r in no:
            with self.subTest(rule=r):
                self.assertFalse(score.matches(r, l))

    def test_check_rejects_bad_rules(self):
        for bad in ({"name": "x", "has": "emails"}, {"points": 1, "gte": 5}, {"points": 1, "hass": "emails"},
                    {"points": 1}, {"points": 1, "field": "name", "matches": "("}):
            with self.subTest(rule=bad), self.assertRaises(Exception):
                score.check(bad)
        score.check({"name": "ok", "has": "emails", "points": 5})
        score.check({"name": "ex", "category": "chain", "disqualify": True})


class ScoreAllTest(unittest.TestCase):
    CFG = {"scoring": {"tiers": {"A": 30, "B": 20, "C": 10}, "rules": [
        {"name": "email", "has": "emails", "points": 20},
        {"name": "phone", "has": "phones", "points": 10},
        {"name": "no site", "missing": "website", "points": 5},
        {"name": "big chain", "field": "name", "matches": "mcdonald", "disqualify": True},
        {"name": "penalty", "signal": "company_inactive", "points": -50},
    ]}}

    def test_tiers_breakdown_and_disqualify(self):
        leads = [lead(emails=[{"value": "a@x.test"}], phones=["351210000000"]),  # 35 → A
                 lead(emails=[{"value": "a@x.test"}], website="http://x.test"),  # 20 → B
                 lead(phones=["1"], website="http://x.test"),  # 10 → C
                 lead(website="http://x.test"),  # 0 → D
                 lead(name="McDonald's", emails=[{"value": "a@x.test"}], phones=["1"]),  # dq → D
                 lead(emails=[{"value": "a@x.test"}], phones=["1"], signals=[{"type": "company_inactive"}])]  # -15 → D
        out = score.score_all(leads, self.CFG)
        self.assertEqual([l["tier"] for l in leads], ["A", "B", "C", "D", "D", "D"])
        self.assertEqual(leads[0]["score_breakdown"], {"email": 20, "phone": 10, "no site": 5})
        self.assertEqual(leads[0]["score"], 35)
        self.assertEqual(leads[4]["score_breakdown"]["big chain"], "disqualified")
        self.assertEqual(leads[5]["score"], -15)  # 20 + 10 + 5 (no site) - 50
        self.assertEqual(out["tiers"], {"A": 1, "B": 1, "C": 1, "D": 3})
        self.assertIn("DISQUALIFY", out["formula"])
        self.assertIn("A >= 30", out["formula"])

    def test_tier_at_least(self):
        self.assertTrue(score.tier_at_least("A", "B"))
        self.assertTrue(score.tier_at_least("B", "B"))
        self.assertFalse(score.tier_at_least("C", "B"))
        self.assertFalse(score.tier_at_least(None, "D"))


if __name__ == "__main__":
    unittest.main()
