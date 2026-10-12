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
from leadgen.core.http import Blocked
from leadgen.sources import LayoutChanged, hn_hiring, opencorporates, sec_edgar, twogis
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


class HNHiringTest(unittest.TestCase):
    def site_and_boards(self, html):
        p = hn_hiring.parse_post(html)
        return hn_hiring.company_site(p), [(b["ats"], b["token"]) for b in p["job_boards"]]

    def test_site_is_the_company_not_any_link(self):
        # an article linked in the body must not become the lead's domain (it's the merge key)
        self.assertEqual(self.site_and_boards(
            'Paramark | Engineer | SF<p>In the news: <a href="https://www.mercurynews.com/2025/x">article</a>. '
            'Apply <a href="https://jobs.ashbyhq.com/paramark/123">here</a>'), (None, [("ashby", "paramark")]))
        # a body link whose host looks like the company counts; a careers path yields the root
        self.assertEqual(self.site_and_boards(
            'Curai | ML | REMOTE<p>See <a href="https://curaihealth.com/careers">careers</a>'),
            ("https://curaihealth.com/", []))
        # a link in the headline counts even when the name differs; code hosts never do
        self.assertEqual(self.site_and_boards(
            'Acme | Backend | Remote | https://brandco.io<p><a href="https://github.com/acme/x">gh</a>'),
            ("https://brandco.io/", []))
        self.assertEqual(self.site_and_boards(
            'Discord | SWE<p><a href="https://boards.greenhouse.io/discord/jobs/1">jobs</a>'),
            (None, [("greenhouse", "discord")]))
        # ATS hosts are never the site, even when the name matches; careers./jobs. subdomains give the company domain
        self.assertEqual(self.site_and_boards('Axmed | Eng<p><a href="https://axmed.teamtailor.com/jobs/1">apply</a>')[0], None)
        self.assertEqual(self.site_and_boards('Search Atlas | Eng | https://careers.searchatlas.com/x')[0],
                         "https://searchatlas.com/")
        self.assertEqual(hn_hiring.parse_post("Snout https://snout.co | Eng | Remote")["company"], "Snout")


def gis_page(prof: dict, total: int | None = None, pad: bool = True) -> str:
    """A page shaped like 2GIS's: the state is a single-quoted JS string inside JSON.parse (synthetic data)."""
    st = {"data": {"entity": {"profile": {k + "_x1": {"data": v} for k, v in prof.items()}},
                   "search": {"profile": {"uuid-1": {"data": {"total": total}}} if total is not None else {}}}}
    js = json.dumps(st, ensure_ascii=False).replace("\\", "\\\\").replace("'", "\\'")
    return "<html><script>var initialState = JSON.parse('" + js + "');</script>" + (" " * 60_000 if pad else "")


def gis_branch(name, org, **extra):
    return {"type": "branch", "name": name, "org": {"id": org, "branch_count": 2}, "address_name": "ул. Тестовая, 1",
            "adm_div": [{"type": "country", "name": "Россия"}, {"type": "city", "name": "Казань"}],
            "rubrics": [{"name": "Стоматологии"}], "reviews": {"general_rating": 4.8, "general_review_count": 31},
            "point": {"lat": 55.79, "lon": 49.12}, **extra}


GIS_CONTACTS = [{"contacts": [
    {"type": "phone", "value": "+78430000001"},
    {"type": "website", "url": "http://clinic-a.test/?utm_source=2gis&utm_medium=2gis&page=1",
     "value": "http://link.2gis.ru/1.2/AB/online/x?http://clinic-a.test/"},
    {"type": "email", "value": "info@clinic-a.test"},
    {"type": "telegram", "url": "https://t.me/clinic_a", "value": "https://t.me/clinic_a"},
    {"type": "vkontakte", "url": "https://vk.com/clinic_a"},
]}]


class _GisFetcher(FakeFetcher):
    def __init__(self, routes, final=None):
        super().__init__(routes)
        self.final = final or {}

    def request(self, url, data=None, headers=None, **kw):
        status, _, body = super().request(url, data, headers, **kw)
        return status, self.final.get(url, url), body


