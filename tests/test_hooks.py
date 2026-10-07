import importlib.util
import json
import pathlib
import subprocess
import sys
import tempfile
import unittest

HOOK = pathlib.Path(__file__).resolve().parents[1] / "hooks" / "guard.py"
spec = importlib.util.spec_from_file_location("guard", HOOK)
guard = importlib.util.module_from_spec(spec)
spec.loader.exec_module(guard)


class GuardTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = pathlib.Path(self.tmp.name)
        for slug, mode in (("c", "confirm"), ("a", "auto"), ("o", "off"), ("w", "weird")):
            d = self.root / "campaigns" / slug
            d.mkdir(parents=True)
            (d / "campaign.toml").write_text(f'[campaign]\nname = "{slug}"\n\n[outreach]\nsend_mode = "{mode}"\n')

    def level(self, cmd):
        r = guard.decide(cmd, str(self.root))
        return r[0] if r else None

    def test_send_gate(self):
        cases = {
            "leadgen send c --dry-run": None,
            "leadgen send c": None,                       # confirm: preview only
            "leadgen send a": None,                       # auto: the user chose it
            "leadgen send o": None,                       # off: the CLI refuses
            "leadgen send c --approve 1a2b3c4d": "ask",
            "leadgen --json send c --approve=1a2b3c4d": "ask",
            "/x/bin/leadgen send c --approve 1a2b": "ask",
            "python3 -m leadgen.cli send c --approve 1a2b": "ask",
            "leadgen send missing": "ask",                # can't read the campaign
            "leadgen send w": "ask",                      # unknown mode
            "leadgen send": "ask",
            "leadgen status c && leadgen send c --approve ab": "ask",
            "leadgen drafts c list": None,
        }
        for cmd, want in cases.items():
            with self.subTest(cmd=cmd):
                self.assertEqual(self.level(cmd), want)

    def test_send_gate_follows_cd_and_env(self):
        other = self.root / "elsewhere"
        other.mkdir()
        self.assertEqual(guard.decide("leadgen send c", str(other))[0], "ask")  # no campaign under cwd
        self.assertIsNone(guard.decide(f"cd {self.root} && leadgen send c", str(other)))
        self.assertIsNone(guard.decide(f"LEADGEN_HOME={self.root} leadgen send c", str(other)))

    def test_pii_guard(self):
        (self.root / "docs").mkdir()
        cases = {
            "git add campaigns/x/leads.jsonl": "deny",
            "git add -f campaigns/": "deny",
            "git add suppression.txt": "deny",
            "git add export.leads.csv": "deny",
            "git add leadgen_sources/chamber_fixtures/p1.html": "deny",
            "git add -f .": "deny",
            "git add -Af": "deny",
            "git -C repo add --force docs": "deny",
            "git add .": None,                            # .gitignore keeps campaign data out
            "git add -f dist/bundle.js": None,
            "git add leadgen/cli.py && git commit -m x": None,
            "git status": None,
        }
        for cmd, want in cases.items():
            with self.subTest(cmd=cmd):
                self.assertEqual(self.level(cmd), want)

    def test_hook_protocol(self):
        event = {"tool_name": "Bash", "cwd": str(self.root), "tool_input": {"command": "leadgen send c --approve ab12"}}
        out = subprocess.run([sys.executable, str(HOOK)], input=json.dumps(event), capture_output=True, text=True, check=True)
        res = json.loads(out.stdout)["hookSpecificOutput"]
        self.assertEqual((res["hookEventName"], res["permissionDecision"]), ("PreToolUse", "ask"))
        self.assertIn("ab12", res["permissionDecisionReason"])
        quiet = subprocess.run([sys.executable, str(HOOK)], input=json.dumps({**event, "tool_input": {"command": "ls"}}),
                               capture_output=True, text=True, check=True)
        self.assertEqual(quiet.stdout, "")


if __name__ == "__main__":
    unittest.main()
