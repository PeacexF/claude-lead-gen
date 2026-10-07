import unittest

from leadgen.core.merge import merge


class MergeTest(unittest.TestCase):
    def test_remerge_keeps_enrichment(self):
        rows = [{"source": "osm", "name": "Acme", "website": "https://acme.test/", "emails": ["info@acme.test"],
                 "city": "Lisbon"}]
        first = merge(rows)
        lead = first[0]
        lead["site"] = {"checked": "2026-10-08", "reachable": True}
        lead["dns"] = {"checked": "2026-10-08", "mx": True}
        lead["jobs"] = {"checked": "2026-10-08", "open": 2}
        lead["registry"] = {"rkn": None}
        lead["emails"][0]["verified"] = "mx"
        lead["status"] = "drafted"

        again = merge(rows, first)
        self.assertEqual(len(again), 1)
        got = again[0]
        for k in ("site", "dns", "jobs", "registry"):
            self.assertEqual(got[k], lead[k], k)
        self.assertEqual(got["emails"], [{"value": "info@acme.test", "source": "osm", "type": "generic", "verified": "mx"}])
        self.assertEqual(got["status"], "drafted")

    def test_shared_phone_collapses(self):
        rows = [{"source": "a", "name": "Sorriso", "website": "sorriso.test", "phones": ["+351 21 123 4567"]},
                {"source": "b", "name": "Sorriso Lisboa", "phones": ["21 123 4567"]}]
        leads = merge(rows, default_cc="351")
        self.assertEqual([l["id"] for l in leads], ["sorriso.test"])
        self.assertEqual(len(leads[0]["sources"]), 2)


if __name__ == "__main__":
    unittest.main()
