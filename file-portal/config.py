import os

from dotenv import load_dotenv

load_dotenv()


def _bool(name, default):
    return os.getenv(name, str(default)).strip().lower() in ("1", "true", "yes", "on")


class Config:
    SECRET_KEY = os.getenv("SECRET_KEY", "dev-secret-change-me")

    # AWS (dummy defaults so the app runs locally without real credentials)
    AWS_REGION = os.getenv("AWS_REGION", "us-east-1")
    AWS_ACCESS_KEY_ID = os.getenv("AWS_ACCESS_KEY_ID", "dummy-access-key")
    AWS_SECRET_ACCESS_KEY = os.getenv("AWS_SECRET_ACCESS_KEY", "dummy-secret-key")
    S3_BUCKET = os.getenv("S3_BUCKET", "file-portal-uploads")
    DYNAMODB_TABLE = os.getenv("DYNAMODB_TABLE", "file-portal-files")

    # When true, an in-process moto server emulates S3 + DynamoDB on localhost.
    USE_LOCAL_AWS = _bool("USE_LOCAL_AWS", True)
    LOCAL_AWS_HOST = os.getenv("LOCAL_AWS_HOST", "127.0.0.1")
    LOCAL_AWS_PORT = int(os.getenv("LOCAL_AWS_PORT", "5001"))
    # Optional explicit endpoint (e.g. LocalStack); overrides the local moto server.
    AWS_ENDPOINT_URL = os.getenv("AWS_ENDPOINT_URL") or None

    # Expiry settings (minutes)
    DEFAULT_EXPIRY_MINUTES = int(os.getenv("DEFAULT_EXPIRY_MINUTES", "10"))
    MIN_EXPIRY_MINUTES = int(os.getenv("MIN_EXPIRY_MINUTES", "1"))
    MAX_EXPIRY_MINUTES = int(os.getenv("MAX_EXPIRY_MINUTES", "1440"))

    # Short lifetime for each generated pre-signed URL; capped by remaining file lifetime.
    PRESIGNED_URL_SECONDS = int(os.getenv("PRESIGNED_URL_SECONDS", "60"))

    MAX_CONTENT_LENGTH = int(os.getenv("MAX_UPLOAD_MB", "50")) * 1024 * 1024
