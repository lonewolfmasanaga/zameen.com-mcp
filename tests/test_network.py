"""Offline tests for network hardening: retries, backoff, politeness, auth.

No test in this file touches the network. HTTP is faked at two seams:

* :class:`ScriptedTransport` patches ``urllib3.connectionpool.HTTPConnectionPool._make_request``
  so the REAL requests -> HTTPAdapter -> urllib3 Retry machinery runs against
  canned responses (genuine retry/backoff/Retry-After behaviour, zero sockets).
* A plain recording stand-in replaces the authenticated session where the
  auth path itself is under test.

Time is faked everywhere (``time.monotonic`` / ``time.sleep``), so neither
politeness waits nor retry backoff ever actually sleep.
"""

from __future__ import annotations

import io
import threading

import pytest
import requests
from requests.exceptions import HTTPError
from urllib3.connectionpool import HTTPConnectionPool
from urllib3.response import HTTPResponse

from zameen_mcp import client


# ------------------------------------------------------------- fixtures ---

@pytest.fixture()
def net_state():
    """Snapshot/restore every module-level network knob around each test."""
    saved = (
        client._HTTP_SESSION,
        client._TIMEOUT,
        client._MIN_DELAY,
        client._LAST_FETCH_MONO,
    )
    client._LAST_FETCH_MONO = None  # each test starts "never fetched"
    yield
    (
        client._HTTP_SESSION,
        client._TIMEOUT,
        client._MIN_DELAY,
        client._LAST_FETCH_MONO,
    ) = saved


class FakeClock:
    """Deterministic monotonic clock; ``sleep`` just advances it."""

    def __init__(self, start: float = 1000.0):
        self.now = start
        self.sleeps: list[float] = []

    def monotonic(self) -> float:
        return self.now

    def sleep(self, seconds: float) -> None:
        assert seconds >= 0, f"negative sleep {seconds}"
        self.sleeps.append(seconds)
        self.now += seconds

    def install(self, monkeypatch: pytest.MonkeyPatch) -> "FakeClock":
        import time as _time

        monkeypatch.setattr(_time, "monotonic", self.monotonic)
        monkeypatch.setattr(_time, "sleep", self.sleep)
        return self


@pytest.fixture()
def clock(monkeypatch: pytest.MonkeyPatch) -> FakeClock:
    return FakeClock().install(monkeypatch)


class ScriptedTransport:
    """Replay a script of ``(status[, headers])`` tuples or Exceptions.

    Patches ``HTTPConnectionPool._make_request`` so canned urllib3 responses
    flow through requests' genuine adapter/retry stack. When the script runs
    dry, the final entry repeats forever (handy for exhaustion tests).
    """

    def __init__(self, monkeypatch: pytest.MonkeyPatch, script: list):
        self.script = list(script)
        self.calls: list[tuple[str, str]] = []

        def fake_make_request(_pool, _conn, method, url, **_kwargs):
            self.calls.append((method, url))
            item = self.script.pop(0) if len(self.script) > 1 else self.script[0]
            if isinstance(item, Exception):
                raise item
            status, headers = (item if isinstance(item, tuple) else (item, {}))
            return HTTPResponse(
                # BytesIO so urllib3's is_fp_closed() can stream/read it.
                body=io.BytesIO(b"<html>ok-page</html>"),
                headers={"Content-Type": "text/html; charset=utf-8", **headers},
                status=status,
                preload_content=False,
                decode_content=False,
            )

        monkeypatch.setattr(HTTPConnectionPool, "_make_request", fake_make_request)


@pytest.fixture(autouse=True)
def _hardened_session(net_state):
    """Give every test a fresh hardened session (explicit configure_http)."""
    client.configure_http()


# ------------------------------------------------------------ configure_http --

class TestConfigureHttp:
    def test_defaults_build_hardened_session(self):
        session = client.configure_http()

        assert session is client._HTTP_SESSION
        retry = session.get_adapter("https://www.zameen.com").max_retries
        assert retry.total == 2
        assert retry.backoff_factor == pytest.approx(1.0)
        assert {429, 500, 502, 503, 504} <= set(retry.status_forcelist)
        assert retry.respect_retry_after_header is True
        assert retry.raise_on_status is False

    def test_post_excluded_from_retries_get_included(self):
        retry = client.configure_http().get_adapter("https://x").max_retries

        assert "GET" in retry.allowed_methods
        assert "POST" not in retry.allowed_methods

    def test_configured_timeout_reaches_the_request(self, clock, monkeypatch):
        ScriptedTransport(monkeypatch, [(200, {})])
        client.configure_http(timeout=12)
        sent_kwargs: list[dict] = []
        original_get = client._HTTP_SESSION.get

        def recording_get(url, **kwargs):
            sent_kwargs.append(kwargs)
            return original_get(url, **kwargs)

        monkeypatch.setattr(client._HTTP_SESSION, "get", recording_get)

        client.fetch("https://www.zameen.com/Homes/Islamabad-3.html")

        (kwargs,) = sent_kwargs
        assert kwargs["timeout"] == pytest.approx(12.0)

    def test_lazy_first_fetch_builds_default_session(self, clock, monkeypatch):
        client._HTTP_SESSION = None  # simulate never-configured module state
        ScriptedTransport(monkeypatch, [(200, {})])

        client.fetch("https://www.zameen.com/x")

        assert client._HTTP_SESSION is not None
        assert client._TIMEOUT == pytest.approx(45.0)


