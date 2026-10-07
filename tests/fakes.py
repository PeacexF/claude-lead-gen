"""Offline stand-ins for leadgen.core.http.Fetcher."""
import json
import pathlib

FIXTURES = pathlib.Path(__file__).parent / "fixtures"


def fixture(name: str) -> str:
    return (FIXTURES / name).read_text(encoding="utf-8")


class FakeFetcher:
    """Serves canned responses. routes: {url_or_prefix: str | dict | list | (status, body)}; longest prefix wins."""

    def __init__(self, routes: dict):
        self.routes = routes
        self.calls: list[str] = []

    def request(self, url, data=None, headers=None, **kw):
        self.calls.append(url)
        match = max((k for k in self.routes if url.startswith(k)), key=len, default=None)
        if match is None:
            return 404, url, ""
        v = self.routes[match]
        status, body = v if isinstance(v, tuple) else (200, v)
        if not isinstance(body, str):
            body = json.dumps(body)
        return status, url, body

    def text(self, url, **kw):
        status, _, body = self.request(url, **kw)
        if status >= 400:
            raise RuntimeError(f"HTTP {status}")
        return body

    def json(self, url, **kw):
        return json.loads(self.text(url, **kw))
