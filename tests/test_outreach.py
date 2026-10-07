import datetime
import pathlib
import tempfile
import unittest

from leadgen.core import schema
from leadgen.core.campaign import Campaign
from leadgen.core.store import read_jsonl, write_jsonl
from leadgen.outreach import compliance, drafts, send
from leadgen.outreach.suppression import Suppression

EV = [{"fact": "site copyright 2019", "source": "http://a.test/"}]
OUT = {"compliance": "gdpr", "sender_name": "Sam", "sender_company": "Sam Studio", "unsubscribe_text": "Reply 'no'.",
       "send_delay": 0, "min_tier": "B"}


class FakeTransport:
    def __init__(self):
        self.msgs = []

    def send(self, msg):
        self.msgs.append(msg)


def lead(i, tier="A", **kw):
    l = schema.empty_lead()
    l.update(id=i, domain=i, tier=tier, score=50, emails=[{"value": f"info@{i}", "verified": "mx", "type": "generic"}], **kw)
    return l


class OutreachTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        root = pathlib.Path(self.tmp.name)
        self.camp = Campaign.create("t", root=root)
        self.set_out(**OUT)
        write_jsonl(self.camp.leads_path, [lead("a.test"), lead("b.test"), lead("c.test", tier="C"), lead("d.test")])
        drafts.Drafts(self.camp.outreach_dir / "drafts.jsonl").add(
            [{"lead_id": x, "subject": "Hi", "body": f"Hello {x}", "evidence": EV} for x in ("a.test", "b.test", "c.test", "d.test")]
            + [{"lead_id": "a.test", "step": 2, "subject": "Re", "body": "Following up", "evidence": EV},
               {"lead_id": "a.test", "channel": "telegram", "body": "hi", "evidence": EV}])
        Suppression(self.camp.suppression_path()).add(["@d.test"])

    def tearDown(self):
        self.tmp.cleanup()

    def set_out(self, **kw):
        self.camp.config["outreach"].update(kw)

    def test_draft_validation(self):
        for bad in ({"lead_id": "a.test", "body": "x", "subject": "s"},  # no evidence
                    {"lead_id": "a.test", "body": "x", "subject": "s", "evidence": [{"fact": "f"}]},  # no source
                    {"lead_id": "a.test", "body": "x", "evidence": EV},  # email without subject
                    {"lead_id": "zz.test", "body": "x", "subject": "s", "evidence": EV}):  # unknown lead
            with self.subTest(d=bad), self.assertRaises(drafts.DraftError):
                drafts.validate(bad, {"a.test": {}})

    def test_off_refuses_and_dry_run_plans(self):
        self.set_out(send_mode="off")
        with self.assertRaises(send.SendRefused):
            send.run(self.camp, transport=FakeTransport(), log=lambda m: None)
        res = send.run(self.camp, dry_run=True)
        self.assertEqual([r["lead_id"] for r in res["ready"]], ["a.test", "b.test"])
        reasons = {s["draft_id"]: s["reason"] for s in res["skipped"]}
        self.assertIn("below min_tier", reasons["c.test:1:email"])
        self.assertEqual(reasons["d.test:1:email"], "suppressed")
        self.assertEqual(reasons["a.test:2:email"], "step 1 not sent yet")
        self.assertNotIn("a.test:1:telegram", reasons)

    def test_compliance_blocks(self):
        self.set_out(send_mode="auto", sender_company="")
        with self.assertRaises(send.SendRefused):
            send.run(self.camp, transport=FakeTransport(), log=lambda m: None)
        self.assertTrue(compliance.issues({"compliance": "ru", "sender_name": "a", "sender_company": "b",
                                           "unsubscribe_text": "c"}))

    def test_confirm_flow_caps_and_idempotency(self):
        self.set_out(send_mode="confirm", daily_cap=1)
        res = send.run(self.camp, transport=FakeTransport(), log=lambda m: None)
        self.assertEqual(len(res["ready"]), 1)
        self.assertTrue(any(s["reason"] == "daily_cap reached" for s in res["skipped"]))
        bid = res["batch"]
        t = FakeTransport()
        out = send.run(self.camp, approve=bid, transport=t, log=lambda m: None)
        self.assertEqual(len(out["sent"]), 1)
        msg = t.msgs[0]
        self.assertEqual(msg["To"], "info@a.test")
        self.assertIn("Sam Studio", msg.get_content())
        self.assertIn("Reply 'no'.", msg.get_content())
        self.assertEqual(next(read_jsonl(self.camp.leads_path))["status"], "sent")
        with self.assertRaises(send.SendRefused):  # a batch is single-use
            send.run(self.camp, approve=bid, transport=FakeTransport(), log=lambda m: None)
        res = send.run(self.camp, dry_run=True)  # cap used up today
        self.assertEqual(res["ready"], [])

    def test_changed_draft_is_not_sent(self):
        self.set_out(send_mode="confirm")
        bid = send.run(self.camp, transport=FakeTransport(), log=lambda m: None)["batch"]
        drafts.Drafts(self.camp.outreach_dir / "drafts.jsonl").add(
            [{"lead_id": "a.test", "subject": "Hi", "body": "Different text", "evidence": EV}])
        t = FakeTransport()
        out = send.run(self.camp, approve=bid, transport=t, log=lambda m: None)
        self.assertEqual([m["To"] for m in t.msgs], ["info@b.test"])
        self.assertTrue(any("changed since the preview" in s["reason"] for s in out["skipped"]))

    def test_followup_waits(self):
        self.set_out(send_mode="auto", followup_days=4)
        send.run(self.camp, transport=FakeTransport(), log=lambda m: None)
        res = send.run(self.camp, dry_run=True)
        self.assertTrue(any(s["reason"].startswith("follow-up due") for s in res["skipped"]))
        # pretend step 1 went out 5 days ago
        p = self.camp.outreach_dir / "sent.jsonl"
        rows = list(read_jsonl(p))
        old = (send.now() - datetime.timedelta(days=5)).isoformat(timespec="seconds")
        write_jsonl(p, [{**r, "sent_at": old} for r in rows])
        t = FakeTransport()
        send.run(self.camp, transport=t, log=lambda m: None)
        self.assertEqual([m["To"] for m in t.msgs], ["info@a.test"])
        self.assertTrue(t.msgs[0]["In-Reply-To"])

    def test_suppression_normalizes(self):
        s = Suppression(self.camp.suppression_path())
        s.add(["Jane@X.test", "+351 21 000 0000", "https://www.y.test/page"])
        s = Suppression(self.camp.suppression_path())
        self.assertTrue(s.email_blocked("jane@x.test"))
        self.assertFalse(s.email_blocked("bob@x.test"))
        self.assertTrue(s.email_blocked("anyone@y.test"))
        self.assertTrue(s.lead_blocked({"phones": ["351210000000"]}))

    def test_deeplinks(self):
        l = lead("a.test", socials={"telegram": ["https://t.me/acme"]}, phones=["351210000000"])
        self.assertEqual(drafts.deeplink({"channel": "telegram", "body": "hi"}, l), "https://t.me/acme")
        self.assertEqual(drafts.deeplink({"channel": "whatsapp", "body": "hi there"}, l), "https://wa.me/351210000000?text=hi%20there")
        self.assertTrue(drafts.deeplink({"channel": "email", "subject": "S", "body": "B"}, l).startswith("mailto:info@a.test?"))


if __name__ == "__main__":
    unittest.main()
