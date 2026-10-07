"""End-to-end CLI run on the offline `file` source: init → collect → merge → score → export → drafts → mark → send."""
import contextlib
import csv
import io
import json
import os
import pathlib
import tempfile
import unittest
from unittest import mock

from leadgen import cli
from leadgen.core.campaign import Campaign
from leadgen.core.store import read_jsonl

CONFIG = """
[campaign]
name = "t"
default_phone_cc = "351"

[[sources]]
type = "file"
paths = ["imports/list.csv"]
segment = "dentist"

[enrich]
site = false
dns = false

[[scoring.rules]]
name = "reachable by email"
has = "emails"
points = 30

[[scoring.rules]]
name = "chain"
field = "name"
matches = "(?i)megadent"
disqualify = true

[scoring.tiers]
A = 30
B = 20
C = 10

[outreach]
send_mode = "off"
"""

CSV = """name,website,phone,email,city
Sorriso Clinic,https://sorriso.test/,21 123 4567,info@sorriso.test,Lisbon
Sorriso Clinic Lisboa,,+351 21 123 4567,,Lisbon
=HYPERLINK("http://evil"),https://evil.test/,,,Lisbon
MegaDent,https://megadent.test/,,hello@megadent.test,Lisbon
"""


class CLITest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = pathlib.Path(self.tmp.name)
        env = mock.patch.dict(os.environ, {"LEADGEN_HOME": str(self.root)})
        env.start()
        self.addCleanup(env.stop)
        self.addCleanup(self.tmp.cleanup)

    def run_cli(self, *argv, stdin: str | None = None) -> tuple[int, str]:
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err), \
                mock.patch("sys.stdin", io.StringIO(stdin or "")):
            code = cli.main(list(argv))
        return code, out.getvalue()

    def j(self, *argv, stdin=None, code=0) -> dict:
        c, out = self.run_cli(*argv, "--json", stdin=stdin)
        self.assertEqual(c, code, out)
        return json.loads(out)

    def make_campaign(self):
        self.assertEqual(self.j("init", "t", "--offer", 'say "hi"')["campaign"], "t")
        camp = Campaign("t", self.root)
        self.assertEqual(camp.config["campaign"]["offer"], 'say "hi"')  # quotes escaped in TOML
        (camp.dir / "campaign.toml").write_text(CONFIG)
        (camp.dir / "imports").mkdir()
        (camp.dir / "imports/list.csv").write_text(CSV)
        return camp

    def test_pipeline(self):
        camp = self.make_campaign()
        r = self.j("run", "t")
        self.assertEqual(r["collect"][0]["rows"], 4)
        self.assertEqual(r["merge"]["leads"], 3)  # the two Sorriso rows share a phone
        self.assertEqual(r["enrich"]["steps"], [])
        self.assertEqual(r["score"]["tiers"], {"A": 1, "B": 0, "C": 0, "D": 2})
        leads = {l["id"]: l for l in read_jsonl(camp.leads_path)}
        self.assertEqual(leads["megadent.test"]["tier"], "D")
        self.assertEqual(leads["sorriso.test"]["phones"], ["351211234567"])

        with (camp.dir / "leads.csv").open() as fh:
            rows = list(csv.DictReader(fh))
        self.assertEqual(rows[0]["id"], "sorriso.test")  # sorted by tier
        self.assertTrue(next(x for x in rows if x["id"] == "evil.test")["name"].startswith("'="))

        # re-run is cached: no new units, same leads
        r2 = self.j("run", "t")
        self.assertEqual((r2["collect"][0]["units"], r2["collect"][0]["skipped_cached"]), (0, 1))
        self.assertEqual(r2["merge"]["leads"], 3)

        self.assertEqual(self.j("export", "t", "--min-tier", "A", "--has-email")["rows"], 1)
        st = self.j("status", "t")
        self.assertEqual((st["leads"], st["raw"]["file"]["rows"], st["status"]["new"]), (3, 4, 3))

    def test_drafts_mark_send(self):
        camp = self.make_campaign()
        self.j("run", "t", "--steps", "")
        ev = [{"fact": "form has no privacy link", "source": "https://sorriso.test/contact"}]
        d = {"lead_id": "sorriso.test", "subject": "Your contact form", "body": "Hi", "evidence": ev}
        self.assertEqual(self.j("drafts", "t", "add", stdin=json.dumps(d))["added"], 1)
        bad = self.j("drafts", "t", "add", stdin=json.dumps({**d, "evidence": []}), code=1)
        self.assertIn("evidence", bad["error"])
        self.assertEqual(self.j("status", "t")["status"]["drafted"], 1)
        shown = self.j("drafts", "t", "show", "sorriso.test")["drafts"][0]
        self.assertTrue(shown["deeplink"].startswith("mailto:info@sorriso.test?"))

        r = self.j("send", "t", "--dry-run")
        self.assertEqual([x["to"] for x in r["ready"]], ["info@sorriso.test"])
        refused = self.j("send", "t", code=3)  # send_mode off
        self.assertIn("off", refused["error"])

        m = self.j("mark", "t", "sorriso.test", "suppressed", "--note", "asked not to be contacted")
        self.assertEqual(m["suppressed"], ["sorriso.test"])
        self.assertIn("sorriso.test", (self.root / "suppression.txt").read_text())
        self.assertEqual(self.j("send", "t", "--dry-run")["ready"], [])

    def test_errors(self):
        self.assertEqual(self.j("status", "nope", code=1)["code"], 1)
        self.make_campaign()
        self.assertIn("no leads yet", self.j("score", "t", code=1)["error"])
        self.assertIn("not configured", self.j("collect", "t", "--source", "osm", code=1)["error"])
        self.assertEqual(self.j("init", "t", code=1)["code"], 1)  # exists
        self.assertEqual(self.j("suppress", "@spam.test", "--reason", "test")["added"], ["spam.test"])


if __name__ == "__main__":
    unittest.main()
