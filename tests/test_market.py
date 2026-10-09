"""leadgen market: order loading across snapshots, product labels, budgets, clusters, supply, scores, the CLI."""
import contextlib
import datetime
import io
import json
import os
import pathlib
import tempfile
import tomllib
import unittest
from unittest import mock

from leadgen import cli, market
from leadgen.core.campaign import TEMPLATES, Campaign
from leadgen.core.store import write_jsonl
from leadgen.sources import telegram

TODAY = datetime.date.today().isoformat()
OLD = (datetime.date.today() - datetime.timedelta(days=500)).isoformat()

KWORK_DAY1 = [
    {"source_id": 1, "url": "https://kwork.ru/projects/1", "title": "Телеграм бот для записи клиентов в салон",
     "description": "Нужен бот", "budget": 10000, "currency": "RUB", "offers": 12, "created": f"{TODAY} 10:00:00",
     "type": "project"},
    {"source_id": 2, "url": "https://kwork.ru/projects/2", "title": "Old title", "description": "", "budget": 5000,
     "currency": "RUB", "offers": 3, "type": "project"},
]
KWORK_DAY2 = [  # project 2 again, edited: the latest snapshot wins, first_seen stays
    {"source_id": 2, "url": "https://kwork.ru/projects/2", "title": "Парсер цен конкурентов для стоматологии",
     "description": "сбор данных", "budget": 15000, "currency": "RUB", "offers": 4, "type": "project", "buyer": "clinic1"},
    {"source_id": 3, "url": "https://kwork.ru/projects/3", "title": "Интеграция формы Tilda с amoCRM",
     "description": "для стоматологической клиники", "budget": 20000, "currency": "RUB", "offers": 8, "type": "project",
     "buyer": "clinic1"},
    {"source_id": 4, "url": "https://kwork.ru/projects/4", "title": "Need a Shopify store for my shop", "description": "",
     "budget": 300, "currency": "USD", "offers": 2, "type": "project"},
]
FLRU = [
    {"source_id": 9, "url": "https://www.fl.ru/projects/9/", "title": "Вакансия: разработчик сайтов",
     "description": "стоматология, зарплата", "budget": 120000, "currency": "RUB", "offers": 1, "type": "vacancy"},
]
TG = [
    {"source_id": 5, "url": "https://t.me/orders/5", "channel": "orders", "title": "Чат-бот для салона красоты",
     "description": "бюджет 8 000 ₽", "budget": 8000, "currency": "RUB", "created": f"{OLD}T10:00:00+00:00", "type": "post"},
    {"source_id": 6, "url": "https://t.me/orders/6", "channel": "orders", "title": "Лендинг для салона красоты",
     "description": "", "budget": None, "created": f"{TODAY}T10:00:00+00:00", "type": "post"},
]


def lead(i, segment, website=None, socials=None, site=None, signals=(), emails=(), city="Kazan"):
    return {"id": f"l{i}", "segment": segment, "city": city, "website": website, "socials": socials or {},
            "site": site or {}, "signals": [{"type": t} for t in signals], "emails": list(emails), "phones": ["7900"],
            "categories": [], "rating": 4.5, "reviews": 10}


LEADS = [
    lead(1, "стоматология", "https://a.test", site={"checked": TODAY, "reachable": True, "tech": ["tilda"]},
         signals=["form_without_privacy_link"], emails=[{"value": "a@a.test"}]),
    lead(2, "стоматология", "https://b.test", site={"checked": TODAY, "reachable": True, "tech": ["wordpress"]},
         socials={"telegram": ["https://t.me/b"]}),
    lead(3, "стоматология", socials={"vk": ["https://vk.com/c"]}),
    lead(4, "стоматология", socials={"whatsapp": ["https://wa.me/1"]}, city="Kostroma"),
    lead(5, "салон красоты", socials={"telegram": ["https://t.me/e"]}),
    lead(6, "салон красоты", "https://f.test", site={"checked": TODAY, "reachable": False}),
]

MARKET = """
[[sources]]
type = "kwork"
[[sources]]
type = "flru"
[[sources]]
type = "telegram"
channels = ["orders"]

[market]
max_age_days = 365

[[market.products]]
name = "booking"
matches = "запис[ьи] клиент"

[[market.clusters]]
name = "dental"
matches = "стоматолог"

[[market.clusters]]
name = "dental_software"
matches = "стоматолог"
product = ["parser_scraper", "crm_integration"]

[[market.segments]]
name = "стоматология"
demand = "стоматолог"

[[market.segments]]
name = "салон красоты"
demand = "салон"

[[market.segments]]
name = "автосервис"
demand = "автосервис"
control = true
"""


class MarketTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = pathlib.Path(self.tmp.name)
        env = mock.patch.dict(os.environ, {"LEADGEN_HOME": str(self.root)})
        env.start()
        self.addCleanup(env.stop)
        self.addCleanup(self.tmp.cleanup)

    def run_cli(self, *argv) -> tuple[int, str]:
        out = io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(io.StringIO()):
            code = cli.main(list(argv))
        return code, out.getvalue()

    def j(self, *argv, code=0):
        c, out = self.run_cli(*argv, "--json")
        self.assertEqual(c, code, out)
        return json.loads(out)

    def study(self, extra=MARKET, leads=LEADS) -> Campaign:
        self.assertEqual(self.j("init", "s", "--niches", "--offer", "bots")["kind"], "niches")
        camp = Campaign("s", self.root)
        cfg = (camp.dir / "campaign.toml").read_text()
        (camp.dir / "campaign.toml").write_text(cfg.split("# --- Demand")[0] + extra)
        raw = camp.dir / "raw"
        write_jsonl(raw / "kwork" / "2026-09-30" / "projects.jsonl", KWORK_DAY1)
        write_jsonl(raw / "kwork" / "2026-10-01" / "projects.jsonl", KWORK_DAY2)
        write_jsonl(raw / "flru" / "2026-10-01" / "projects.jsonl", FLRU)
        write_jsonl(raw / "telegram" / "2026-10-01" / "orders.jsonl", TG)
        write_jsonl(raw / "osm" / "2026-10-01" / "x.jsonl", [{"name": "not demand"}])  # businesses: ignored
        if leads:
            write_jsonl(camp.leads_path, leads)
        return Campaign("s", self.root)

    def test_templates_parse(self):
        cfg = tomllib.loads((TEMPLATES / "niches.toml").read_text())
        self.assertEqual(cfg["market"]["score"]["gap_metric"], "gap_pct")
        self.assertNotIn("sources", cfg)  # every source is commented out: the skill picks them per market

    def test_load_and_label(self):
        camp = self.study()
        orders, dropped, cur = market.prepare(camp)
        by = {o["id"]: o for o in orders}
        self.assertEqual(dropped, {"older": 1, "excluded_type": 0, "no_rate": {"USD": 1}})  # a 500-day-old post
        self.assertEqual(len(orders), 6)
        two = by["https://kwork.ru/projects/2"]
        self.assertEqual((two["title"][:5], two["first_seen"], two["last_seen"]), ("Парсе", "2026-09-30", "2026-10-01"))
        self.assertEqual(by["https://kwork.ru/projects/1"]["date"], TODAY)
        self.assertEqual(cur, "RUB")  # most common currency with a budget
        self.assertEqual(by["https://kwork.ru/projects/1"]["product"], "booking")  # custom rule before the built-in bot rule
        self.assertEqual(two["product"], "parser_scraper")
        self.assertEqual(by["https://kwork.ru/projects/3"]["product"], "crm_integration")
        self.assertEqual(by["https://kwork.ru/projects/4"]["product"], "marketplace_ecom")
        self.assertEqual(by["https://t.me/orders/6"]["product"], "landing_site")

    def test_stats_skip_vacancies_and_other_currencies(self):
        camp = self.study()
        orders, _, cur = market.prepare(camp)
        dental = [o for o in orders if "стоматолог" in market.text_of(o)]
        st = market.stats(dental)
        self.assertEqual((st["orders"], st["with_budget"], st["median_budget"]), (3, 2, 17500))  # vacancy salary left out
        self.assertEqual(market.convert(orders, "USD", {}), {"RUB": 4})
        usd = market.stats(orders)
        self.assertEqual((usd["with_budget"], usd["median_budget"]), (1, 300))

    def test_rates(self):
        camp = self.study(extra=MARKET.replace("max_age_days = 365", 'max_age_days = 365\ncurrency = "rub"\nrates = {usd = 90}'))
        orders, dropped, cur = market.prepare(camp)
        self.assertEqual((cur, dropped["no_rate"]), ("RUB", {}))
        shop = next(o for o in orders if o["id"].endswith("/4"))
        self.assertEqual((shop["value"], shop["currency"], shop["amount"]), (300, "USD", 27000))
        r = self.j("market", "s", "orders", "--min-budget", "21000")
        self.assertEqual([o["url"] for o in r["orders"]], ["https://www.fl.ru/projects/9/", "https://kwork.ru/projects/4"])

    def test_scan(self):
        camp = self.study()
        r = self.j("market", "s", "scan")
        self.assertEqual(r["by_source"], {"kwork": 4, "flru": 1, "telegram": 1})
        self.assertEqual(r["dropped"]["no_rate"], {"USD": 1})
        self.assertEqual(r["clusters"]["dental"]["orders"], 3)
        self.assertEqual(r["clusters"]["dental_software"]["orders"], 2)  # product filter
        self.assertEqual(r["clusters"]["dental_software"]["median_budget"], 17500)
        self.assertEqual(r["clusters"]["dental_software"]["buyers"], 1)  # one buyer posted both orders
        self.assertEqual(r["clusters"]["dental"]["distinct"], 3)
        repost = [{"id": "a", "title": "Обзвон. Москва", "description": "Звонки по базе."},
                  {"id": "b", "title": "Обзвон. Сочи", "description": "Звонки по базе"}]
        self.assertEqual(market.stats([{**o, "type": "project", "offers": None} for o in repost])["distinct"], 1)

        dent = r["segments"]["стоматология"]
        self.assertEqual((dent["n"], dent["no_own_site_pct"], dent["social_only_pct"], dent["messenger_pct"]),
                         (4, 50.0, 50.0, 50.0))
        self.assertEqual((dent["sites_crawled"], dent["site_issue_pct"], dent["gap_pct"]), (2, 50.0, 75.0))
        self.assertEqual(dent["email_pct"], 25.0)
        self.assertEqual(sorted(dent["cities"]), ["Kazan", "Kostroma"])
        salon = r["segments"]["салон красоты"]
        self.assertEqual((salon["site_issue_pct"], salon["gap_pct"]), (100.0, 100.0))  # its one site is unreachable

        sc = r["scores"]
        rows = {t["segment"]: t for t in sc["segments"]}
        self.assertEqual(rows["стоматология"]["demand_orders"], 3)
        self.assertEqual(rows["салон красоты"]["demand_orders"], 2)  # kwork 1 + telegram 6 (5 is too old)
        # dental: demand 3/3, gap 75/100, reach 50/50 → 0.4 + 0.225 + 0.3; salon: 0.4·2/3 + 0.3 + 0.3
        self.assertEqual(rows["стоматология"]["score"], 0.925)
        self.assertEqual(rows["салон красоты"]["score"], 0.867)
        self.assertEqual([t["segment"] for t in sc["segments"]][-1], "автосервис")  # control rows last, unranked
        self.assertIsNone(rows["автосервис"]["gap"])
        self.assertIn("score = 0.4·distinct orders/max", sc["formula"])

        files = sorted(p.name for p in (camp.dir / "market").iterdir())
        self.assertEqual(files, ["clusters.json", "orders.jsonl", "products.json", "scores.json", "segments.json"])
        c, text = self.run_cli("market", "s", "scan")
        self.assertEqual(c, 0)
        self.assertIn("product types", text)
        self.assertIn("стоматология", text)

    def test_scan_demand_only(self):
        self.study(extra=MARKET.split("[[market.segments]]")[0], leads=None)
        r = self.j("market", "s", "scan")
        self.assertEqual((r["segments"], r["scores"], r["leads"]), ({}, None, 0))
        c, text = self.run_cli("market", "s", "scan")
        self.assertIn("nothing is scored", text)

    def test_orders_and_terms(self):
        self.study()
        r = self.j("market", "s", "orders", "--cluster", "dental", "--sort", "budget")
        self.assertEqual(r["total"], 3)
        self.assertEqual(r["orders"][0]["value"], 120000)  # the vacancy is listed; only budget stats skip it
        r = self.j("market", "s", "orders", "--product", "crm_integration,parser_scraper", "--min-budget", "16000")
        self.assertEqual([o["url"] for o in r["orders"]], ["https://kwork.ru/projects/3"])
        r = self.j("market", "s", "orders", "--match", "shopify", "--full")
        self.assertEqual(r["orders"][0]["currency"], "USD")
        self.assertIn("description", r["orders"][0])
        self.assertEqual(self.j("market", "s", "orders", "--source", "telegram")["total"], 1)
        t = self.j("market", "s", "terms")
        self.assertIn(["салона", 1], t["words"])
        self.assertEqual(t["orders"], 6)

    def test_config_errors(self):
        self.study(extra=MARKET + '\n[[market.clusters]]\nname = "bad"\nmatches = "(unclosed"\n')
        self.assertIn("bad regex", self.j("market", "s", "scan", code=1)["error"])
        self.assertIn("no [[market.clusters]] named", self.j("market", "s", "orders", "--cluster", "nope", code=1)["error"])

    def test_bad_metric(self):
        self.study(extra=MARKET + '\n[market.score]\ngap_metric = "top_tech"\n')
        self.assertIn("gap_metric", self.j("market", "s", "scan", code=1)["error"])

    def test_intent_before_product(self):
        rules = market.product_rules({"default_products": True})
        o = {"title": "Привлечение новых клиентов для создания ботов", "description": "", "category": None}
        market.label([o], rules)
        self.assertEqual(o["product"], "leadgen_sales")

    def test_order_dates(self):
        d = market.order_date
        self.assertEqual(str(d("2026-10-02 12:00:00")), "2026-10-02")
        self.assertEqual(str(d("02.10.2026")), "2026-10-02")
        self.assertEqual(str(d(1759363200)), "2025-10-02")
        self.assertIsNone(d("2 часа назад"))
        self.assertIsNone(d(None))


class TelegramBudgetTest(unittest.TestCase):
    def test_currency(self):
        self.assertEqual(telegram.budget_from_text("Бюджет: 15 000 ₽"), (15000.0, "RUB"))
        self.assertEqual(telegram.budget_from_text("budget 500 usd"), (500.0, "USD"))
        self.assertEqual(telegram.budget_from_text("no money talk"), (None, None))


if __name__ == "__main__":
    unittest.main()
