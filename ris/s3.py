from contextlib import asynccontextmanager
from pathlib import Path
from typing import TYPE_CHECKING, AsyncGenerator, BinaryIO

from aioboto3 import Session
from botocore.exceptions import ClientError

if TYPE_CHECKING:
    from types_aiobotocore_s3.client import S3Client


class S3Manager:
    def __init__(self, access_key: str, secret_key: str, endpoint_url: str, default_bucket: str = "") -> None:
        self.session = Session(
            aws_access_key_id=access_key,
            aws_secret_access_key=secret_key,
            region_name="ams1",
        )
        self.endpoint_url = endpoint_url
        self.default_bucket = default_bucket

    @asynccontextmanager
    async def client(self) -> "AsyncGenerator[S3Client, None]":
        async with self.session.client(service_name="s3", endpoint_url=self.endpoint_url) as s3_client:
            yield s3_client

    async def upload_file(
        self, file_content: BinaryIO, file_path: str | Path, bucket: str = "", public: bool = True
    ) -> None:
        file_path = str(file_path)
        bucket = bucket or self.default_bucket
        if not bucket:
            raise ValueError("No bucket specified")

        async with self.client() as s3_client:
            await s3_client.upload_fileobj(
                file_content,
                bucket,
                file_path,
                ExtraArgs={"ACL": "public-read"} if public else {},
            )

    async def file_exists(self, file_path: str | Path, bucket: str = "") -> bool:
        file_path = str(file_path)
        bucket = bucket or self.default_bucket
        if not bucket:
            raise ValueError("No bucket specified")

        async with self.client() as s3_client:
            try:
                await s3_client.head_object(Bucket=bucket, Key=file_path)
                return True
            except ClientError:
                return False
