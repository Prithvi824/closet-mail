"""ORM models. Importing this package registers every table on `Base.metadata`."""

# local imports
from mailalias.models.alias import Alias, AliasKind, AliasState, alias_recipients
from mailalias.models.api_token import ApiToken
from mailalias.models.audit import AuditLog
from mailalias.models.base import Base
from mailalias.models.blocklist import BlockKind, BlocklistEntry
from mailalias.models.contact import Contact
from mailalias.models.failed_delivery import FailedDelivery, FailureKind
from mailalias.models.invite import Invite
from mailalias.models.label import Label, alias_labels
from mailalias.models.mail_log import MailLog
from mailalias.models.quarantine import QuarantineItem
from mailalias.models.recipient import Recipient
from mailalias.models.usage import UsageDaily
from mailalias.models.user import AliasFormat, BannerPosition, User, UserRole
from mailalias.models.webauthn import WebAuthnCredential

__all__ = [
    "Alias",
    "AliasFormat",
    "AliasKind",
    "AliasState",
    "ApiToken",
    "AuditLog",
    "BannerPosition",
    "Base",
    "BlockKind",
    "BlocklistEntry",
    "Contact",
    "FailedDelivery",
    "FailureKind",
    "Invite",
    "Label",
    "MailLog",
    "QuarantineItem",
    "Recipient",
    "UsageDaily",
    "User",
    "UserRole",
    "WebAuthnCredential",
    "alias_labels",
    "alias_recipients",
]