# --------------------------------------------------------- retries/backoff --

class TestRetries:
    def test_retry_on_500_then_200_succeeds(self, clock, monkeypatch):
        transport = ScriptedTransport(monkeypatch, [(500, {}), (200, {})])

        text = client.fetch("https://www.zameen.com/Homes/Lahore-1.html")

        assert "<html>ok-page</html>" == text
        assert len(transport.calls) == 2  # initial attempt + 1 retry
        assert all(method == "GET" for method, _url in transport.calls)
        # urllib3 >= 2 semantics: zero backoff before the FIRST retry
        # (get_backoff_time returns 0 while history has one entry), so no
        # sleep is recorded here; Retry-After headers would still be honoured
        # (see test_retry_after_header_wins_over_backoff).
        assert clock.sleeps == []

    def test_second_failure_backs_off_exponentially(self, clock, monkeypatch):
        transport = ScriptedTransport(monkeypatch, [(500, {}), (500, {}), (200, {})])

        assert "<html>ok-page</html>" == client.fetch(
            "https://www.zameen.com/x"
        )
        assert len(transport.calls) == 3
        # Second retry waits backoff_factor * 2**(n-1) with n=2 -> 2 * 1.0.
        assert clock.sleeps == [pytest.approx(2.0)]

    def test_exhausted_retries_raise_httperror_like_before(
        self, clock, monkeypatch
    ):
        transport = ScriptedTransport(monkeypatch, [(500, {})])  # always 500

        with pytest.raises(HTTPError):
            client.fetch("https://www.zameen.com/Homes/Lahore-1.html")

        assert len(transport.calls) == 3  # 1 initial + max_retries(2) retries
        # First retry: 0s (urllib3 skips zero backoff); second: factor * 2**1.
        assert clock.sleeps == [pytest.approx(2.0)]

    def test_rate_limit_429_is_retried(self, clock, monkeypatch):
        transport = ScriptedTransport(monkeypatch, [(429, {}), (200, {})])

        assert "<html>ok-page</html>" == client.fetch(
            "https://www.zameen.com/Rentals/Karachi-2.html"
        )
        assert len(transport.calls) == 2

    def test_retry_after_header_wins_over_backoff(self, clock, monkeypatch):
        ScriptedTransport(monkeypatch, [(429, {"Retry-After": "3"}), (200, {})])

        client.fetch("https://www.zameen.com/x")

        assert clock.sleeps == [pytest.approx(3.0)]

    def test_client_level_http_error_not_retried(self, clock, monkeypatch):
        transport = ScriptedTransport(monkeypatch, [(404, {}), (404, {})])

        with pytest.raises(HTTPError):
            client.fetch("https://www.zameen.com/nope")

        assert len(transport.calls) == 1  # 404 is not in the forcelist

    def test_post_never_retried_even_on_forcelist_status(self, clock, monkeypatch):
        transport = ScriptedTransport(monkeypatch, [(500, {}), (500, {})])
        session = client._HTTP_SESSION

        response = session.post("https://www.zameen.com/api", data={})

        # POST is excluded from allowed_methods: despite two 500s scripted,
        # urllib3 makes exactly one attempt and hands back the raw response
        # (raise_on_status=False keeps the final-response contract; callers
        # see HTTPError only via raise_for_status in _get).
        assert response.status_code == 500
        assert len(transport.calls) == 1


# ------------------------------------------------------------- politeness --

