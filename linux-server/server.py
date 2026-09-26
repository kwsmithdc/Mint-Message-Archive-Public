#!/usr/bin/env python3

import argparse
import base64
import cgi
import json
import ipaddress
import os
import hmac
import binascii
import pathlib
import tempfile
import zipfile
import re
from database import ArchiveDatabase
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from web import handle_get

MAX_UPLOAD = 2 * 1024 * 1024 * 1024  # 2 GiB


def is_local_client(address):
    """Allow only loopback, RFC1918, link-local, or IPv6 ULA client addresses."""
    try:
        ip = ipaddress.ip_address(address)
    except ValueError:
        return False

    if ip.is_loopback:
        return True

    if ip.version == 4:
        return (
            ip in ipaddress.ip_network("10.0.0.0/8")
            or ip in ipaddress.ip_network("172.16.0.0/12")
            or ip in ipaddress.ip_network("192.168.0.0/16")
            or ip in ipaddress.ip_network("169.254.0.0/16")
        )

    return (
        ip in ipaddress.ip_network("fc00::/7")
        or ip in ipaddress.ip_network("fe80::/10")
    )


def require_local_client(handler):
    """Reject archive requests originating outside the local/private network."""
    client_ip = handler.client_address[0]
    if is_local_client(client_ip):
        return True

    handler.send_json(403, {
        "error": "archive server accepts connections only from the local network"
    })
    return False


def safe_archive_filename(filename):
    name = pathlib.Path(str(filename or "")).name
    if not name or name in {".", ".."} or len(name) > 255:
        raise ValueError("archive filename is invalid")
    if any(ord(char) < 32 or ord(char) == 127 for char in name):
        raise ValueError("archive filename is invalid")
    return name


def is_safe_device_id(device_id):
    """Accept only device IDs that are safe to use as archive directory names."""
    return bool(re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]{0,127}", device_id))


def read_manifest(zip_path):
    """Read device information from manifest.json."""
    with zipfile.ZipFile(zip_path, "r") as z:
        if "manifest.json" not in z.namelist():
            raise ValueError("archive is missing manifest.json")
        with z.open("manifest.json") as f:
            manifest = json.load(f)
    if not isinstance(manifest, dict):
        raise ValueError("manifest must be a JSON object")
    device_id = manifest.get("deviceId")
    device_alias = manifest.get("deviceAlias", "")
    if not device_id:
        raise ValueError("manifest is missing deviceId")
    device_id = str(device_id)
    if not is_safe_device_id(device_id):
        raise ValueError("manifest contains an invalid deviceId")
    return {"deviceId": device_id, "deviceAlias": str(device_alias)}


def update_device_registry(device_dir, device_id, device_alias, seen_at):
    """Create or update device.json using the archive's canonical receive time."""
    device_file = device_dir / "device.json"
    if device_file.exists():
        try:
            with device_file.open("r", encoding="utf-8") as f:
                device = json.load(f)
        except (OSError, json.JSONDecodeError):
            device = {}
        first_seen = device.get("firstSeen", seen_at)
    else:
        first_seen = seen_at

    device = {
        "deviceId": device_id,
        "deviceAlias": device_alias,
        "firstSeen": first_seen,
        "lastSeen": seen_at,
    }
    device_dir.mkdir(parents=True, exist_ok=True)
    with device_file.open("w", encoding="utf-8") as f:
        json.dump(device, f, indent=2)
        f.write("\n")


