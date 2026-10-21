"""S3 + DynamoDB access layer for File Portal."""
import secrets
import time

import boto3
from botocore.exceptions import ClientError

CODE_ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"  # no ambiguous 0/O/1/I
CODE_LENGTH = 8


def generate_access_code():
    return "".join(secrets.choice(CODE_ALPHABET) for _ in range(CODE_LENGTH))


def normalize_code(code):
    return "".join(ch for ch in (code or "").upper() if ch.isalnum())


class FileStore:
    def __init__(self, region, bucket, table_name, endpoint_url=None,
                 access_key=None, secret_key=None):
        session = boto3.session.Session(
            aws_access_key_id=access_key,
            aws_secret_access_key=secret_key,
            region_name=region,
        )
        self.region = region
        self.bucket = bucket
        self.table_name = table_name
        self.s3 = session.client("s3", endpoint_url=endpoint_url)
        self.dynamodb = session.resource("dynamodb", endpoint_url=endpoint_url)
        self.table = self.dynamodb.Table(table_name)

    # ---------- setup ----------
    def ensure_resources(self):
        """Create bucket/table and enable TTL if they don't exist (idempotent)."""
        try:
            self.s3.head_bucket(Bucket=self.bucket)
        except ClientError:
            kwargs = {"Bucket": self.bucket}
            if self.region != "us-east-1":
                kwargs["CreateBucketConfiguration"] = {"LocationConstraint": self.region}
            self.s3.create_bucket(**kwargs)

        client = self.dynamodb.meta.client
        try:
            client.describe_table(TableName=self.table_name)
        except client.exceptions.ResourceNotFoundException:
            client.create_table(
                TableName=self.table_name,
                KeySchema=[{"AttributeName": "access_code", "KeyType": "HASH"}],
                AttributeDefinitions=[{"AttributeName": "access_code", "AttributeType": "S"}],
                BillingMode="PAY_PER_REQUEST",
            )
            client.get_waiter("table_exists").wait(TableName=self.table_name)

        ttl = client.describe_time_to_live(TableName=self.table_name)
        status = ttl.get("TimeToLiveDescription", {}).get("TimeToLiveStatus")
        if status not in ("ENABLED", "ENABLING"):
            client.update_time_to_live(
                TableName=self.table_name,
                TimeToLiveSpecification={"Enabled": True, "AttributeName": "expires_at"},
            )

    # ---------- operations ----------
    def save_file(self, fileobj, filename, content_type, expiry_minutes, now=None):
        now = int(now if now is not None else time.time())
        expires_at = now + int(expiry_minutes) * 60

        for _ in range(5):
            code = generate_access_code()
            key = f"uploads/{code}/{filename}"
            try:
                # Reserve the code first so two uploads can never share it.
                self.table.put_item(
                    Item={
                        "access_code": code,
                        "filename": filename,
                        "s3_key": key,
                        "content_type": content_type or "application/octet-stream",
                        "created_at": now,
                        "expires_at": expires_at,
                    },
                    ConditionExpression="attribute_not_exists(access_code)",
                )
            except ClientError as e:
                if e.response["Error"]["Code"] == "ConditionalCheckFailedException":
                    continue
                raise
            try:
                self.s3.upload_fileobj(
                    fileobj, self.bucket, key,
                    ExtraArgs={"ContentType": content_type or "application/octet-stream"},
                )
            except Exception:
                self.table.delete_item(Key={"access_code": code})
                raise
            return {"access_code": code, "filename": filename, "expires_at": expires_at}
        raise RuntimeError("Could not allocate a unique access code")

    def get_record(self, code):
        resp = self.table.get_item(Key={"access_code": code})
        item = resp.get("Item")
        if item:
            for k in ("created_at", "expires_at"):
                item[k] = int(item[k])
        return item

    def delete(self, record):
        try:
            self.s3.delete_object(Bucket=self.bucket, Key=record["s3_key"])
        finally:
            self.table.delete_item(Key={"access_code": record["access_code"]})

    def presigned_url(self, record, expires_in):
        return self.s3.generate_presigned_url(
            "get_object",
            Params={
                "Bucket": self.bucket,
                "Key": record["s3_key"],
                "ResponseContentDisposition": f'attachment; filename="{record["filename"]}"',
                "ResponseContentType": record.get("content_type", "application/octet-stream"),
            },
            ExpiresIn=max(1, int(expires_in)),
        )
