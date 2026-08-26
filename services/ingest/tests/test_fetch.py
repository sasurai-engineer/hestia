"""The HTTP shim against a local socket — never the live provider."""

from __future__ import annotations

import http.server
import socket
import threading
import typing

import pytest
from hestia_ingest.fetch import MAX_RESPONSE_BYTES, FetchError, ProviderRequest, fetch_json


class Handler(http.server.BaseHTTPRequestHandler):
    routes: typing.ClassVar[dict[str, tuple[int, bytes]]] = {}

    def do_GET(self) -> None:
        status, body = self.routes.get(self.path.split("?")[0], (404, b"{}"))
        self.send_response(status)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *args: object) -> None:  # silence
        del args


@pytest.fixture(scope="module")
def server() -> str:
    Handler.routes = {
        "/ok": (200, b'{"hello": "world"}'),
        "/not-json": (200, b"<html>nope</html>"),
        "/array": (200, b"[1, 2]"),
        "/huge": (200, b'{"pad": "' + b"x" * (MAX_RESPONSE_BYTES + 10) + b'"}'),
        "/missing": (404, b"{}"),
    }
    httpd = http.server.HTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    yield f"http://127.0.0.1:{httpd.server_port}"
    httpd.shutdown()


def request(base: str, path: str) -> ProviderRequest:
    return ProviderRequest(provider="test", url=f"{base}{path}")


def test_fetches_and_parses(server: str) -> None:
    result = fetch_json(request(server, "/ok"))
    assert result.payload == {"hello": "world"}
    assert result.raw_text == '{"hello": "world"}'


def test_full_url_encodes_params(server: str) -> None:
    prepared = ProviderRequest(provider="t", url=f"{server}/ok", params={"a b": "c&d"})
    assert prepared.full_url.endswith("/ok?a+b=c%26d")
    assert fetch_json(prepared).payload == {"hello": "world"}


def test_http_error_is_typed(server: str) -> None:
    with pytest.raises(FetchError, match="HTTP 404"):
        fetch_json(request(server, "/missing"))


def test_non_json_is_typed(server: str) -> None:
    with pytest.raises(FetchError, match="not JSON"):
        fetch_json(request(server, "/not-json"))


def test_non_object_json_is_refused(server: str) -> None:
    with pytest.raises(FetchError, match="not an object"):
        fetch_json(request(server, "/array"))


def test_size_bound_is_enforced(server: str) -> None:
    with pytest.raises(FetchError, match="size bound"):
        fetch_json(request(server, "/huge"))


def test_refuses_plain_http_to_the_world() -> None:
    with pytest.raises(FetchError, match="refusing non-https"):
        fetch_json(ProviderRequest(provider="t", url="http://example.com/x"))


def test_transport_failure_is_typed() -> None:
    # A socket that accepts and never speaks: connect succeeds, read times out.
    listener = socket.socket()
    listener.bind(("127.0.0.1", 0))
    listener.listen(1)
    port = listener.getsockname()[1]
    try:
        with pytest.raises(FetchError, match="transport failure"):
            fetch_json(
                ProviderRequest(provider="t", url=f"http://127.0.0.1:{port}/x"),
                timeout_seconds=0.2,
            )
    finally:
        listener.close()
