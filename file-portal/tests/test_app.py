import io
import time

import pytest
from moto import mock_aws

from app import create_app
from config import Config
from storage import FileStore


class TestConfig(Config):
    TESTING = True
    USE_LOCAL_AWS = False
    AWS_ENDPOINT_URL = None


@pytest.fixture
def store():
    with mock_aws():
        s = FileStore(region="us-east-1", bucket="test-bucket", table_name="test-table",
                      access_key="testing", secret_key="testing")
        s.ensure_resources()
        yield s


@pytest.fixture
def client(store):
    return create_app(TestConfig, store=store).test_client()


def upload(client, name="hello.txt", data=b"hello world", expiry=None):
    form = {"file": (io.BytesIO(data), name)}
    if expiry is not None:
        form["expiry_minutes"] = str(expiry)
    return client.post("/api/upload", data=form, content_type="multipart/form-data")


def test_ttl_enabled(store):
    ttl = store.dynamodb.meta.client.describe_time_to_live(TableName="test-table")
    assert ttl["TimeToLiveDescription"]["AttributeName"] == "expires_at"


def test_upload_uses_default_10_minute_expiry(client, store):
    before = int(time.time())
    resp = upload(client)
    assert resp.status_code == 201
    body = resp.get_json()
    assert before + 600 <= body["expires_at"] <= int(time.time()) + 600
    record = store.get_record(body["access_code"])
    assert record["filename"] == "hello.txt"
    obj = store.s3.get_object(Bucket="test-bucket", Key=record["s3_key"])
    assert obj["Body"].read() == b"hello world"


def test_custom_expiry_and_validation(client):
    assert upload(client, expiry=30).get_json()["expires_at"] >= int(time.time()) + 30 * 60 - 1
    assert upload(client, expiry=0).status_code == 400
    assert upload(client, expiry=99999).status_code == 400
    assert upload(client, expiry="abc").status_code == 400


def test_retrieve_returns_presigned_url(client):
    code = upload(client).get_json()["access_code"]
    resp = client.get(f"/api/files/{code.lower()}")  # codes are case-insensitive
    assert resp.status_code == 200
    body = resp.get_json()
    assert "X-Amz-Expires" in body["download_url"] or "Expires=" in body["download_url"]
    assert 0 < body["seconds_remaining"] <= 600

    page = client.get(f"/f/{code}")
    assert page.status_code == 200 and b"hello.txt" in page.data
    dl = client.get(f"/download/{code}")
    assert dl.status_code == 302 and "test-bucket" in dl.headers["Location"]


def test_unknown_code_returns_404(client):
    assert client.get("/api/files/NOPE2345").status_code == 404
    assert client.get("/f/NOPE2345").status_code == 404


def test_expired_file_is_rejected_and_cleaned_up(client, store):
    past = int(time.time()) - 3600
    rec = store.save_file(io.BytesIO(b"old"), "old.txt", "text/plain", 10, now=past)
    code = rec["access_code"]
    key = store.get_record(code)["s3_key"]

    assert client.get(f"/download/{code}").status_code == 410
    assert store.get_record(code) is None
    listed = store.s3.list_objects_v2(Bucket="test-bucket", Prefix=key)
    assert listed.get("KeyCount", 0) == 0
    assert client.get(f"/api/files/{code}").status_code == 404


def test_twenty_sample_files_round_trip(client, store):
    codes = {}
    for i in range(20):
        data = f"sample file {i}".encode() * (i + 1)
        codes[upload(client, name=f"sample_{i}.txt", data=data).get_json()["access_code"]] = data
    assert len(codes) == 20
    for code, data in codes.items():
        rec = store.get_record(code)
        assert store.s3.get_object(Bucket="test-bucket", Key=rec["s3_key"])["Body"].read() == data


def test_html_upload_flow(client):
    resp = client.post("/upload", data={"file": (io.BytesIO(b"x"), "../evil name.txt")},
                       content_type="multipart/form-data")
    assert resp.status_code == 200
    assert b"evil_name.txt" in resp.data  # filename sanitised
    assert client.post("/upload", data={}, content_type="multipart/form-data").status_code == 302
