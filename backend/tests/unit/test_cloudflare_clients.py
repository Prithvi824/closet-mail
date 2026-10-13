"""Tests for the Cloudflare API, Queue inbox, KV and R2 clients (HTTP mocked with respx)."""

# 1st party imports
import json
from typing import Any

# 3rd party imports
import httpx
import pytest
import respx
from botocore.exceptions import ClientError

# local imports
from mailalias.config import get_settings
from mailalias.integrations.cloudflare_api import CloudflareApi, CloudflareApiError
from mailalias.integrations.cloudflare_kv import CloudflareKv
from mailalias.integrations.cloudflare_queue import CloudflareQueueInbox, MalformedJob, parse_job
from mailalias.integrations.r2 import R2ObjectMissing, R2Storage
from mailalias.mail.types import RetryableError

BASE = "https://api.cloudflare.com/client/v4/accounts/test-account"
QUEUE = f"{BASE}/queues/test-queue/messages"
KV = f"{BASE}/storage/kv/namespaces/test-kv"


async def _no_sleep(_seconds: float) -> None:
    """Skip backoff waits in tests.

    Args:
        _seconds: Ignored.
    Returns:
        None.
    """


def _api() -> CloudflareApi:
    """API client with instant backoff.

    Returns:
        A CloudflareApi using test settings.
    """
    return CloudflareApi(get_settings(), sleep=_no_sleep)


def _job_message(lease: str, **overrides: Any) -> dict[str, Any]:
    """Build a pull-API message as observed in the T6 spike.

    Args:
        lease: Lease id.
        overrides: Fields to change in the job body.
    Returns:
        The message dict with a JSON-string body.
    """
    job = {
        "v": 1,
        "r2Key": "in/2026/10/11/abc.eml",
        "mailFrom": "Sender@Example.com",
        "rcptTo": "spike@closetcompute.online",
        "rawSize": 7065,
        "receivedAt": "2026-10-11T10:38:30.344Z",
        **overrides,
    }
    return {
        "id": f"id-{lease}",
        "timestamp_ms": 1,
        "attempts": 2,
        "lease_id": lease,
        "metadata": {"CF-Content-Type": "json"},
        "body": json.dumps(job),
    }


def _ok(result: Any, **extra: Any) -> dict[str, Any]:
    """Cloudflare success envelope.

    Args:
        result: The result payload.
        extra: Additional top-level keys.
    Returns:
        The envelope dict.
    """
    return {"success": True, "errors": [], "messages": [], "result": result, **extra}


class _FakeStorage:
    """Stands in for R2Storage in queue tests."""

    def __init__(self) -> None:
        """Start with no deletions.

        Returns:
            None.
        """
        self.deleted: list[str] = []

    async def get(self, key: str) -> bytes:
        """Return fixed bytes.

        Args:
            key: Ignored.
        Returns:
            Raw bytes.
        """
        return b"raw"

    async def delete(self, key: str) -> None:
        """Record the deletion.

        Args:
            key: Deleted key.
        Returns:
            None.
        """
        self.deleted.append(key)


def _inbox() -> CloudflareQueueInbox:
    """Queue inbox with fake storage.

    Returns:
        A CloudflareQueueInbox.
    """
    return CloudflareQueueInbox(_api(), _FakeStorage(), "test-queue")  # type: ignore[arg-type]


def test_parse_job_maps_fields_and_lowercases() -> None:
    """A valid job becomes an envelope with lowercased addresses and a UTC timestamp.

    Returns:
        None.
    """
    env = parse_job(_job_message("L1"))
    assert env.lease_id == "L1" and env.attempts == 2
    assert env.mail_from == "sender@example.com"
    assert env.raw_size == 7065
    assert env.received_at.utcoffset() is not None


@pytest.mark.parametrize(
    "message",
    [
        _job_message("L", v=2),
        {"lease_id": "L", "body": "not json"},
        {"lease_id": "L", "body": json.dumps({"v": 1})},
    ],
)
def test_parse_job_rejects_malformed(message: dict[str, Any]) -> None:
    """Wrong version, invalid JSON and missing fields raise MalformedJob.

    Args:
        message: A bad pull message.
    Returns:
        None.
    """
    with pytest.raises(MalformedJob):
        parse_job(message)


@respx.mock
async def test_pull_parses_and_acks_malformed() -> None:
    """Good jobs are returned; malformed ones are acked and skipped.

    Returns:
        None.
    """
    pull = respx.post(f"{QUEUE}/pull").respond(
        json=_ok(
            {
                "message_backlog_count": 0,
                "messages": [_job_message("good"), _job_message("bad", v=9)],
            }
        )
    )
    ack = respx.post(f"{QUEUE}/ack").respond(json=_ok({"ackCount": 1}))

    envelopes = await _inbox().pull(10, 120_000)

    assert [e.lease_id for e in envelopes] == ["good"]
    assert json.loads(pull.calls[0].request.content) == {
        "batch_size": 10,
        "visibility_timeout_ms": 120_000,
    }
    assert json.loads(ack.calls[0].request.content) == {
        "acks": [{"lease_id": "bad"}],
        "retries": [],
    }