class TwoGisTest(unittest.TestCase):
    SEARCH = "https://2gis.ru/kazan/search/" + "%D1%81%D1%82%D0%BE%D0%BC"  # quote("стом")

    def setUp(self):
        twogis._org_sites.clear()

    def ctx(self, fetcher):
        return mock.Mock(fetcher=fetcher, log=lambda m: None)

    def test_js_unquote(self):
        self.assertEqual(twogis.js_unquote(r"a\'b\\c\nd\u0416\x41\ud83d\ude00\/"), "a'b\\c\ndЖA😀/")

    def test_state_and_row(self):
        page = gis_page({"101": gis_branch("Клиника «А» — 'зуб'", "o1", contact_groups=GIS_CONTACTS)}, total=1)
        st = twogis.state(page)
        self.assertEqual(twogis.total(st), 1)
        r = twogis.row(twogis.profiles(st)["101"], "101", "kazan", "стоматология")
        self.assertEqual(r["name"], "Клиника «А» — 'зуб'")
        self.assertEqual(r["sites"], ["http://clinic-a.test/?page=1"])  # tracking dropped, link.2gis not used
        self.assertEqual((r["city"], r["country"], r["address"]), ("Казань", "Россия", "Казань, ул. Тестовая, 1"))
        self.assertEqual((r["phones"], r["emails"], r["telegram"], r["vk"]),
                         (["+78430000001"], ["info@clinic-a.test"], ["https://t.me/clinic_a"], ["https://vk.com/clinic_a"]))
        self.assertEqual((r["rating"], r["reviews"], r["url"]), (4.8, 31, "https://2gis.ru/kazan/firm/101"))

    def test_link_wrapper_is_unwrapped(self):
        self.assertEqual(twogis.clean_url("http://link.2gis.ru/1.2/AB/x?http://b.test/?utm_campaign=z"), "http://b.test/")

    def test_collect_reads_one_firm_page_per_organisation(self):
        search = gis_page({"101": gis_branch("A", "o1"), "102": gis_branch("A", "o1"), "201": gis_branch("B", "o2")},
                          total=3)
        firm = lambda fid, org: gis_page({fid: gis_branch("A", org, contact_groups=GIS_CONTACTS)})
        f = _GisFetcher({self.SEARCH: search, "https://2gis.ru/kazan/firm/101": firm("101", "o1"),
                         "https://2gis.ru/kazan/firm/201": firm("201", "o2")})
        rows = twogis.collect_unit(self.ctx(f), {"query": "стом", "location": "kazan", "limit": 50, "domain": "2gis.ru"})
        self.assertEqual([r["source_id"] for r in rows], ["101", "102", "201"])
        self.assertNotIn("https://2gis.ru/kazan/firm/102", f.calls)          # same org: reuses 101's sites
        self.assertEqual(rows[1]["sites"], rows[0]["sites"])
        self.assertNotIn(self.SEARCH + "/page/2", f.calls)                   # total reached

    def test_paginates_and_honours_limit(self):
        p1 = gis_page({str(100 + i): gis_branch(f"N{i}", f"o{i}") for i in range(12)}, total=30)
        p2 = gis_page({str(200 + i): gis_branch(f"M{i}", f"p{i}") for i in range(12)}, total=30)
        routes = {self.SEARCH: p1, self.SEARCH + "/page/2": p2}
        routes.update({f"https://2gis.ru/kazan/firm/{i}": gis_page({}) for i in [*range(100, 112), *range(200, 212)]})
        f = _GisFetcher(routes)
        rows = twogis.collect_unit(self.ctx(f), {"query": "стом", "location": "kazan", "limit": 15, "domain": "2gis.ru"})
        self.assertEqual(len(rows), 15)
        self.assertNotIn(self.SEARCH + "/page/3", f.calls)
        self.assertEqual(rows[0]["name"], "N0")  # firm page without the profile: the search entry is used

    def test_walls_stop_and_are_not_cached(self):
        unit = {"query": "стом", "location": "kazan", "limit": 12, "domain": "2gis.ru"}
        f = _GisFetcher({self.SEARCH: "<html>captcha</html>"})
        with self.assertRaises(Blocked):
            twogis.collect_unit(self.ctx(f), unit)
        self.assertEqual(f.forgotten, [self.SEARCH])
        f = _GisFetcher({self.SEARCH: "<html>old browser</html>"}, final={self.SEARCH: "https://2gis.ru/museum?x=1"})
        with self.assertRaises(LayoutChanged) as e:
            twogis.collect_unit(self.ctx(f), unit)
        self.assertIn("UA_BROWSER", str(e.exception))
        with self.assertRaises(LayoutChanged):  # a full page without the state is a layout change, not a block
            twogis.state("<html>" + " " * 60_000 + "</html>")


