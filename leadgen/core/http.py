"""Polite HTTP: per-host throttle, on-disk cache, SSL fallback, IDN hosts, block detection.

Every source goes through Fetcher so that re-runs never re-fetch cached pages and no host is hit faster
than its delay. Stdlib only.
"""
from __future__ import annotations

import hashlib
import json
import pathlib
import ssl
import threading
import time
import urllib.error
import urllib.parse
import urllib.request

UA_BROWSER = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130 Safari/537.36"
UA_BOT = "leadgen/0.1 (+https://github.com/PeacexF/claude-lead-gen)"


class Blocked(Exception):
    """The source answered with a rate limit, captcha, or access wall. Stop the run; don't retry hard."""


class Fetcher:
    def __init__(self, cache_dir: pathlib.Path | None = None, delay: float = 1.0, ua: str = UA_BROWSER,
                 lang: str = "en", timeout: float = 25.0, host_delays: dict[str, float] | None = None):
        self.cache_dir = cache_dir
        self.delay = delay
        self.ua = ua
        self.lang = lang
        self.timeout = timeout
        self.host_delays = host_delays or {}
        self._last: dict[str, float] = {}
        self._lock = threading.Lock()
        self._host_locks: dict[str, threading.Lock] = {}

    # --- helpers ---------------------------------------------------------
    @staticmethod
    def idna_url(url: str) -> str:
        if not url.startswith(("http://", "https://")):
            url = "http://" + url
        parts = urllib.parse.urlsplit(url)
        host = parts.hostname or ""
        if host and not host.isascii():
            netloc = host.encode("idna").decode()
            if parts.port:
                netloc += f":{parts.port}"
            url = parts._replace(netloc=netloc).geturl()
        # percent-encode non-ASCII path/query characters
        return urllib.parse.quote(url, safe=":/?#[]@!$&'()*+,;=%~")

    def _cache_path(self, key: str) -> pathlib.Path | None:
        if not self.cache_dir:
            return None
        h = hashlib.sha1(key.encode()).hexdigest()
        return self.cache_dir / h[:2] / h

    def _wait(self, host: str) -> None:
        with self._lock:
            lock = self._host_locks.setdefault(host, threading.Lock())
        lock.acquire()
        try:
            delay = self.host_delays.get(host, self.delay)
            wait = self._last.get(host, 0) + delay - time.monotonic()
            if wait > 0:
                time.sleep(wait)
            self._last[host] = time.monotonic()
        finally:
            lock.release()

    # --- main API --------------------------------------------------------
    def request(self, url: str, data: bytes | None = None, headers: dict | None = None, method: str | None = None,
                cache: bool = True, ttl: float | None = None, max_bytes: int = 5_000_000,
                html_only: bool = False, insecure_fallback: bool = False) -> tuple[int, str, str]:
        """Return (status, final_url, text). Cached by (method, url, body).

        insecure_fallback: retry without certificate verification after an SSL error. Only for reading public
        business pages (the crawler records the broken certificate as a finding). Never use it for API calls
        that carry keys or for anything that sends data.
        """
        url = self.idna_url(url)
        key = json.dumps([method or ("POST" if data else "GET"), url, (data or b"").decode("utf-8", "replace")])
        cp = self._cache_path(key) if cache else None
        if cp and cp.exists() and (ttl is None or time.time() - cp.stat().st_mtime < ttl):
            rec = json.loads(cp.read_text())
            return rec["status"], rec["final"], rec["text"]
        host = urllib.parse.urlsplit(url).hostname or ""
        hdrs = {"User-Agent": self.ua, "Accept-Language": self.lang, **(headers or {})}
        self._wait(host)
        status, final, text = self._do(url, data, hdrs, method, max_bytes, html_only, insecure_fallback and data is None)
        if cp and status < 500:
            cp.parent.mkdir(parents=True, exist_ok=True)
            cp.write_text(json.dumps({"status": status, "final": final, "text": text}))
        return status, final, text

    def _do(self, url, data, hdrs, method, max_bytes, html_only, insecure_fallback):
        req = urllib.request.Request(url, data=data, headers=hdrs, method=method)
        for verify in ((True, False) if insecure_fallback else (True,)):
            ctx = ssl.create_default_context() if verify else ssl._create_unverified_context()
            try:
                with urllib.request.urlopen(req, timeout=self.timeout, context=ctx) as r:
                    ctype = r.headers.get("Content-Type", "")
                    if html_only and ctype and "html" not in ctype:
                        return r.status, r.geturl(), ""
                    raw = r.read(max_bytes)
                    charset = r.headers.get_content_charset() or "utf-8"
                    return r.status, r.geturl(), raw.decode(charset, "replace")
            except urllib.error.HTTPError as e:
                if e.code in (429,) or (e.code == 403 and "captcha" in (e.read(4000) or b"").decode("utf-8", "replace").lower()):
                    raise Blocked(f"{e.code} at {url}") from e
                body = ""
                try:
                    body = e.read(200_000).decode("utf-8", "replace")
                except Exception:
                    pass
                return e.code, url, body
            except (ssl.SSLError, urllib.error.URLError) as e:
                is_ssl = isinstance(e, ssl.SSLError) or isinstance(getattr(e, "reason", None), ssl.SSLError)
                if verify and is_ssl:
                    continue
                raise
        raise RuntimeError("unreachable")

    def text(self, url: str, **kw) -> str:
        status, _, text = self.request(url, **kw)
        if status >= 400:
            raise urllib.error.HTTPError(url, status, f"HTTP {status}", {}, None)
        return text

    def json(self, url: str, **kw):
        return json.loads(self.text(url, **kw))

    def post_json(self, url: str, payload: dict, headers: dict | None = None, **kw):
        body = json.dumps(payload).encode()
        status, _, text = self.request(url, data=body, headers={"Content-Type": "application/json", **(headers or {})}, **kw)
        if status >= 400:
            raise urllib.error.HTTPError(url, status, f"HTTP {status}: {text[:300]}", {}, None)
        return json.loads(text)

    def post_form(self, url: str, form: dict, **kw) -> str:
        body = urllib.parse.urlencode(form).encode()
        status, _, text = self.request(url, data=body, headers={"Content-Type": "application/x-www-form-urlencoded"}, **kw)
        if status >= 400:
            raise urllib.error.HTTPError(url, status, f"HTTP {status}: {text[:300]}", {}, None)
        return text
