"""Source runner: workspace adapters, LayoutChanged handling, inspect, and the adapter template."""
import contextlib
import io
import json
import os
import pathlib
import tempfile
import unittest
from unittest import mock

from leadgen import cli, sources
from leadgen.core.campaign import PLUGIN_ROOT, Campaign
from tests.fakes import FakeFetcher

# A workspace adapter that "fetches" pages from its spec, so the runner can be driven offline.
ADAPTER = '''
from leadgen.sources import LayoutChanged
NAME = "chamber"
KIND = "businesses"
REGIONS = "PT"
ABOUT = "test chamber directory"

def units(spec):
    return [{"page": p} for p in spec["pages"]]

def unit_key(u):
    return "p" + str(u["page"])

def collect_unit(ctx, unit):
    page = ctx.spec["pages"][unit["page"]]
    if page is None:
        raise LayoutChanged("no member table")
    return [{"source_id": n, "name": n, "sites": [n.lower() + ".test"], "city": "Porto"} for n in page]
'''


class SourcesTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = pathlib.Path(self.tmp.name)
        env = mock.patch.dict(os.environ, {"LEADGEN_HOME": str(self.root)})
        env.start()
        self.addCleanup(env.stop)
        (self.root / "sources").mkdir()
        (self.root / "sources/chamber.py").write_text(ADAPTER)
        self.camp = Campaign.create("t", root=self.root)
        self.logs: list[str] = []

    def cli(self, *argv):
        out = io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(io.StringIO()):
            code = cli.main([*argv, "--json"])
        return code, json.loads(out.getvalue())

    def test_workspace_adapter_collects_and_merges(self):
        spec = {"type": "chamber", "pages": {"1": ["Alfa", "Beta"], "2": ["Gama"]}}
        stats = sources.run_source(self.camp, spec, log=self.logs.append)
        self.assertEqual((stats["units"], stats["rows"]), (2, 3))
        self.assertEqual(len(sources.load_raw(self.camp, log=self.logs.append)), 3)
        self.assertEqual(sources.load("chamber", self.root).WORKSPACE, str((self.root / "sources/chamber.py").resolve()))
        code, res = self.cli("inspect", "t")
        self.assertEqual(code, 0)
        self.assertEqual(res["chamber"]["rows"], 3)
        self.assertEqual(res["chamber"]["fill"]["sites"], 1.0)
        code, res = self.cli("merge", "t")
        self.assertEqual(res["leads"], 3)

    def test_layout_changed_fails_loudly_and_stops_after_two(self):
        spec = {"type": "chamber", "pages": {"1": None, "2": ["Alfa"], "3": None, "4": None, "5": ["Zeta"]}}
        stats = sources.run_source(self.camp, spec, log=self.logs.append)
        self.assertEqual(stats["layout_changed"], 3)
        self.assertEqual(stats["rows"], 1)  # unit 5 never ran: 3 and 4 in a row stopped the source
        self.assertTrue(any("LAYOUT CHANGED" in m for m in self.logs))

    def test_unknown_and_bad_names(self):
        for name in ("nope", "../etc", "Chamber"):
            with self.subTest(name=name), self.assertRaises(KeyError):
                sources.load(name, self.root)
        (self.root / "sources/broken.py").write_text("NAME = 'other'\n")
        with self.assertRaises(KeyError):
            sources.load("broken", self.root)

    def test_template_is_a_working_adapter(self):
        src = (PLUGIN_ROOT / "templates/source.py").read_text().replace('NAME = "TODO_name"', 'NAME = "tmpl"')
        (self.root / "sources/tmpl.py").write_text(src)
        mod = sources.load("tmpl", self.root)
        unit = mod.units({"queries": ["dentist"], "locations": ["Porto"], "max_pages": 3})[0]
        page = ('<div class="TODO-result-item"><h2>Clinica <b>A</b></h2><a href="/company/a-1">x</a>'
                '<span data-website="https://a.test/"></span><a href="tel:+351 22 000 0000">call</a></div>')
        fake = FakeFetcher({mod.page_url(unit, 1): page + '<a rel="next">', mod.page_url(unit, 2): page})
        rows = mod.collect_unit(sources.Ctx(self.camp, fake, {}), unit)
        self.assertEqual([(r["source_id"], r["name"], r["sites"]) for r in rows], [("a-1", "Clinica A", ["https://a.test/"])])
        self.assertEqual(len(fake.calls), 2)  # page 2 brought no new ids → stop
        with self.assertRaises(sources.LayoutChanged):
            mod.parse("<html>redesigned</html>", unit)


if __name__ == "__main__":
    unittest.main()