FORM_D = """<?xml version="1.0"?>
<edgarSubmission><submissionType>D</submissionType>
<primaryIssuer><cik>0009990001</cik><entityName>Example Robotics, Inc.</entityName>
<issuerAddress><street1>1 TEST WAY</street1><city>AUSTIN</city><stateOrCountry>TX</stateOrCountry><zipCode>78701</zipCode></issuerAddress>
<issuerPhoneNumber>5125550100</issuerPhoneNumber><jurisdictionOfInc>DELAWARE</jurisdictionOfInc><entityType>Corporation</entityType>
<yearOfInc><withinFiveYears>true</withinFiveYears><value>2025</value></yearOfInc></primaryIssuer>
<relatedPersonsList><relatedPersonInfo><relatedPersonName><firstName>Ada</firstName><lastName>Example</lastName></relatedPersonName>
<relatedPersonRelationshipList><relationship>Executive Officer</relationship><relationship>Director</relationship></relatedPersonRelationshipList>
</relatedPersonInfo></relatedPersonsList>
<offeringData><industryGroup><industryGroupType>Other Technology</industryGroupType></industryGroup>
<issuerSize><revenueRange>No Revenues</revenueRange></issuerSize>
<typeOfFiling><dateOfFirstSale><value>2026-09-20</value></dateOfFirstSale></typeOfFiling>
<offeringSalesAmounts><totalOfferingAmount>2000000</totalOfferingAmount><totalAmountSold>500000</totalAmountSold></offeringSalesAmounts>
</offeringData></edgarSubmission>"""


def efts(*hits, total=None):
    return {"hits": {"total": {"value": total if total is not None else len(hits)}, "hits": [
        {"_id": f"{adsh}:{file}", "_source": {"ciks": [cik], "form": form, "file_date": "2026-10-09",
                                               "display_names": [f"Co {cik}  (CIK {cik})"], "biz_locations": ["Austin, TX"]}}
        for cik, adsh, file, form in hits]}}


class SecEdgarTest(unittest.TestCase):
    UNIT = {"forms": "D", "query": "", "from": "2026-10-01", "to": "2026-10-10", "limit": 50, "amendments": False,
            "state": "TX", "skip": ["Pooled Investment Fund"]}

    def test_search_url_filters_by_business_state(self):
        u = sec_edgar.search_url(self.UNIT, 100)
        self.assertIn("locationType=located", u)
        self.assertIn("locationCodes=TX", u)
        self.assertIn("from=100", u)

    def test_form_d_row(self):
        f = {"cik": "9990001", "adsh": "0009990001-26-000001", "file": "primary_doc.xml", "form": "D",
             "filed": "2026-10-09", "name": "x"}
        r = sec_edgar.form_d(FORM_D, f)
        self.assertEqual((r["name"], r["city"], r["phones"], r["country"]), ("Example Robotics, Inc.", "Austin",
                                                                            ["+15125550100"], "US"))
        self.assertEqual(r["legal"]["registry_ids"], {"cik": "9990001"})
        self.assertEqual(r["people"][0]["name"], "Ada Example")
        self.assertEqual(r["people"][0]["role"], "Executive Officer, Director")
        self.assertEqual(r["signals"][0]["type"], "funding")
        self.assertIn("$500,000 sold of $2,000,000 offered", r["signals"][0]["value"])
        self.assertIn("/Archives/edgar/data/9990001/000999000126000001/primary_doc.xml", r["signals"][0]["source"])

    def test_dtd_is_refused(self):
        bomb = '<?xml version="1.0"?><!DOCTYPE x [<!ENTITY a "aaaa">]><edgarSubmission>&a;</edgarSubmission>'
        with self.assertRaises(ValueError):
            sec_edgar.parse_xml(bomb)

    def test_collect_one_row_per_company_and_skips_amendments(self):
        search = efts(("0009990001", "0009990001-26-000002", "primary_doc.xml", "D"),
                      ("0009990001", "0009990001-26-000001", "primary_doc.xml", "D"),
                      ("0009990002", "0009990002-26-000001", "primary_doc.xml", "D/A"))
        f = FakeFetcher({sec_edgar.search_url(self.UNIT): search,
                         "https://www.sec.gov/Archives/edgar/data/9990001/": FORM_D})
        rows = sec_edgar.collect_unit(mock.Mock(fetcher=f, log=lambda m: None), self.UNIT)
        self.assertEqual([r["source_id"] for r in rows], ["9990001"])
        self.assertIn("/9990001/000999000126000002/primary_doc.xml", rows[0]["signals"][0]["source"])  # newest filing
        f.routes["https://www.sec.gov/Archives/edgar/data/9990001/"] = FORM_D.replace("Other Technology", "Pooled Investment Fund")
        fund = sec_edgar.collect_unit(mock.Mock(fetcher=f, log=lambda m: None), self.UNIT)
        self.assertEqual(fund, [])  # funds are skipped by default


