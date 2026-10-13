"""Inputs to the forward transformer, prepared by the handler (no I/O happens in transforms)."""

# 1st party imports
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Literal

BannerPosition = Literal["top", "bottom", "off"]


@dataclass(frozen=True)
class BannerSettings:
    """Where to place the banner and the signed one-click action links it shows."""

    position: BannerPosition
    block_sender_url: str
    disable_alias_url: str


@dataclass(frozen=True)
class TransformContext:
    """Everything build_forward needs to know about one delivery."""

    alias_address: str
    contact_token_address: str  # "<token>@rp.closetcompute.online"
    sender_display: str  # e.g. "Alice (alice at example.com)"
    banner: BannerSettings
    strip_trackers: bool
    pgp_public_key: str | None
    pgp_protect_subject: bool


@dataclass(frozen=True)
class ReplyContext:
    """Everything build_reply needs: the alias identity and the address mappings."""

    alias_address: str
    to: tuple[tuple[str, str], ...]  # (display name, real address) for the To header
    cc: tuple[tuple[str, str], ...]
    owner_addresses: tuple[str, ...]  # every address of the owner; never allowed out
    token_addresses: Mapping[str, str]  # "<token>@rp..." -> real address (body rewriting)
    action_url_prefix: str  # "https://app.closetcompute.online/a/" (banner links to strip)