@respx.mock
async def test_pull_handles_null_result() -> None:
    """An empty queue may return result=null.

    Returns:
        None.
    """
    respx.post(f"{QUEUE}/pull").respond(json=_ok(None))
    assert await _inbox().pull(10, 1000) == []


@respx.mock
async def test_ack_and_retry_payloads() -> None:
    """ack and retry send the documented request bodies.

    Returns:
        None.
    """
    route = respx.post(f"{QUEUE}/ack").respond(json=_ok({}))
    inbox = _inbox()
    await inbox.ack(["a", "b"])
    await inbox.retry(["c"], 60)
    await inbox.ack([])  # no-op, no request
    bodies = [json.loads(call.request.content) for call in route.calls]
    assert bodies == [
        {"acks": [{"lease_id": "a"}, {"lease_id": "b"}], "retries": []},
        {"acks": [], "retries": [{"lease_id": "c", "delay_seconds": 60}]},
    ]


@respx.mock
async def test_429_is_retried_then_succeeds() -> None:
    """A 429 followed by success returns normally after one retry.

    Returns:
        None.
    """
    route = respx.post(f"{QUEUE}/pull").mock(
        side_effect=[httpx.Response(429), httpx.Response(200, json=_ok({"messages": []}))]
    )
    assert await _inbox().pull(1, 1000) == []
    assert route.call_count == 2


@respx.mock
async def test_persistent_5xx_raises_retryable_without_secrets() -> None:
    """Exhausted retries raise RetryableError whose message holds no token or URL.

    Returns:
        None.
    """
    route = respx.post(f"{QUEUE}/pull").respond(503)
    with pytest.raises(RetryableError) as info:
        await _inbox().pull(1, 1000)
    assert route.call_count == 3
    assert "test-queue" not in str(info.value) and "Bearer" not in str(info.value)


@respx.mock
async def test_4xx_is_permanent() -> None:
    """A 403 is not retried and raises CloudflareApiError with the error codes.

    Returns:
        None.
    """
    route = respx.post(f"{QUEUE}/pull").respond(
        403, json={"success": False, "errors": [{"code": 10000}]}
    )
    with pytest.raises(CloudflareApiError) as info:
        await _inbox().pull(1, 1000)
    assert route.call_count == 1 and info.value.codes == [10000]


@respx.mock
async def test_kv_put_escapes_key_and_sends_value() -> None:
    """Keys with ':' and '@' are percent-encoded; the value is the raw body.

    Returns:
        None.
    """
    route = respx.put(f"{KV}/values/a%3Aspike%40closetcompute.online").respond(json=_ok(None))
    await CloudflareKv(_api(), "test-kv").put("a:spike@closetcompute.online", "A")
    assert route.calls[0].request.content == b"A"


@respx.mock
async def test_kv_list_follows_cursor() -> None:
    """list_keys yields every page until the cursor is empty.

    Returns:
        None.
    """
    route = respx.get(f"{KV}/keys").mock(
        side_effect=[
            httpx.Response(
                200, json=_ok([{"name": "a:1"}, {"name": "a:2"}], result_info={"cursor": "c2"})
            ),
            httpx.Response(200, json=_ok([{"name": "a:3"}], result_info={"cursor": ""})),
        ]
    )
    keys = [key async for key in CloudflareKv(_api(), "test-kv").list_keys("a:")]
    assert keys == ["a:1", "a:2", "a:3"]
    assert route.calls[1].request.url.params["cursor"] == "c2"
    assert route.calls[0].request.url.params["prefix"] == "a:"


@respx.mock
async def test_kv_bulk_put_and_delete() -> None:
    """Bulk operations send key/value pairs and key lists.

    Returns:
        None.
    """
    put = respx.put(f"{KV}/bulk").respond(json=_ok(None))
    delete = respx.post(f"{KV}/bulk/delete").respond(json=_ok(None))
    kv = CloudflareKv(_api(), "test-kv")
    await kv.bulk_put({"r:tok": "V"})
    await kv.bulk_delete(["r:old"])
    assert json.loads(put.calls[0].request.content) == [{"key": "r:tok", "value": "V"}]
    assert json.loads(delete.calls[0].request.content) == ["r:old"]


class _FakeS3:
    """boto3-like client raising a configured error code."""

    def __init__(self, code: str) -> None:
        """Remember the error code to raise.

        Args:
            code: S3 error code.
        Returns:
            None.
        """
        self.code = code

    def get_object(self, **_kwargs: Any) -> Any:
        """Raise the configured ClientError.

        Args:
            _kwargs: Ignored.
        Returns:
            Never returns.
        """
        raise ClientError({"Error": {"Code": self.code}}, "GetObject")


@pytest.mark.parametrize(
    ("code", "error"), [("NoSuchKey", R2ObjectMissing), ("InternalError", RetryableError)]
)
async def test_r2_error_mapping(code: str, error: type[Exception]) -> None:
    """Missing objects are permanent; other S3 errors are retryable.

    Args:
        code: S3 error code to simulate.
        error: Expected exception type.
    Returns:
        None.
    """
    with pytest.raises(error):
        await R2Storage(get_settings(), client=_FakeS3(code)).get("in/x.eml")
