import unittest

from leadgen.core import http
from leadgen.enrich import site


class PublicOnlyTest(unittest.TestCase):
    def test_refuses_private_and_special_addresses(self):
        for url in ("http://127.0.0.1/", "http://localhost:8080/x", "http://10.1.2.3/", "http://192.168.0.1/",
                    "http://172.16.5.5/", "http://169.254.169.254/latest/meta-data/", "http://[::1]/",
                    "http://[::ffff:127.0.0.1]/", "http://0.0.0.0/", "http://100.64.0.1/", "http://224.0.0.1/"):
            with self.subTest(url=url), self.assertRaises(http.UnsafeURL):
                http.check_public(url)

    def test_refuses_other_schemes(self):
        for url in ("file:///etc/passwd", "ftp://8.8.8.8/x", "gopher://8.8.8.8/"):
            with self.subTest(url=url), self.assertRaises(http.UnsafeURL):
                http.check_public(url)

    def test_allows_public_ip(self):
        http.check_public("http://8.8.8.8/")
        http.check_public("https://[2606:4700:4700::1111]/")

    def test_redirect_to_private_is_refused(self):
        h = http._PublicRedirects()
        with self.assertRaises(http.UnsafeURL):
            h.redirect_request(None, None, 302, "Found", {}, "http://127.0.0.1/admin")
        with self.assertRaises(http.UnsafeURL):
            h.redirect_request(None, None, 302, "Found", {}, "file:///etc/passwd")

    def test_fetcher_guard_runs_before_network(self):
        f = http.Fetcher(delay=0)
        with self.assertRaises(http.UnsafeURL):
            f.request("http://127.0.0.1:9/", public_only=True)
        with self.assertRaises(http.UnsafeURL):
            http.Fetcher(delay=0, public_only=True).request("http://169.254.169.254/")

    def test_connect_time_check_blocks_rebinding(self):
        # the pre-check passes (public name), but the socket layer re-resolves and must refuse a private answer
        import socket
        from unittest import mock
        fake = [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("127.0.0.1", 80))]
        with mock.patch("socket.getaddrinfo", return_value=fake), self.assertRaises(http.UnsafeURL):
            http._public_connection(("rebind.example", 80), 2)

    def test_public_only_surfaces_unsafe_from_connect(self):
        from unittest import mock
        f = http.Fetcher(delay=0)
        with mock.patch.object(http, "check_public"), self.assertRaises(http.UnsafeURL):
            f.request("http://127.0.0.1:9/", public_only=True, cache=False)

    def test_crawler_refuses_internal_site(self):
        r = site.crawl(http.Fetcher(delay=0), "http://127.0.0.1:9/")
        self.assertFalse(r["reachable"])
        self.assertEqual(r["error"], "UnsafeURL")


class _Resp:
    status, headers = 200, None

    def __init__(self, url, body):
        import email.message
        self.url, self.body, self.headers = url, body, email.message.Message()
        self.headers["Content-Type"] = "text/html; charset=utf-8"

    def geturl(self):
        return self.url

    def read(self, n=-1):
        return self.body

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


class CertFallbackTest(unittest.TestCase):
    """A broken certificate is a finding (cert_ok False), not a dead site; a flaky handshake is not a broken cert."""

    def setUp(self):
        import pathlib, ssl, tempfile, urllib.error, urllib.request
        from unittest import mock
        self.tmp = tempfile.TemporaryDirectory()
        self.cache = pathlib.Path(self.tmp.name)
        self.verified_fails = 10**6  # how many verified attempts fail before one succeeds
        self.error = lambda: ssl.SSLCertVerificationError("certificate has expired")
        self.opens = []

        def build_opener(*handlers):
            ctx = next(h._context for h in handlers if isinstance(h, urllib.request.HTTPSHandler))
            verify = ctx.verify_mode == ssl.CERT_REQUIRED
            opener = mock.Mock()

            def open_(req, timeout=None):
                self.opens.append(verify)
                if verify and self.verified_fails > 0:
                    self.verified_fails -= 1
                    raise urllib.error.URLError(self.error())
                return _Resp(req.full_url, b"<html><title>Clinic</title></html>")
            opener.open = open_
            return opener
        for p in (mock.patch("urllib.request.build_opener", build_opener), mock.patch.object(http, "check_public")):
            p.start()
            self.addCleanup(p.stop)
        self.addCleanup(self.tmp.cleanup)

    def fetcher(self):
        return http.Fetcher(cache_dir=self.cache, delay=0)

    def test_without_fallback_the_ssl_error_surfaces(self):
        import ssl, urllib.error
        with self.assertRaises((ssl.SSLError, urllib.error.URLError)):
            self.fetcher().request("https://expired.example/", cache=False)

    def test_broken_cert_is_reachable_with_cert_ok_false(self):
        r = site.crawl(self.fetcher(), "https://expired.example/")
        self.assertTrue(r["reachable"])
        self.assertIs(r["cert_ok"], False)

    def test_cached_insecure_page_stays_cert_ok_false(self):
        site.fetch(self.fetcher(), "https://expired.example/")
        n = len(self.opens)
        self.assertIs(site.fetch(self.fetcher(), "https://expired.example/")[2], False)
        self.assertEqual(len(self.opens), n)  # served from the cache
        with self.assertRaises(ssl_error()):  # a caller without the fallback is not handed the unverified page
            self.fetcher().request("https://expired.example/")

    def test_handshake_failure_is_not_a_broken_cert(self):
        import ssl
        self.error = lambda: ssl.SSLError("UNEXPECTED_EOF_WHILE_READING")
        r = site.crawl(self.fetcher(), "https://flaky.example/")
        self.assertFalse(r["reachable"])
        self.assertNotIn(False, self.opens)  # never retried without verification

    def test_good_cert(self):
        self.verified_fails = 0
        self.assertIs(site.fetch(self.fetcher(), "https://ok.example/")[2], True)
        self.assertEqual(self.opens, [True])


def ssl_error():
    import ssl
    return ssl.SSLError


if __name__ == "__main__":
    unittest.main()
