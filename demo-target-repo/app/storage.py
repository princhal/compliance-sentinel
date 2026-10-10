import boto3

from app.config import EXPORT_BUCKET

s3 = boto3.client("s3")


def upload_export(key: str, data: bytes) -> None:
    s3.put_object(Bucket=EXPORT_BUCKET, Key=key, Body=data)


def upload_invoice(key: str, data: bytes) -> None:
    s3.put_object(Bucket=EXPORT_BUCKET, Key=key, Body=data, ServerSideEncryption="aws:kms")