class Handler(BaseHTTPRequestHandler):
    server_version = "MintMessageArchive/0.1"

    def log_message(self, fmt, *args):
        print("[%s] %s" % (datetime.now().isoformat(timespec="seconds"), fmt % args), flush=True)

    def send_json(self, status, obj):
        data = json.dumps(obj, indent=2).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def authorized(self):
        """Accept the bearer token used by Android and Basic auth for browsers."""
        expected = self.server.token
        header = self.headers.get("Authorization", "")
        if expected and hmac.compare_digest(header, "Bearer " + expected):
            return True
        if expected and header.startswith("Basic "):
            try:
                decoded = base64.b64decode(header[6:], validate=True).decode("utf-8")
                username, password = decoded.split(":", 1)
                return hmac.compare_digest(username, "archive") and hmac.compare_digest(password, expected)
            except (ValueError, UnicodeDecodeError, binascii.Error):
                return False
        return False

    def require_web_auth(self):
        if self.authorized():
            return True
        self.send_response(401)
        self.send_header("WWW-Authenticate", 'Basic realm="Mint Message Archive"')
        self.send_header("Content-Length", "0")
        self.end_headers()
        return False

    def do_GET(self):
        if not require_local_client(self):
            return
        if self.path == "/health":
            self.send_json(200, {"ok": True, "service": "Mint Message Archive"})
            return
        if not self.require_web_auth():
            return
        if handle_get(self):
            return
        self.send_json(404, {"error": "not found"})

    def do_POST(self):
        if not require_local_client(self):
            return
        if self.path != "/upload":
            self.send_json(404, {"error": "not found"})
            return
        if not self.authorized():
            self.send_json(401, {"error": "unauthorized"})
            return
        try:
            length = int(self.headers.get("Content-Length", "0"))
        except ValueError:
            length = 0
        if length <= 0 or length > MAX_UPLOAD:
            self.send_json(413, {"error": "invalid upload size"})
            return
        ctype, pdict = cgi.parse_header(self.headers.get("Content-Type", ""))
        if ctype != "multipart/form-data" or "boundary" not in pdict:
            self.send_json(400, {"error": "expected multipart/form-data"})
            return
        self.headers["content-length"] = str(length)
        fs = cgi.FieldStorage(fp=self.rfile, headers=self.headers, environ={
            "REQUEST_METHOD": "POST", "CONTENT_TYPE": self.headers.get("Content-Type"), "CONTENT_LENGTH": str(length)
        })
        if "file" not in fs:
            self.send_json(400, {"error": "missing file field"})
            return
        item = fs["file"]
        stamp = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        outdir = self.server.archive / stamp
        outdir.mkdir(parents=True, exist_ok=True)
        fd, tmp = tempfile.mkstemp(prefix=".upload-", suffix=".part", dir=outdir)
        os.close(fd)
        try:
            filename = safe_archive_filename(item.filename or "backup.zip")
            with open(tmp, "wb") as out:
                src = item.file
                while True:
                    chunk = src.read(1024 * 1024)
                    if not chunk:
                        break
                    out.write(chunk)
            device_info = read_manifest(tmp)
            device_id = device_info["deviceId"]
            device_alias = device_info["deviceAlias"]
            device_dir = self.server.archive / "devices" / device_id
            received_at = datetime.now(timezone.utc).isoformat()
            update_device_registry(
                device_dir,
                device_id,
                device_alias,
                received_at,
            )
            device_outdir = device_dir / "archives" / stamp
            device_outdir.mkdir(parents=True, exist_ok=True)
            final = device_outdir / filename
            try:
                os.link(tmp, final)
            except FileExistsError:
                pass
            finally:
                if os.path.exists(tmp):
                    os.unlink(tmp)
            self.server.database.register_device(device_id, device_alias, received_at, received_at)
            archive_id = self.server.database.register_archive(device_id, filename, str(final), received_at)
            if archive_id is None:
                raise RuntimeError("could not register uploaded archive")
            sms_count = self.server.database.import_sms_from_archive(device_id, archive_id, str(final))
            mms_result = self.server.database.import_mms_from_archive(device_id, archive_id, str(final))
            log = device_outdir / "received.jsonl"
            with log.open("a", encoding="utf-8") as f:
                f.write(json.dumps({
                    "receivedAt": received_at, "filename": filename,
                    "bytes": final.stat().st_size, "remote": self.client_address[0],
                    "deviceId": device_id, "deviceAlias": device_alias,
                    "indexed": {"sms": sms_count, "mms": mms_result["messages"], "mmsParts": mms_result["parts"], "participants": mms_result["participants"], "attachments": mms_result["attachments"]}
                }) + "\n")
            self.send_json(201, {
                "ok": True, "file": str(final), "deviceId": device_id, "deviceAlias": device_alias,
                "indexed": {"sms": sms_count, "mms": mms_result["messages"], "mmsParts": mms_result["parts"], "participants": mms_result["participants"], "attachments": mms_result["attachments"]}
            })
        except (ValueError, OSError, zipfile.BadZipFile, json.JSONDecodeError) as exc:
            self.send_json(400, {"error": str(exc)})
            if os.path.exists(tmp):
                os.unlink(tmp)
        except Exception as exc:
            self.send_json(500, {"error": str(exc)})
            if os.path.exists(tmp):
                os.unlink(tmp)
        finally:
            if os.path.exists(tmp):
                os.unlink(tmp)


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--bind", default="127.0.0.1")
    p.add_argument("--port", type=int, default=8765)
    p.add_argument("--archive", required=True)
    p.add_argument("--token")
    p.add_argument("--token-file")

    args = p.parse_args()

    if args.token_file:
        token_path = pathlib.Path(args.token_file).expanduser()
        try:
            args.token = token_path.read_text(encoding="utf-8").strip()
        except OSError as exc:
            p.error(f"Unable to read token file: {exc}")

    if not args.token:
        p.error("A token is required; use --token or --token-file")

    archive = pathlib.Path(args.archive).expanduser().resolve()
    archive.mkdir(parents=True, exist_ok=True)
    httpd = ThreadingHTTPServer((args.bind, args.port), Handler)
    httpd.archive = archive
    httpd.database = ArchiveDatabase(archive)
    httpd.database.initialize()
    httpd.token = args.token
    print(f"Mint Message Archive server listening on {args.bind}:{args.port}")
    print(f"Archive directory: {archive}")
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        httpd.server_close()


if __name__ == "__main__":
    main()
