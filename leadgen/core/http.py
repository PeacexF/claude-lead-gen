"""Polite HTTP: per-host throttle, on-disk cache, SSL fallback, IDN hosts, block detection.

Every source goes through Fetcher so that re-runs never re-fetch cached pages and no host is hit faster
than its delay. Stdlib only.
"""
from __future__ import annotations

import hashlib
import http.client
import ipaddress
import json
import os
import pathlib
import socket
import ssl
import tempfile
import threading
import time
import urllib.error
import urllib.parse
import urllib.request

UA_BROWSER = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130 Safari/537.36"
UA_BOT = "leadgen/0.1 (+https://github.com/PeacexF/claude-lead-gen)"


class Blocked(Exception):
    """The source answered with a rate limit, captcha, or access wall. Stop the run; don't retry hard."""


class HTTPStatusError(Exception):
    """Non-2xx/3xx answer from text()/json()/post_*(). Carries .code and .url (no open response body)."""

    def __init__(self, url: str, code: int, detail: str = ""):
        super().__init__(f"HTTP {code} at {url}" + (f": {detail}" if detail else ""))
        self.url, self.code = url, code


class UnsafeURL(urllib.error.URLError):
    """A public_only request pointed at a non-http(s) scheme or a host that resolves to a non-public address."""


def public_ip(addr: str) -> bool:
    ip = ipaddress.ip_address(addr.split("%", 1)[0])
    if ip.version == 6 and ip.ipv4_mapped:
        ip = ip.ipv4_mapped
    return ip.is_global and not ip.is_multicast


def check_public(url: str) -> None:
    """Refuse URLs that could reach the local machine or private networks (SSRF guard for untrusted URLs).

    Fails fast before throttling. The binding check is _public_connection, which validates the address the socket
    actually connects to, so DNS rebinding between this check and the connection doesn't get through.
    """
    parts = urllib.parse.urlsplit(url)
    if parts.scheme not in ("http", "https"):
        raise UnsafeURL(f"scheme not allowed: {parts.scheme!r}")
    host = parts.hostname
    if not host:
        raise UnsafeURL("no host")
    _public_addrs(host, parts.port or (443 if parts.scheme == "https" else 80))


def _public_addrs(host: str, port: int) -> list[tuple]:
    try:
        infos = socket.getaddrinfo(host, port, type=socket.SOCK_STREAM)
    except socket.gaierror as e:
        raise urllib.error.URLError(e) from e
    bad = sorted({i[4][0] for i in infos if not public_ip(i[4][0])})
    if bad or not infos:
        raise UnsafeURL(f"non-public address for {host}: {', '.join(bad) or 'none'}")
    return infos


def _public_connection(address, timeout=socket._GLOBAL_DEFAULT_TIMEOUT, source_address=None, *a, **kw):
    """socket.create_connection that resolves once, refuses non-public addresses, and connects to a checked one."""
    host, port = address
    last = None
    for family, stype, proto, _, sockaddr in _public_addrs(host, port):
        sock = socket.socket(family, stype, proto)
        try:
            if timeout is not socket._GLOBAL_DEFAULT_TIMEOUT:
                sock.settimeout(timeout)
            if source_address:
                sock.bind(source_address)
            sock.connect(sockaddr)
            return sock
        except OSError as e:
            last = e
            sock.close()
    raise last or OSError(f"cannot connect to {host}")


class _PublicHTTPConnection(http.client.HTTPConnection):
    def __init__(self, *a, **kw):
        super().__init__(*a, **kw)
        self._create_connection = _public_connection  # __init__ sets it per instance, so override here


class _PublicHTTPSConnection(http.client.HTTPSConnection):
    def __init__(self, *a, **kw):
        super().__init__(*a, **kw)
        self._create_connection = _public_connection  # SNI and cert checks still use the hostname


class _PublicHTTPHandler(urllib.request.HTTPHandler):
    def http_open(self, req):
        return self.do_open(_PublicHTTPConnection, req)


class _PublicHTTPSHandler(urllib.request.HTTPSHandler):
    def https_open(self, req):
        return self.do_open(_PublicHTTPSConnection, req, context=self._context)


class _PublicRedirects(urllib.request.HTTPRedirectHandler):
    """Re-check every redirect target, so a public page can't bounce the crawler to 127.0.0.1 or file://."""

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        check_public(newurl)
        return super().redirect_request(req, fp, code, msg, headers, newurl)


