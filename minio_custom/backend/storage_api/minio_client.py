import boto3
from botocore.config import Config
from django.conf import settings


def get_s3_client(endpoint_url=None):
    return boto3.client(
        "s3",
        endpoint_url=endpoint_url or settings.MINIO_ENDPOINT,
        aws_access_key_id=settings.MINIO_ACCESS_KEY,
        aws_secret_access_key=settings.MINIO_SECRET_KEY,
        use_ssl=settings.MINIO_SECURE,
        config=Config(signature_version="s3v4"),
    )
