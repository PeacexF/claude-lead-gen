"""Technology fingerprints from a page's HTML: CMS/builder, ecommerce, analytics, chat, booking, forms/CRM, payments.

Each entry: name → (category, regex on lowercase HTML). Keep patterns specific (script hosts, asset paths) so a
blog post that mentions "Shopify" doesn't count. Extend freely; tests cover the matching, not the list.
"""
from __future__ import annotations

import re

TECH: dict[str, tuple[str, str]] = {
    # CMS / site builders
    "wordpress": ("cms", r"/wp-content/|/wp-includes/"),
    "woocommerce": ("ecommerce", r"woocommerce"),
    "shopify": ("ecommerce", r"cdn\.shopify\.com|myshopify\.com"),
    "wix": ("cms", r"static\.wixstatic\.com|wix-code|x-wix-"),
    "squarespace": ("cms", r"static1\.squarespace\.com|squarespace-cdn"),
    "webflow": ("cms", r"webflow\.(js|css|io)|assets\.website-files\.com|data-wf-page"),
    "framer": ("cms", r"framerusercontent\.com|framer\.com/m/"),
    "tilda": ("cms", r"tildacdn|tilda\.(ws|cc)"),
    "bitrix": ("cms", r"/bitrix/(js|templates|cache)"),
    "joomla": ("cms", r"/media/jui/|/components/com_"),
    "drupal": ("cms", r"drupal-settings-json|/sites/default/files/"),
    "ghost": ("cms", r"ghost-(portal|sdk)|content=\"ghost"),
    "hubspot-cms": ("cms", r"hs-sites\.com|/hs-fs/hubfs/"),
    "duda": ("cms", r"dudaone|multiscreensite"),
    "godaddy-builder": ("cms", r"img1\.wsimg\.com"),
    "weebly": ("cms", r"weebly\.com/"),
    "jimdo": ("cms", r"jimdo(cdn)?\.com"),
    "magento": ("ecommerce", r"mage/cookies|/static/version\d+/frontend/"),
    "prestashop": ("ecommerce", r"prestashop"),
    "opencart": ("ecommerce", r"catalog/view/theme"),
    "bigcommerce": ("ecommerce", r"cdn\d*\.bigcommerce\.com"),
    "ecwid": ("ecommerce", r"app\.ecwid\.com"),
    "insales": ("ecommerce", r"insales"),
    "flexbe": ("cms", r"flexbe"),
    "nethouse": ("cms", r"nethouse"),
    "craftum": ("cms", r"craftum"),
    "ukit": ("cms", r"ukit|ucoz"),
    "nextjs": ("framework", r"/_next/static/"),
    "nuxt": ("framework", r"/_nuxt/"),
    "gatsby": ("framework", r"___gatsby"),
    "astro": ("framework", r"astro-island|/_astro/"),
    # analytics / ads
    "google-analytics": ("analytics", r"gtag\(|google-analytics\.com/|googletagmanager\.com/gtag"),
    "google-tag-manager": ("analytics", r"googletagmanager\.com/gtm\.js"),
    "yandex-metrika": ("analytics", r"mc\.yandex\.ru/(metrika|watch)"),
    "meta-pixel": ("analytics", r"connect\.facebook\.net/[^\"']*/fbevents\.js|fbq\("),
    "linkedin-insight": ("analytics", r"snap\.licdn\.com/li\.lms-analytics"),
    "hotjar": ("analytics", r"static\.hotjar\.com"),
    "clarity": ("analytics", r"clarity\.ms/tag"),
    "tiktok-pixel": ("analytics", r"analytics\.tiktok\.com"),
    "vk-pixel": ("analytics", r"vk\.com/js/api/openapi|top-fwz1\.mail\.ru"),
    "plausible": ("analytics", r"plausible\.io/js"),
    # chat / support
    "intercom": ("chat", r"widget\.intercom\.io|intercomcdn"),
    "drift": ("chat", r"js\.driftt\.com"),
    "crisp": ("chat", r"client\.crisp\.chat"),
    "tawk": ("chat", r"embed\.tawk\.to"),
    "livechat": ("chat", r"cdn\.livechatinc\.com"),
    "zendesk": ("chat", r"static\.zdassets\.com|zopim"),
    "hubspot-chat": ("chat", r"js\.usemessages\.com"),
    "freshchat": ("chat", r"wchat\.freshchat\.com"),
    "tidio": ("chat", r"code\.tidio\.co"),
    "jivo": ("chat", r"code\.jivo(site)?\.(ru|com)"),
    "whatsapp-widget": ("chat", r"wa\.me/|api\.whatsapp\.com/send"),
    # booking / scheduling
    "calendly": ("booking", r"calendly\.com/"),
    "acuity": ("booking", r"acuityscheduling\.com"),
    "setmore": ("booking", r"setmore\.com"),
    "simplybook": ("booking", r"simplybook\.(me|it|asia)"),
    "square-appointments": ("booking", r"square\.site|squareup\.com/appointments"),
    "booksy": ("booking", r"booksy\.com"),
    "fresha": ("booking", r"fresha\.com"),
    "treatwell": ("booking", r"treatwell\."),
    "doctolib": ("booking", r"doctolib\."),
    "zocdoc": ("booking", r"zocdoc\.com"),
    "opentable": ("booking", r"opentable\.(com|co\.uk)"),
    "resy": ("booking", r"resy\.com"),
    "thefork": ("booking", r"thefork\."),
    "yclients": ("booking", r"yclients\.com"),
    "dikidi": ("booking", r"dikidi\.(net|ru)"),
    "cal-com": ("booking", r"cal\.com/"),
    # forms / CRM / marketing
    "hubspot": ("crm", r"js\.hs-scripts\.com|js\.hsforms\.net|hs-analytics"),
    "salesforce": ("crm", r"pardot\.com|salesforce\.com/servlet"),
    "zoho": ("crm", r"zoho\.(com|eu)/(crm|salesiq)|salesiq\.zoho"),
    "pipedrive": ("crm", r"pipedrivewebforms|leadbooster"),
    "amocrm": ("crm", r"amocrm\.(ru|com)|amoforms"),
    "bitrix24": ("crm", r"bitrix24\.(ru|com|by|kz)/b\d+/crm/form|b24-form"),
    "mailchimp": ("email-marketing", r"list-manage\.com|chimpstatic\.com"),
    "klaviyo": ("email-marketing", r"klaviyo\.com"),
    "activecampaign": ("email-marketing", r"activehosted\.com|trackcmp\.net"),
    "typeform": ("forms", r"typeform\.com"),
    "jotform": ("forms", r"jotform\.(com|us)"),
    "google-forms": ("forms", r"docs\.google\.com/forms"),
    "marquiz": ("forms", r"marquiz"),
    "contact-form-7": ("forms", r"wpcf7"),
    # payments
    "stripe": ("payments", r"js\.stripe\.com"),
    "paypal": ("payments", r"paypal\.com/sdk|paypalobjects"),
    "yookassa": ("payments", r"yookassa|yoomoney"),
    "cloudpayments": ("payments", r"cloudpayments"),
    # consent / cookies
    "cookiebot": ("consent", r"consent\.cookiebot\.com"),
    "onetrust": ("consent", r"cdn\.cookielaw\.org|onetrust"),
    "cookieyes": ("consent", r"cookieyes\.com"),
}
_COMPILED = {k: (cat, re.compile(rx)) for k, (cat, rx) in TECH.items()}

BUILDER_ORDER = [k for k, (c, _) in TECH.items() if c in ("cms", "ecommerce")]


def detect(html: str) -> list[str]:
    low = html.lower()
    return [k for k, (_, rx) in _COMPILED.items() if rx.search(low)]


def builder(found: list[str]) -> str:
    for k in BUILDER_ORDER:
        if k in found:
            return k
    for k in ("nextjs", "nuxt", "gatsby", "astro"):
        if k in found:
            return k
    return "other"


def category(name: str) -> str | None:
    return TECH.get(name, (None,))[0]
