"""Email deliverability from public DNS, over HTTPS (no key): MX, SPF, DMARC → mail provider and email checks.

For each email domain on a lead (its own domain plus the domains of its listed emails):
- MX hosts → "can receive mail" (emails at that domain get verified="mx") and the mail provider
  (Google Workspace, Microsoft 365, Zoho, Yandex 360, ...), which is a tech/buying signal on its own.
- SPF includes → sending tools (SendGrid, Mailchimp, HubSpot, ...).
- DMARC present or not.
A null MX ("0 .") or no MX means the domain doesn't take mail; its emails stay verified="none" and the lead gets a
no_mx signal. "mx" only proves the domain accepts mail, not that the mailbox exists.
"""
from __future__ import annotations

import datetime
import json
import re
import urllib.parse

from ..core import schema

DOH = ["https://cloudflare-dns.com/dns-query", "https://dns.google/resolve"]
TYPES = {"MX": 15, "TXT": 16}

# MX host suffix → provider
MX_PROVIDERS = [
    (r"(aspmx\.l\.google\.com|googlemail\.com|google\.com|smtp\.google\.com)$", "google-workspace"),
    (r"mail\.protection\.outlook\.com$|outlook\.com$|hotmail\.com$", "microsoft-365"),
    (r"zoho\.(com|eu|in|com\.au)$", "zoho"),
    (r"(mx\.yandex\.(net|ru)|yandex\.(net|ru))$", "yandex-360"),
    (r"mail\.ru$", "vk-workspace"),
    (r"protonmail\.ch$|proton\.me$", "proton"),
    (r"messagingengine\.com$", "fastmail"),
    (r"icloud\.com$|me\.com$", "icloud"),
    (r"pphosted\.com$|ppe-hosted\.com$", "proofpoint"),
    (r"mimecast\.com$", "mimecast"),
    (r"barracudanetworks\.com$", "barracuda"),
    (r"secureserver\.net$", "godaddy"),
    (r"(registrar-servers|privateemail)\.com$", "namecheap"),
    (r"(ionos|1and1|kundenserver)\.[a-z.]+$", "ionos"),
    (r"ovh\.net$", "ovh"),
    (r"hostinger\.[a-z.]+$|titan\.email$", "hostinger"),
    (r"gmx\.[a-z.]+$|web\.de$", "gmx"),
    (r"amazonaws\.com$|amazonses\.com$", "amazon"),
    (r"beget\.(com|ru)$", "beget"),
    (r"timeweb\.ru$", "timeweb"),
    (r"(reg\.ru|hosting\.reg\.ru)$", "reg-ru"),
    (r"sprinthost\.ru$", "sprinthost"),
]
SPF_TOOLS = {
    "_spf.google.com": "google-workspace", "spf.protection.outlook.com": "microsoft-365", "zoho": "zoho",
    "sendgrid.net": "sendgrid", "mailgun.org": "mailgun", "servers.mcsv.net": "mailchimp", "mandrillapp.com": "mandrill",
    "amazonses.com": "amazon-ses", "_spf.salesforce.com": "salesforce", "hubspotemail.net": "hubspot",
    "sparkpostmail.com": "sparkpost", "spf.mtasv.net": "postmark", "mailjet.com": "mailjet",
    "sendinblue.com": "brevo", "brevo.com": "brevo", "_spf.yandex.net": "yandex-360", "spf.mail.ru": "vk-workspace",
    "unisender": "unisender", "freshdesk.com": "freshdesk", "zendesk.com": "zendesk", "intercom": "intercom",
    "helpscout": "helpscout", "klaviyo": "klaviyo", "activecampaign": "activecampaign",
}


def query(fetcher, name: str, rtype: str) -> list[str]:
    """Answer data strings for one record type; [] for NXDOMAIN/no data. Tries the next resolver on failure."""
    last = None
    for ep in DOH:
        url = ep + "?" + urllib.parse.urlencode({"name": name, "type": rtype})
        try:
            status, _, text = fetcher.request(url, headers={"Accept": "application/dns-json"}, ttl=14 * 86400)
            if status != 200:
                raise RuntimeError(f"DoH {status}")
            data = json.loads(text)
        except Exception as e:  # resolver hiccup: try the other one
            last = e
            continue
        if data.get("Status") not in (0, 3):  # 0 NOERROR, 3 NXDOMAIN
            last = RuntimeError(f"DNS status {data.get('Status')}")
            continue
        return [a["data"] for a in data.get("Answer") or [] if a.get("type") == TYPES[rtype]]
    raise last or RuntimeError("DoH failed")


def mx_hosts(answers: list[str]) -> list[str]:
    """'10 aspmx.l.google.com.' → sorted hosts; a null MX ('0 .') yields []."""
    pairs = []
    for a in answers:
        parts = a.split()
        if len(parts) == 2 and parts[1] not in (".", ""):
            pairs.append((int(parts[0]) if parts[0].isdigit() else 99, parts[1].rstrip(".").lower()))
    return [h for _, h in sorted(pairs)]


def provider(hosts: list[str]) -> str | None:
    for h in hosts:
        for rx, name in MX_PROVIDERS:
            if re.search(rx, h):
                return name
    return "self-hosted/other" if hosts else None


def txt(answers: list[str]) -> list[str]:
    return ["".join(re.findall(r'"([^"]*)"', a)) or a for a in answers]


def check_domain(fetcher, domain: str) -> dict:
    mx = mx_hosts(query(fetcher, domain, "MX"))
    spf = next((t for t in txt(query(fetcher, domain, "TXT")) if t.lower().startswith("v=spf1")), None)
    dmarc = next((t for t in txt(query(fetcher, "_dmarc." + domain, "TXT")) if t.lower().startswith("v=dmarc1")), None)
    tools = sorted({v for k, v in SPF_TOOLS.items() if spf and k in spf.lower()})
    return {"domain": domain, "mx": mx[:5], "mail_provider": provider(mx), "spf": spf[:300] if spf else None,
            "spf_tools": tools, "dmarc": bool(dmarc), "dmarc_policy": (re.search(r"p=(\w+)", dmarc or "") or [None, None])[1],
            "checked": datetime.date.today().isoformat()}


def enrich(fetcher, lead: dict) -> dict:
    """Check the lead's own domain and every email domain; set emails[].verified and lead['dns']."""
    domains = list(dict.fromkeys(([lead["domain"]] if lead.get("domain") else [])
                                 + [e["value"].split("@", 1)[1] for e in lead.get("emails") or []]))
    results = {}
    for d in domains[:6]:
        try:
            results[d] = check_domain(fetcher, d)
        except Exception as e:
            results[d] = {"domain": d, "error": type(e).__name__}
    for e in lead.get("emails") or []:
        r = results.get(e["value"].split("@", 1)[1]) or {}
        if r.get("mx") and e.get("verified") in (None, "none"):
            e["verified"] = "mx"
    own = results.get(lead.get("domain")) or {}
    lead["dns"] = {**own, "email_domains": {d: {"mx": bool(r.get("mx")), "error": r.get("error")} for d, r in results.items()},
                   "checked": datetime.date.today().isoformat()}
    if own and not own.get("error") and not own.get("mx"):
        schema.add_signal(lead, "no_mx", lead["domain"], "dns")
    return lead

