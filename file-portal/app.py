import time

from flask import (Flask, abort, flash, jsonify, redirect, render_template,
                   request, url_for)
from werkzeug.exceptions import RequestEntityTooLarge
from werkzeug.utils import secure_filename

from config import Config
from storage import FileStore, normalize_code

_local_server = None


def _start_local_aws(cfg):
    """Start an in-process moto server that emulates S3 + DynamoDB."""
    global _local_server
    if _local_server is None:
        from moto.server import ThreadedMotoServer
        _local_server = ThreadedMotoServer(ip_address="0.0.0.0", port=cfg.LOCAL_AWS_PORT, verbose=False)
        _local_server.start()
    return f"http://{cfg.LOCAL_AWS_HOST}:{cfg.LOCAL_AWS_PORT}"


def create_app(config_object=Config, store=None):
    app = Flask(__name__)
    app.config.from_object(config_object)
    cfg = config_object

    if store is None:
        endpoint = cfg.AWS_ENDPOINT_URL
        if endpoint is None and cfg.USE_LOCAL_AWS:
            endpoint = _start_local_aws(cfg)
        store = FileStore(
            region=cfg.AWS_REGION, bucket=cfg.S3_BUCKET, table_name=cfg.DYNAMODB_TABLE,
            endpoint_url=endpoint, access_key=cfg.AWS_ACCESS_KEY_ID,
            secret_key=cfg.AWS_SECRET_ACCESS_KEY,
        )
        store.ensure_resources()
    app.extensions["file_store"] = store

    def parse_expiry(raw):
        if raw in (None, ""):
            return cfg.DEFAULT_EXPIRY_MINUTES
        try:
            minutes = int(raw)
        except (TypeError, ValueError):
            raise ValueError("Expiry must be a whole number of minutes.")
        if not cfg.MIN_EXPIRY_MINUTES <= minutes <= cfg.MAX_EXPIRY_MINUTES:
            raise ValueError(
                f"Expiry must be between {cfg.MIN_EXPIRY_MINUTES} and {cfg.MAX_EXPIRY_MINUTES} minutes.")
        return minutes

    def do_upload():
        f = request.files.get("file")
        if f is None or not f.filename:
            raise ValueError("Please choose a file to upload.")
        filename = secure_filename(f.filename) or "file"
        minutes = parse_expiry(request.form.get("expiry_minutes"))
        return store.save_file(f.stream, filename, f.mimetype, minutes)

    def load_active(code):
        """Return (record, status) where status is 'ok', 'missing' or 'expired'."""
        code = normalize_code(code)
        if not code:
            return None, "missing"
        record = store.get_record(code)
        if record is None:
            return None, "missing"
        # DynamoDB TTL deletion is lazy, so always verify the stored expiry.
        if record["expires_at"] <= int(time.time()):
            store.delete(record)
            return None, "expired"
        return record, "ok"

    # ---------- HTML routes ----------
    @app.get("/")
    def index():
        return render_template("index.html", default_expiry=cfg.DEFAULT_EXPIRY_MINUTES,
                               min_expiry=cfg.MIN_EXPIRY_MINUTES, max_expiry=cfg.MAX_EXPIRY_MINUTES)

    @app.post("/upload")
    def upload():
        try:
            result = do_upload()
        except ValueError as e:
            flash(str(e), "error")
            return redirect(url_for("index"))
        return render_template("uploaded.html", result=result,
                               share_url=url_for("file_page", code=result["access_code"], _external=True))

    @app.get("/retrieve")
    def retrieve():
        code = normalize_code(request.args.get("code"))
        if not code:
            flash("Please enter an access code.", "error")
            return redirect(url_for("index"))
        return redirect(url_for("file_page", code=code))

    @app.get("/f/<code>")
    def file_page(code):
        record, status = load_active(code)
        if status != "ok":
            return render_template("unavailable.html", status=status), (410 if status == "expired" else 404)
        return render_template("file.html", record=record, now=int(time.time()))

    @app.get("/download/<code>")
    def download(code):
        record, status = load_active(code)
        if status != "ok":
            return render_template("unavailable.html", status=status), (410 if status == "expired" else 404)
        remaining = record["expires_at"] - int(time.time())
        return redirect(store.presigned_url(record, min(remaining, cfg.PRESIGNED_URL_SECONDS)))

    # ---------- JSON API ----------
    @app.post("/api/upload")
    def api_upload():
        try:
            result = do_upload()
        except ValueError as e:
            return jsonify(error=str(e)), 400
        result["share_url"] = url_for("file_page", code=result["access_code"], _external=True)
        return jsonify(result), 201

    @app.get("/api/files/<code>")
    def api_file(code):
        record, status = load_active(code)
        if status == "expired":
            return jsonify(error="File has expired"), 410
        if status != "ok":
            return jsonify(error="File not found"), 404
        remaining = record["expires_at"] - int(time.time())
        return jsonify(
            access_code=record["access_code"], filename=record["filename"],
            expires_at=record["expires_at"], seconds_remaining=remaining,
            download_url=store.presigned_url(record, min(remaining, cfg.PRESIGNED_URL_SECONDS)),
        )

    @app.errorhandler(RequestEntityTooLarge)
    def too_large(_):
        msg = f"File too large (max {cfg.MAX_CONTENT_LENGTH // (1024 * 1024)} MB)."
        if request.path.startswith("/api/"):
            return jsonify(error=msg), 413
        flash(msg, "error")
        return redirect(url_for("index"))

    @app.template_filter("datetime")
    def fmt_dt(ts):
        return time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(int(ts)))

    return app


if __name__ == "__main__":
    import os
    app = create_app()
    # Reloader disabled: it would start the embedded moto server twice.
    app.run(host=os.getenv("HOST", "127.0.0.1"), port=int(os.getenv("PORT", "5000")),
            debug=True, use_reloader=False)
