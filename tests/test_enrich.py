import unittest

from leadgen.core import schema
from leadgen.enrich import dns, jobs, registry, site, tech

from .fakes import FakeFetcher, fixture

INN = "5012345672"  # synthetic, checksum-valid


def site_fetcher():
    base = "http://harbor-dental.test"
    return FakeFetcher({base + "/": fixture("site/home.html"), base + "/contact": fixture("site/contact.html"),
                        base + "/team/": fixture("site/team.html"), base + "/about-us/": "<html>about</html>"})


class SiteCrawlTest(unittest.TestCase):
    def setUp(self):
        self.f = site_fetcher()
        self.r = site.crawl(self.f, "http://harbor-dental.test/", max_inner=4)

    def test_follows_only_same_host_inner_pages(self):
        self.assertTrue(self.r["reachable"])
        self.assertIn("http://harbor-dental.test/contact", self.f.calls)
        self.assertNotIn("http://harbor-dental.test/cart/", self.f.calls)
        self.assertFalse(any("elsewhere" in c for c in self.f.calls))

    def test_contacts(self):
        self.assertEqual(self.r["emails"][0], "hello@harbor-dental.test")  # mailto links first, then page text
        self.assertEqual(set(self.r["emails"]), {"hello@harbor-dental.test", "bookings@harbor-dental.test",
                                                 "jane.doe@harbor-dental.test"})
        self.assertFalse(any("sentry" in e or "2x" in e for e in self.r["emails"]))
        self.assertEqual(self.r["phones"], ["+15550100199"])
        self.assertEqual(self.r["socials"]["facebook"], ["https://www.facebook.com/harbordentalstudio"])
        self.assertIn("instagram", self.r["socials"])

    def test_legal_ids(self):
        ids = self.r["registry_ids"]
        self.assertEqual(ids["inn"], INN)  # the bad-checksum ИНН is dropped
        self.assertEqual(ids["ogrn"], "1027700132195")
        self.assertEqual(ids["company_number"], "01234567")
        self.assertEqual(ids["vat"], "GB123456789")
        self.assertTrue(any("Harbor Dental Studio LLC" in n for n in self.r["legal_names"]))

    def test_tech_health_and_boards(self):
        self.assertIn("wordpress", self.r["tech"])
        self.assertIn("google-tag-manager", self.r["tech"])
        self.assertEqual(self.r["builder"], "wordpress")
        self.assertEqual(self.r["copyright_year"], 2019)
        self.assertFalse(self.r["mobile"])
        self.assertTrue(self.r["has_form"])
        self.assertEqual(self.r["job_boards"][0]["ats"], "lever")
        self.assertEqual(self.r["job_boards"][0]["token"], "harbordental")

    def test_people(self):
        names = {p["name"]: p["role"].lower() for p in self.r["people"]}
        self.assertEqual(names, {"Jane Doe": "founder", "Mark Example": "practice manager"})
        got = {p["name"]: p["role"].lower() for p in site.people_from("Leadership. CEO: John Smith. Contact us today")}
        self.assertEqual(got, {"John Smith": "ceo"})
        got = {p["name"]: p["role"] for p in site.people_from("Генеральный директор Иванов Иван Петрович, тел.")}
        self.assertEqual(got, {"Иванов Иван Петрович": "Генеральный директор"})

    def test_apply_adds_contacts_and_signals(self):
        lead = schema.empty_lead()
        lead.update(id="harbor-dental.test", website="http://harbor-dental.test/", domain="harbor-dental.test")
        site.apply(lead, self.r)
        self.assertEqual(lead["legal"]["registry_ids"]["inn"], INN)
        types = {s["type"] for s in lead["signals"]}
        self.assertTrue({"outdated_site", "no_https", "not_mobile_friendly", "form_without_privacy_link"} <= types)
        self.assertTrue(all(e["verified"] == "none" for e in lead["emails"]))
        self.assertEqual(lead["site"]["job_boards"][0]["token"], "harbordental")

    def test_unreachable(self):
        r = site.crawl(FakeFetcher({}), "http://nothing.test/")
        self.assertFalse(r["reachable"])
        self.assertEqual(r["status"], 404)


class InnTest(unittest.TestCase):
    def test_checksums(self):
        self.assertTrue(site.inn_ok(INN))
        self.assertFalse(site.inn_ok("1234567890"))
        self.assertTrue(site.inn_ok("500100732259"))  # 12-digit individual form, checksum-valid
        self.assertFalse(site.inn_ok("500100732250"))


class TechTest(unittest.TestCase):
    def test_detect_and_builder(self):
        found = tech.detect('<script src="https://cdn.shopify.com/s/x.js"></script><script src="https://js.stripe.com/v3">')
        self.assertEqual(set(found), {"shopify", "stripe"})
        self.assertEqual(tech.builder(found), "shopify")
        self.assertEqual(tech.builder([]), "other")


def doh(answers: dict):
    """FakeFetcher routes for DoH: {(name, type): [data, ...]}; anything else is NXDOMAIN."""
    routes = {"https://cloudflare-dns.com/dns-query": {"Status": 3}}
    for (name, rtype), data in answers.items():
        routes[f"https://cloudflare-dns.com/dns-query?name={name}&type={rtype}"] = {
            "Status": 0, "Answer": [{"type": dns.TYPES[rtype], "data": d} for d in data]}
    return FakeFetcher(routes)


