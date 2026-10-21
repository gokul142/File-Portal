# File Portal

Temporary file-sharing web app built with **Python, Flask, AWS S3, DynamoDB, HTML5 and CSS3**.

- Files are stored in **S3**; metadata (access code, filename, S3 key, expiry) lives in **DynamoDB**.
- Each upload gets a unique 8-character **access code** and share link (`/f/<code>`).
- Configurable expiry (**10 minutes by default**). Every request checks the stored
  `expires_at` timestamp; downloads use short-lived **S3 pre-signed URLs** that never outlive the file.
- **DynamoDB TTL** is enabled on `expires_at` to clean up expired records; expired S3 objects
  are also deleted when accessed.

## Run locally (no AWS account needed)

By default the app starts an embedded [moto](https://github.com/getmoto/moto) server on
`localhost:5001` that emulates S3 and DynamoDB using dummy credentials.

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
python app.py
```

Open http://127.0.0.1:5000. Local data is in-memory and resets on restart.

**Testing from other devices on your network:** set `HOST=0.0.0.0` and
`LOCAL_AWS_HOST=<your-LAN-IP>` (in `.env` or the environment), then browse to `http://<your-LAN-IP>:5000`.

## Use real AWS

Copy `.env.example` to `.env` and set:

```
USE_LOCAL_AWS=false
AWS_ACCESS_KEY_ID=...
AWS_SECRET_ACCESS_KEY=...
AWS_REGION=us-east-1
S3_BUCKET=<globally-unique-bucket-name>
DYNAMODB_TABLE=file-portal-files
```

On startup the app creates the bucket and table (partition key `access_code`) if missing and enables TTL on
`expires_at`. The IAM identity needs `s3:CreateBucket/PutObject/GetObject/DeleteObject/ListBucket` and
`dynamodb:CreateTable/DescribeTable/PutItem/GetItem/DeleteItem/DescribeTimeToLive/UpdateTimeToLive`.
Consider an S3 lifecycle rule as a backstop for objects that are never accessed after expiry.

## Endpoints

| Method | Path | Description |
|---|---|---|
| GET | `/` | Upload / retrieve UI |
| POST | `/upload` | Upload form (`file`, `expiry_minutes`) |
| GET | `/retrieve?code=XXXX` | Redirects to file page |
| GET | `/f/<code>` | File details + countdown |
| GET | `/download/<code>` | Verifies expiry, redirects to pre-signed S3 URL |
| POST | `/api/upload` | JSON API upload → `{access_code, expires_at, share_url}` |
| GET | `/api/files/<code>` | JSON metadata + pre-signed `download_url` (404 / 410 if missing / expired) |

## Tests

```powershell
python -m pytest -q
```

Tests run fully offline using moto (`mock_aws`) and cover upload, retrieval, expiry/cleanup,
validation, and a 20-file round trip.
