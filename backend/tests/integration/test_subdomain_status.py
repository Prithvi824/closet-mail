"""SubdomainStatusChecker: DNS via the Cloudflare API, the KV catch-all flag and inboxes."""

# 1st party imports
from collections.abc import Iterator
from datetime import UTC, datetime

# 3rd party imports
import httpx
import pytest
from fastapi import FastAPI
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

# local imports
from mailalias.api.deps import DbSession, get_status_checker
from mailalias.config import get_settings
from mailalias.mail.types import RetryableError
from mailalias.models import Recipient, SubdomainState, SubdomainStatus, User, UserRole
from mailalias.services.subdomain_status import EXPECTED_MX, SPF_INCLUDE, SubdomainStatusChecker
from mailalias.services.users import UserService
from tests.fakes import FakeDns, FakeKv

pytestmark = pytest.mark.usefixtures("dispatched", "relaxed_rate_limits")
FQDN = "acme.closetcompute.online"
PASSWORD = "correct horse battery"


def _dns(*, mx: set[str] = EXPECTED_MX, spf: bool = True) -> FakeDns:
    """Fake DNS for acme.

    Args:
        mx: MX hostnames present.
        spf: Whether the Cloudflare SPF include is present.
    Returns:
        The fake.
    """
    txt = [f"v=spf1 {SPF_INCLUDE} ~all"] if spf else ["v=spf1 -all"]
    return FakeDns({(FQDN, "MX"): sorted(mx), (FQDN, "TXT"): txt})


async def _acme(session: AsyncSession) -> User:
    """Subdomain acme with a verified default inbox and catch-all on.

    Args:
        session: Test session.
    Returns:
        The user.
    """
    acme = await UserService(session).create_user("acme", "acme@example.com", PASSWORD)
    acme.subdomain_catchall = True
    await session.commit()
    return acme


def _checker(session: AsyncSession, dns: FakeDns, kv: FakeKv) -> SubdomainStatusChecker:
    """Checker wired to fakes.

    Args:
        session: Test session.
        dns: Fake DNS.
        kv: Fake KV.
    Returns:
        The checker.
    """
    return SubdomainStatusChecker(session, dns, kv, get_settings())  # type: ignore[arg-type]


async def test_ready_when_mx_spf_and_flag_are_in_place(session: AsyncSession) -> None:
    """All three Cloudflare MX hosts, the SPF include and the s: flag: READY."""
    acme = await _acme(session)
    status = await _checker(session, _dns(), FakeKv({"s:acme": "C"})).check(acme)
    assert (status.state, status.mx_ok, status.spf_ok, status.kv_ok) == (
        SubdomainState.READY,
        True,
        True,
        True,
    )


async def test_dns_missing_when_an_mx_host_is_absent(session: AsyncSession) -> None:
    """Two of three MX hosts is not enough; a missing flag shows up as kv_ok False."""
    acme = await _acme(session)
    dns = _dns(mx={"route1.mx.cloudflare.net", "route2.mx.cloudflare.net"}, spf=False)
    status = await _checker(session, dns, FakeKv()).check(acme)
    assert (status.state, status.mx_ok, status.spf_ok, status.kv_ok) == (
        SubdomainState.DNS_MISSING,
        False,
        False,
        False,
    )
    assert status.detail is not None and FQDN in status.detail


async def test_no_inbox_without_a_verified_default_inbox(session: AsyncSession) -> None:
    """A subdomain whose only inbox is unverified cannot forward anything."""
    acme = await _acme(session)
    inbox = await session.scalar(select(Recipient).where(Recipient.user_id == acme.id))
    assert inbox is not None
    inbox.verified_at = None
    await session.commit()
    status = await _checker(session, _dns(), FakeKv({"s:acme": "C"})).check(acme)
    assert status.state == SubdomainState.NO_INBOX


async def test_suspended_and_retired_win_over_dns(session: AsyncSession) -> None:
    """Suspension and retirement are reported whatever DNS says."""
    acme = await _acme(session)
    acme.disabled_at = datetime.now(UTC)
    await session.commit()
    checker = _checker(session, _dns(), FakeKv())
    assert (await checker.check(acme)).state == SubdomainState.SUSPENDED
    acme.retired_at = datetime.now(UTC)
    await session.commit()
    assert (await checker.check(acme)).state == SubdomainState.RETIRED


async def test_cloudflare_failure_is_unknown_and_still_saved(session: AsyncSession) -> None:
    """A Cloudflare outage never raises: the state is UNKNOWN and the row is stored."""
    acme = await _acme(session)
    dns = _dns()
    dns.error = RetryableError("cloudflare dns.list unavailable (http 500)")
    status = await _checker(session, dns, FakeKv({"s:acme": "C"})).check(acme)
    assert (status.state, status.detail) == (SubdomainState.UNKNOWN, "Cloudflare lookup failed")
    await session.commit()
    stored = await session.get(SubdomainStatus, acme.id)
    assert stored is not None and stored.state == SubdomainState.UNKNOWN


async def test_check_all_skips_retired_and_updates_the_row(session: AsyncSession) -> None:
    """Every live subdomain is checked; a repeat check updates the same row."""
    acme = await _acme(session)
    gone = await UserService(session).create_user("gone", "gone@example.com", PASSWORD)
    gone.retired_at = datetime.now(UTC)
    await session.commit()
    checker = _checker(session, _dns(), FakeKv({"s:acme": "C"}))
    assert await checker.check_all() == 1
    assert await checker.check_all() == 1
    rows = (await session.scalars(select(SubdomainStatus))).all()
    assert [row.user_id for row in rows] == [acme.id]


@pytest.fixture
def fake_checker(app: FastAPI) -> Iterator[None]:
    """Make the check endpoint use fake DNS and KV.

    Args:
        app: Application.
    Returns:
        An iterator yielding once.
    """

    def _override(db: DbSession) -> SubdomainStatusChecker:
        return _checker(db, _dns(), FakeKv({"s:acme": "C"}))

    app.dependency_overrides[get_status_checker] = _override
    yield


@pytest.mark.usefixtures("fake_checker")
async def test_check_now_endpoint_returns_the_fresh_status(
    client: httpx.AsyncClient, session: AsyncSession
) -> None:
    """POST /operator/subdomains/{label}/check runs the check inline."""
    await _acme(session)
    await UserService(session).create_user("boss", "boss@example.com", PASSWORD, UserRole.ADMIN)
    await session.commit()
    login = await client.post("/api/v1/auth/login", json={"username": "boss", "password": PASSWORD})
    assert login.status_code == 200
    response = await client.post("/api/v1/operator/subdomains/acme/check")
    assert response.status_code == 200
    assert response.json()["status"]["state"] == "ready"
    assert response.json()["status"]["checked_at"] is not None


def test_periodic_check_skips_without_a_zone(migrated_db: str) -> None:
    """Without CF_ZONE_ID (dev and tests) the beat task does nothing and calls no API.

    Args:
        migrated_db: Ensures the test database exists.
    Returns:
        None.
    """
    from mailalias.tasks.subdomains import check_status

    assert get_settings().cf_zone_id == ""
    assert check_status() == 0