class DnsTest(unittest.TestCase):
    def test_parse_helpers(self):
        self.assertEqual(dns.mx_hosts(["20 alt1.aspmx.l.google.com.", "10 aspmx.l.google.com."]),
                         ["aspmx.l.google.com", "alt1.aspmx.l.google.com"])
        self.assertEqual(dns.mx_hosts(["0 ."]), [])
        self.assertEqual(dns.provider(["acme-com.mail.protection.outlook.com"]), "microsoft-365")
        self.assertEqual(dns.provider(["mx.acme.test"]), "self-hosted/other")
        self.assertIsNone(dns.provider([]))
        self.assertEqual(dns.txt(['"v=spf1 include:" "_spf.google.com ~all"']), ["v=spf1 include:_spf.google.com ~all"])

    def test_enrich_marks_emails_and_provider(self):
        f = doh({("acme.test", "MX"): ["10 aspmx.l.google.com."],
                 ("acme.test", "TXT"): ['"v=spf1 include:_spf.google.com include:sendgrid.net ~all"'],
                 ("_dmarc.acme.test", "TXT"): ['"v=DMARC1; p=quarantine"'],
                 ("dead.test", "MX"): ["0 ."]})
        lead = schema.empty_lead()
        lead.update(id="acme.test", domain="acme.test",
                    emails=[{"value": "info@acme.test", "verified": "none"}, {"value": "x@dead.test", "verified": "none"}])
        dns.enrich(f, lead)
        self.assertEqual(lead["dns"]["mail_provider"], "google-workspace")
        self.assertEqual(lead["dns"]["spf_tools"], ["google-workspace", "sendgrid"])
        self.assertEqual(lead["dns"]["dmarc_policy"], "quarantine")
        self.assertEqual([e["verified"] for e in lead["emails"]], ["mx", "none"])
        self.assertNotIn("no_mx", {s["type"] for s in lead["signals"]})

    def test_no_mx_signal(self):
        lead = schema.empty_lead()
        lead.update(id="nomail.test", domain="nomail.test")
        dns.enrich(doh({}), lead)
        self.assertIn("no_mx", {s["type"] for s in lead["signals"]})


class JobsTest(unittest.TestCase):
    def lead(self, **kw):
        l = schema.empty_lead()
        l.update(id="acme.test", domain="acme.test", name="Acme Robotics", **kw)
        return l

    def test_guesses(self):
        self.assertEqual(jobs.guesses(self.lead()), ["acme", "acmerobotics", "acme-robotics"])

    def test_guessed_board_needs_proof(self):
        other = [{"text": "Join Acme Plumbing in Ohio", "categories": {"location": "Ohio"}, "hostedUrl": "u", "descriptionPlain": "Acme Plumbing"}]
        mine = [{"text": "Robot engineer", "categories": {}, "hostedUrl": "https://jobs.lever.co/acme/1",
                 "descriptionPlain": "At Acme Robotics (acme.test) we build robots", "createdAt": 1767225600000}]
        l = self.lead()
        jobs.enrich(FakeFetcher({"https://api.lever.co/v0/postings/acme?": other}), l)
        self.assertEqual(l["jobs"]["boards"], [])
        l = self.lead()
        jobs.enrich(FakeFetcher({"https://api.lever.co/v0/postings/acme?": mine}), l)
        self.assertEqual(l["jobs"]["open_roles"], 1)
        self.assertIn("hiring", {s["type"] for s in l["signals"]})

    def test_greenhouse_company_name_and_site_link(self):
        gh = {"jobs": [{"title": "SRE", "company_name": "Acme Robotics", "absolute_url": "https://x/1",
                        "location": {"name": "Remote"}, "first_published": "2026-09-01T00:00:00Z"}]}
        l = self.lead()
        jobs.enrich(FakeFetcher({"https://boards-api.greenhouse.io/v1/boards/acmerobotics/jobs": gh}), l)
        self.assertEqual(l["jobs"]["boards"][0]["token"], "acmerobotics")
        # a board linked from the site is trusted without the name check
        l = self.lead(site={"job_boards": [{"ats": "ashby", "token": "acme-hq"}]})
        f = FakeFetcher({"https://api.ashbyhq.com/posting-api/job-board/acme-hq": {"jobs": [{"title": "PM", "jobUrl": "u"}]}})
        jobs.enrich(f, l)
        self.assertTrue(l["jobs"]["boards"][0]["linked_from_site"])
        self.assertEqual(f.calls[0], "https://api.ashbyhq.com/posting-api/job-board/acme-hq")


class RegistryTest(unittest.TestCase):
    def test_rkn_found_and_missing(self):
        url = registry.RKN_URL.format(inn=INN)
        lead = schema.empty_lead()
        lead["legal"]["registry_ids"]["inn"] = INN
        registry.enrich(FakeFetcher({url: fixture("rkn/found.html")}), lead, ["rkn"])
        self.assertTrue(lead["registry"]["rkn"]["registered"])
        self.assertEqual(lead["registry"]["rkn"]["by_inn"][INN]["entries"][0]["regn"], "77-00-000001")
        self.assertIn("Пример", lead["legal"]["name"])

        lead = schema.empty_lead()
        lead["legal"]["registry_ids"]["inn"] = INN
        registry.enrich(FakeFetcher({url: fixture("rkn/empty.html")}), lead, ["rkn"])
        self.assertFalse(lead["registry"]["rkn"]["registered"])
        self.assertIn("not_in_pd_registry", {s["type"] for s in lead["signals"]})

    def test_no_ids_no_lookup(self):
        f = FakeFetcher({})
        lead = registry.enrich(f, schema.empty_lead(), ["rkn"])
        self.assertEqual(lead["registry"], {})
        self.assertEqual(f.calls, [])


if __name__ == "__main__":
    unittest.main()
