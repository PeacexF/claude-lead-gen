import csv
import pathlib
import tempfile
import unittest

from leadgen.core import schema, store


class StoreTest(unittest.TestCase):
    def test_jsonl_roundtrip_is_atomic_and_ordered(self):
        with tempfile.TemporaryDirectory() as d:
            p = pathlib.Path(d) / "leads.jsonl"
            rows = [{"id": "a.com", "name": "Ä"}, {"id": "b.com", "name": "B"}]
            self.assertEqual(store.write_jsonl(p, rows), 2)
            self.assertEqual(list(store.read_jsonl(p)), rows)
            store.append_jsonl(p, [{"id": "c.com"}])
            self.assertEqual([r["id"] for r in store.read_jsonl(p)], ["a.com", "b.com", "c.com"])
            self.assertEqual(list(pathlib.Path(d).glob(".leads.jsonl.*")), [])

    def test_csv_neutralizes_formulas(self):
        lead = schema.empty_lead()
        lead.update(id="x.com", name='=HYPERLINK("http://evil","click")', notes="+1 cmd|' /C calc'!A0",
                    address="@SUM(A1)", city="-2+3", segment="\tTab", score=-5, website="  =1+1",
                    domain="＝cmd")
        with tempfile.TemporaryDirectory() as d:
            p = pathlib.Path(d) / "leads.csv"
            store.write_csv(p, [lead])
            with p.open() as fh:
                row = next(csv.DictReader(fh))
        for k in ("name", "notes", "address", "city", "segment", "website", "domain"):
            self.assertTrue(row[k].startswith("'"), (k, row[k]))
        self.assertEqual(row["score"], "-5")  # numbers are left alone
        self.assertEqual(row["id"], "x.com")


if __name__ == "__main__":
    unittest.main()