class OpenCorporatesTest(unittest.TestCase):
    UNIT = {"query": "", "industry": "", "from": "2026-07-01", "to": "", "limit": 10, "jurisdiction": "gb"}

    def setUp(self):
        p = mock.patch.dict(os.environ, {"OPENCORPORATES_API_TOKEN": "tok-SECRET"})
        p.start()
        self.addCleanup(p.stop)

    def test_row(self):
        c = {"name": "EXAMPLE LTD", "company_number": "01234567", "jurisdiction_code": "gb",
             "incorporation_date": "2026-08-01", "current_status": "Active", "registered_address_in_full": "1 Test St, Leeds",
             "registered_address": {"locality": "Leeds"}, "opencorporates_url": "https://opencorporates.com/companies/gb/01234567"}
        r = opencorporates.row(c, self.UNIT)
        self.assertEqual(r["legal"]["registry_ids"], {"opencorporates": "gb/01234567", "company_number": "01234567"})
        self.assertEqual((r["country"], r["city"]), ("GB", "Leeds"))
        self.assertEqual(r["signals"][0]["type"], "new_registration")

    def test_paginates(self):
        page = lambda n, items: {"results": {"companies": [{"company": {"name": f"C{i}", "company_number": str(i),
                                                                       "jurisdiction_code": "gb"}} for i in items],
                                             "page": n, "total_pages": 2}}
        f = FakeFetcher({"https://api.opencorporates.com/v0.4/companies/search?": page(1, range(5))})
        f.routes["https://api.opencorporates.com/v0.4/companies/search?per_page=100&order=incorporation_date&inactive=false&jurisdiction_code=gb&incorporation_date=2026-07-01%3A&page=2"] = page(2, range(5, 9))
        rows = opencorporates.collect_unit(mock.Mock(fetcher=f), self.UNIT)
        self.assertEqual(len(rows), 9)

    def test_refused_token_stops_and_is_not_cached(self):
        f = FakeFetcher({"https://api.opencorporates.com/": (401, "{}")})
        with self.assertRaises(Blocked) as e:
            opencorporates.get(f, "companies/search", {"q": "x"})
        self.assertNotIn("tok-SECRET", str(e.exception))
        self.assertEqual(len(f.forgotten), 1)


class SourcesTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = pathlib.Path(self.tmp.name)
        env = mock.patch.dict(os.environ, {"LEADGEN_HOME": str(self.root)})
        env.start()
        self.addCleanup(env.stop)
        self.ws = self.root / "leadgen_sources"
        self.ws.mkdir()
        (self.ws / "chamber.py").write_text(ADAPTER)
        self.camp = Campaign.create("t", root=self.root)
        self.camp.config["sources"] = [{"type": "chamber"}]
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
        self.assertEqual(sources.load("chamber", self.root, workspace_ok=True).WORKSPACE, str((self.ws / "chamber.py").resolve()))
        (self.camp.dir / "campaign.toml").write_text('[[sources]]\ntype = "chamber"\npages = {}\n')
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
                sources.load(name, self.root, workspace_ok=True)
        (self.ws / "broken.py").write_text("NAME = 'other'\n")
        with self.assertRaises(KeyError):
            sources.load("broken", self.root, workspace_ok=True)

    def test_workspace_code_runs_only_when_a_campaign_names_it(self):
        marker = self.root / "ran"
        (self.ws / "evil.py").write_text(f"open({str(marker)!r}, 'w').close()\n")
        (self.root / "sources").mkdir()  # a generic folder name is never a workspace adapter dir
        (self.root / "sources/osm2.py").write_text(f"open({str(marker)!r}, 'w').close()\n")
        with self.assertRaises(KeyError):
            sources.load("evil", self.root)                 # not named by a campaign
        code, res = self.cli("sources")                     # listing never imports
        self.assertIn("evil", [r["name"] for r in res["sources"]])
        (self.camp.dir / "raw/evil/2026-01-01").mkdir(parents=True)  # raw data for an unconfigured adapter
        (self.camp.dir / "raw/evil/2026-01-01/x.jsonl").write_text('{"name": "x"}\n')
        sources.load_raw(self.camp, log=self.logs.append)
        self.assertFalse(marker.exists())
        self.assertTrue(any("raw/evil skipped" in m for m in self.logs))

    def test_template_is_a_working_adapter(self):
        src = (PLUGIN_ROOT / "templates/source.py").read_text().replace('NAME = "TODO_name"', 'NAME = "tmpl"')
        (self.ws / "tmpl.py").write_text(src)
        mod = sources.load("tmpl", self.root, workspace_ok=True)
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
