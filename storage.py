import boto3
from botocore.client import Config

from config import settings


s3 = boto3.client(
    "s3",
    endpoint_url=settings.b2_endpoint,
    aws_access_key_id=settings.b2_key_id,
    aws_secret_access_key=settings.b2_application_key,
    region_name=settings.b2_region,
    config=Config(signature_version="s3v4"),
)


def create_multipart(key: str, mime: str) -> str:
    return s3.create_multipart_upload(
        Bucket=settings.b2_bucket, Key=key, ContentType=mime, Metadata={"nobar": "1"}
    )["UploadId"]


def presigned_part(key: str, upload_id: str, part_number: int) -> str:
    return s3.generate_presigned_url(
        "upload_part",
        Params={"Bucket": settings.b2_bucket, "Key": key, "UploadId": upload_id, "PartNumber": part_number},
        ExpiresIn=3600,
    )


def complete_multipart(key: str, upload_id: str, parts: list[dict]) -> dict:
    return s3.complete_multipart_upload(
        Bucket=settings.b2_bucket,
        Key=key,
        UploadId=upload_id,
        MultipartUpload={"Parts": sorted(parts, key=lambda x: x["PartNumber"])},
    )


def abort_multipart(key: str, upload_id: str) -> None:
    s3.abort_multipart_upload(Bucket=settings.b2_bucket, Key=key, UploadId=upload_id)


def presigned_get(key: str) -> str:
    return s3.generate_presigned_url(
        "get_object", Params={"Bucket": settings.b2_bucket, "Key": key}, ExpiresIn=3600
    )


def head(key: str) -> dict:
    return s3.head_object(Bucket=settings.b2_bucket, Key=key)


def delete_object(key: str) -> None:
    s3.delete_object(Bucket=settings.b2_bucket, Key=key)