class TestPoliteness:
    def test_second_consecutive_zameen_fetch_is_delayed(
        self, clock, monkeypatch
    ):
        ScriptedTransport(monkeypatch, [(200, {})])
        assert client.politeness_delay() == pytest.approx(1.5)  # contract default

        client.fetch("https://www.zameen.com/Homes/Islamabad-3.html")
        client.fetch("https://www.zameen.com/Homes/Islamabad-3-2.html")

        assert clock.sleeps == [pytest.approx(1.5)]  # only the 2nd fetch waited

    @pytest.mark.parametrize("url", [
        "https://zameen.com/",
        "https://www.zameen.com/Homes/Lahore-1.html",
        "https://images.zameen.com/photos/x.jpg",
    ])
    def test_delay_covers_zameen_hosts_only_for_zameen_urls(
        self, url, clock, monkeypatch
    ):
        ScriptedTransport(monkeypatch, [(200, {})])

        client.fetch(url)
        client.fetch(url)

        assert len(clock.sleeps) == 1

    def test_non_zameen_urls_are_never_throttled(self, clock, monkeypatch):
        ScriptedTransport(monkeypatch, [(200, {})])

        client.fetch("https://example.com/a")
        client.fetch("https://evilzameen.com/a")  # suffix trick must not count
        client.fetch("https://example.com/b")

        assert clock.sleeps == []
        assert client._LAST_FETCH_MONO is None  # nothing recorded

    def test_elapsed_time_reduces_wait_proportionally(self, clock, monkeypatch):
        ScriptedTransport(monkeypatch, [(200, {})])

        client.fetch("https://www.zameen.com/a")
        clock.now += 0.9  # pretend 0.9s of real work happened meanwhile
        client.fetch("https://www.zameen.com/b")

        assert clock.sleeps == [pytest.approx(0.6)]

    def test_set_politeness_roundtrip_and_validation(self):
        try:
            client.set_politeness(0.25)
            assert client.politeness_delay() == pytest.approx(0.25)
            with pytest.raises(ValueError):
                client.set_politeness(-0.1)
        finally:
            client.set_politeness(1.5)
        assert client.politeness_delay() == pytest.approx(1.5)

    def test_zero_disables_waiting(self, clock, monkeypatch):
        ScriptedTransport(monkeypatch, [(200, {})])
        client.set_politeness(0)

        client.fetch("https://www.zameen.com/a")
        client.fetch("https://www.zameen.com/b")

        assert clock.sleeps == []

    def test_thread_safe_spacing_between_workers(self, clock, monkeypatch):
        """Two concurrent workers produce exactly one polite wait overall."""
        ScriptedTransport(monkeypatch, [(200, {}), (200, {})])
        barrier = threading.Barrier(2)
        results: dict[int, object] = {}

        def worker(idx: int, url: str) -> None:
            barrier.wait(timeout=5)
            try:
                results[idx] = client.fetch(url)
            except Exception as exc:  # noqa: BLE001 - surfaced below
                results[idx] = exc

        threads = [
            threading.Thread(target=worker, args=(i, u))
            for i, u in enumerate(
                (
                    "https://www.zameen.com/Homes/Lahore-1.html",
                    "https://www.zameen.com/Homes/Lahore-1-2.html",
                )
            )
        ]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=10)

        # Both workers got their page; the polite lock serialised them into
        # exactly one minimum-delay wait (a second worker always sleeps until
        # >= _MIN_DELAY after the previous zameen dispatch).
        for idx in range(2):
            assert results[idx] == "<html>ok-page</html>", results[idx]
        assert clock.sleeps == [pytest.approx(1.5)]


# ------------------------------------------------------------- auth session --

class RecordingAuthSession:
    """Stand-in authenticated session: records calls, serves canned HTML."""

    def __init__(self, marker: bytes = b"auth-ok"):
        self.marker = marker
        self.calls: list[tuple[str, dict]] = []

    def get(self, url: str, **kwargs):
        self.calls.append((url, kwargs))
        response = requests.Response()
        response.status_code = 200
        response._content = self.marker
        response.url = url
        return response


class TestAuthSessionIntegrity:
    def test_auth_session_still_used_when_set(self, clock):
        auth = RecordingAuthSession(b"logged-in page")
        client.set_auth_session(auth)

        text = client.fetch("https://www.zameen.com/Homes/Islamabad-3.html")

        assert text == "logged-in page"
        assert client.auth_enabled() is True
        (url, kwargs), = auth.calls  # exactly one call, onto the auth session
        assert url == "https://www.zameen.com/Homes/Islamabad-3.html"
        assert kwargs["timeout"] == pytest.approx(45.0)  # default preserved
        assert kwargs["allow_redirects"] is True
        assert kwargs["headers"]["User-Agent"].startswith("Mozilla/5.0")
        assert clock.sleeps == []  # first fetch: no politeness wait yet

    def test_clearing_auth_falls_back_to_hardened_session(
        self, clock, monkeypatch
    ):
        auth = RecordingAuthSession(b"auth-ok")
        transport = ScriptedTransport(monkeypatch, [(200, {})])
        client.set_auth_session(auth)

        assert "auth-ok" == client.fetch("https://www.zameen.com/a")
        client.set_auth_session(None)

        text = client.fetch("https://www.zameen.com/b")

        assert "<html>ok-page</html>" == text  # served by the module session
        assert len(auth.calls) == 1  # the second fetch never touched auth
        assert len(transport.calls) == 1
