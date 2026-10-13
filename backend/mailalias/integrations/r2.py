"""Cloudflare R2 (S3-compatible) object storage access via boto3 in worker threads."""

# 1st party imports
import asyncio
from typing import Any, Protocol

# 3rd party imports
import boto3
from botocore.config import Config
from botocore.exceptions import BotoCoreError, ClientError

# local imports
from mailalias.config import Settings
from mailalias.mail.types import RetryableError

MISSING_CODES = {"NoSuchKey", "404"}


class R2ObjectMissing(Exception):
    """The object does not exist (e.g. removed by the lifecycle rule)."""


class ObjectStore(Protocol):
    """Byte storage by key (R2 in production, a dict in tests)."""

    async def get(self, key: str) -> bytes:
        """Return the object; raises R2ObjectMissing."""
        ...

    async def put(self, key: str, data: bytes) -> None:
        """Store the object."""
        ...

    async def delete(self, key: str) -> None:
        """Delete the object (missing is fine)."""
        ...


class R2Storage:
    """Minimal get/put/delete on one bucket. Blocking boto3 calls run in threads."""

    def __init__(self, settings: Settings, client: Any | None = None) -> None:
        """Build the storage wrapper.

        Args:
            settings: R2 endpoint, credentials and bucket.
            client: Optional pre-built S3 client (tests).
        Returns:
            None.
        """
        self.bucket = settings.r2_bucket
        self._client = client or boto3.client(
            "s3",
            endpoint_url=settings.r2_endpoint,
            region_name="auto",
            aws_access_key_id=settings.r2_access_key_id.get_secret_value(),
            aws_secret_access_key=settings.r2_secret_access_key.get_secret_value(),
            config=Config(retries={"max_attempts": 3, "mode": "standard"}),
        )

    async def get(self, key: str) -> bytes:
        """Download an object.

        Args:
            key: Object key.
        Returns:
            The object bytes. Raises R2ObjectMissing or RetryableError.
        """

        def _get() -> bytes:
            body: bytes = self._client.get_object(Bucket=self.bucket, Key=key)["Body"].read()
            return body

        return await self._call("get", _get)

    async def put(self, key: str, data: bytes) -> None:
        """Upload an object, replacing any existing one.

        Args:
            key: Object key.
            data: Object bytes.
        Returns:
            None.
        """
        await self._call(
            "put", lambda: self._client.put_object(Bucket=self.bucket, Key=key, Body=data)
        )

    async def delete(self, key: str) -> None:
        """Delete an object; deleting a missing object is not an error.

        Args:
            key: Object key.
        Returns:
            None.
        """
        await self._call("delete", lambda: self._client.delete_object(Bucket=self.bucket, Key=key))

    async def _call[T](self, op: str, func: Any) -> T:
        """Run a boto3 call in a thread and map its errors.

        Args:
            op: Operation name for error messages.
            func: Zero-argument callable doing the boto3 call.
        Returns:
            The callable's result.
        """
        try:
            result: T = await asyncio.to_thread(func)
        except ClientError as exc:
            code = str(exc.response.get("Error", {}).get("Code", ""))
            if code in MISSING_CODES:
                raise R2ObjectMissing(op) from exc
            raise RetryableError(f"r2 {op} failed ({code or 'client error'})") from exc
        except BotoCoreError as exc:
            raise RetryableError(f"r2 {op} failed ({type(exc).__name__})") from exc
        return result
