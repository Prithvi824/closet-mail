"""Tests for the Rspamd client and the Cloudflare client-info parser that feeds it."""

# 3rd party imports
import httpx
import pytest
import respx

# local imports
from mailalias.config import get_settings
from mailalias.integrations import rspamd
from mailalias.integrations.rspamd import RspamdClient, SpamCheckUnavailable
from mailalias.mail.auth_results import client_info
from tests.eml import load_eml

URL = "http://rspamd.test/checkv2"


def _client() -> RspamdClient:
    """Client pointed at the mocked URL.

    Returns:
        The client.
    """
    settings = get_settings().model_copy(update={"rspamd_url": "http://rspamd.test"})
    return RspamdClient(settings, httpx.AsyncClient())


def test_client_info_reads_only_cloudflares_top_received_header() -> None:
    """IP and HELO come from Cloudflare's own Received line; anything else yields None."""
    msg = load_eml("real_inbound_gmail.eml")
    assert client_info(msg) == ("209.85.220.41", "mail-sor-f41.google.com")
    assert client_info(load_eml("fwd_alternative.eml")) == (None, None)


@respx.mock
async def test_check_sends_smtp_details_and_parses_score(monkeypatch: pytest.MonkeyPatch) -> None:
    """Envelope, IP, HELO and the PTR name are passed as headers; score and symbols parsed."""

    async def fake_ptr(ip: str) -> str:
        """Pretend PTR lookup."""
        return "mail-sor-f41.google.com"

    monkeypatch.setattr(rspamd, "reverse_dns", fake_ptr)
    route = respx.post(URL).respond(json={"score": 7.25, "symbols": {"B": {}, "A": {}}})
    verdict = await _client().check(b"raw", "", "x@closetcompute.online", "1.2.3.4", "helo.x")
    sent = route.calls.last.request.headers
    assert (sent["From"], sent["Rcpt"], sent["IP"]) == ("<>", "x@closetcompute.online", "1.2.3.4")
    assert (sent["Helo"], sent["Hostname"]) == ("helo.x", "mail-sor-f41.google.com")
    assert verdict.score == 7.25 and verdict.symbols == ("A", "B")


@respx.mock
@pytest.mark.parametrize(
    "response",
    [httpx.Response(500), httpx.Response(200, text="not json"), httpx.ConnectError("down")],
)
async def test_failures_raise_unavailable(response: httpx.Response | Exception) -> None:
    """HTTP errors, bad bodies and connection failures all mean "unavailable"."""
    route = respx.post(URL)
    if isinstance(response, Exception):
        route.mock(side_effect=response)
    else:
        route.mock(return_value=response)
    with pytest.raises(SpamCheckUnavailable):
        await _client().check(b"raw", "a@b.c", "x@closetcompute.online", None, None)