class Fetcher:
    def __init__(self, cache_dir: pathlib.Path | None = None, delay: float = 1.0, ua: str = UA_BROWSER,
                 lang: str = "en", timeout: float = 25.0, host_delays: dict[str, float] | None = None,
                 public_only: bool = False):
        self.cache_dir = cache_dir
        self.public_only = public_only
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
                html_only: bool = False, insecure_fallback: bool = False,
                public_only: bool | None = None) -> tuple[int, str, str]:
        """Return (status, final_url, text). Cached by (method, url, body).

        public_only: refuse anything but http(s) to public addresses, including after redirects. Set it (here or
        on the Fetcher) whenever the URL comes from scraped or imported data rather than from adapter code.

        insecure_fallback: retry without certificate verification after an SSL error. Only for reading public
        business pages (the crawler records the broken certificate as a finding). Never use it for API calls
        that carry keys or for anything that sends data.
        """
        url = self.idna_url(url)
        guard = self.public_only if public_only is None else public_only
        key = json.dumps([method or ("POST" if data else "GET"), url, (data or b"").decode("utf-8", "replace")])
        cp = self._cache_path(key) if cache else None
        if cp and cp.exists() and (ttl is None or time.time() - cp.stat().st_mtime < ttl):
            rec = json.loads(cp.read_text())
            return rec["status"], rec["final"], rec["text"]
        host = urllib.parse.urlsplit(url).hostname or ""
        hdrs = {"User-Agent": self.ua, "Accept-Language": self.lang, **(headers or {})}
        if guard:
            check_public(url)
        self._wait(host)
        status, final, text = self._do(url, data, hdrs, method, max_bytes, html_only, insecure_fallback and data is None,
                                       guard)
        if cp and status < 500:
            cp.parent.mkdir(parents=True, exist_ok=True)
            fd, tmp = tempfile.mkstemp(dir=cp.parent, prefix=".tmp-")  # atomic: workers may share a key
            with os.fdopen(fd, "w") as fh:
                fh.write(json.dumps({"status": status, "final": final, "text": text}))
            os.replace(tmp, cp)
        return status, final, text

    def _do(self, url, data, hdrs, method, max_bytes, html_only, insecure_fallback, public_only=False):
        req = urllib.request.Request(url, data=data, headers=hdrs, method=method)
        for verify in ((True, False) if insecure_fallback else (True,)):
            ctx = ssl.create_default_context() if verify else ssl._create_unverified_context()
            if public_only:  # no proxies: the connect-time address check must see the real target
                handlers = [urllib.request.ProxyHandler({}), _PublicHTTPHandler(), _PublicHTTPSHandler(context=ctx),
                            _PublicRedirects()]
            else:
                handlers = [urllib.request.HTTPSHandler(context=ctx)]
            try:
                with urllib.request.build_opener(*handlers).open(req, timeout=self.timeout) as r:
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
                if isinstance(getattr(e, "reason", None), UnsafeURL):
                    raise e.reason from e  # do_open wraps it; surface the guard's own error
                is_ssl = isinstance(e, ssl.SSLError) or isinstance(getattr(e, "reason", None), ssl.SSLError)
                if verify and is_ssl:
                    continue
                raise
        raise RuntimeError("unreachable")

    def text(self, url: str, **kw) -> str:
        status, _, text = self.request(url, **kw)
        if status >= 400:
            raise HTTPStatusError(url, status)
        return text

    def json(self, url: str, **kw):
        return json.loads(self.text(url, **kw))

    def post_json(self, url: str, payload: dict, headers: dict | None = None, **kw):
        body = json.dumps(payload).encode()
        status, _, text = self.request(url, data=body, headers={"Content-Type": "application/json", **(headers or {})}, **kw)
        if status >= 400:
            raise HTTPStatusError(url, status, text[:300])
        return json.loads(text)

    def post_form(self, url: str, form: dict, **kw) -> str:
        body = urllib.parse.urlencode(form).encode()
        status, _, text = self.request(url, data=body, headers={"Content-Type": "application/x-www-form-urlencoded"}, **kw)
        if status >= 400:
            raise HTTPStatusError(url, status, text[:300])
        return text
