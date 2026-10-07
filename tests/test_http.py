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

    def test_crawler_refuses_internal_site(self):
        r = site.crawl(http.Fetcher(delay=0), "http://127.0.0.1:9/")
        self.assertFalse(r["reachable"])
        self.assertEqual(r["error"], "UnsafeURL")


if __name__ == "__main__":
    unittest.main()
