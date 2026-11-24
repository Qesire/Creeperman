"""Content-addressed file transport. Workers share a store, not a filesystem."""
from __future__ import annotations

import base64
import hashlib
import json
import os
import re
import shutil
import tempfile
from pathlib import Path
from urllib.parse import urlsplit
from .core import canonical, sha

MAX_OBJECT = 512 * 1024 * 1024


class Store:
    def __init__(self, root: str):
        self.root = root
        self.s3 = None
        if root.startswith("s3://"):
            import boto3
            p = urlsplit(root)
            if not p.netloc or p.query or p.fragment:
                raise ValueError("invalid S3 store")
            self.bucket = p.netloc
            self.prefix = p.path.strip("/")
            self.s3 = boto3.client("s3")
        else:
            self.path = Path(root).resolve()
            (self.path / "objects").mkdir(parents=True, exist_ok=True)

    @staticmethod
    def check_ref(ref):
        if not re.fullmatch(r"[0-9a-f]{64}", ref["sha256"]):
            raise ValueError("invalid object hash")
        if type(ref["bytes"]) is not int or not 0 <= ref["bytes"] <= MAX_OBJECT:
            raise ValueError("invalid object size")

    def key(self, ref):
        self.check_ref(ref)
        return "/".join(x for x in (getattr(self, "prefix", ""), "objects", ref["sha256"]) if x)

    def put(self, path: Path):
        ref = {"sha256": sha(path), "bytes": path.stat().st_size}
        key = self.key(ref)
        if self.s3:
            from botocore.exceptions import ClientError
            try:
                with path.open("rb") as f:
                    self.s3.put_object(Bucket=self.bucket, Key=key, Body=f,
                        ContentLength=ref["bytes"], IfNoneMatch="*",
                        ChecksumSHA256=base64.b64encode(bytes.fromhex(ref["sha256"])).decode())
            except ClientError as exc:
                if exc.response["ResponseMetadata"]["HTTPStatusCode"] != 412:
                    raise
                # Another writer published the same key. Consumers verify bytes.
                if self.s3.head_object(Bucket=self.bucket, Key=key)["ContentLength"] != ref["bytes"]:
                    raise ValueError("existing S3 object size mismatch") from exc
        else:
            dst = self.path / key
            fd, name = tempfile.mkstemp(dir=dst.parent, prefix=".upload-")
            os.close(fd)
            tmp = Path(name)
            try:
                shutil.copyfile(path, tmp)
                if sha(tmp) != ref["sha256"] or tmp.stat().st_size != ref["bytes"]:
                    raise ValueError("source changed during publication")
                try:
                    os.link(tmp, dst)
                except FileExistsError:
                    if sha(dst) != ref["sha256"] or dst.stat().st_size != ref["bytes"]:
                        raise ValueError("existing local object corrupted")
            finally:
                tmp.unlink(missing_ok=True)
        return ref

    def put_json(self, data):
        with tempfile.TemporaryDirectory() as t:
            p = Path(t)/"object.json"
            p.write_bytes(canonical(data))
            return self.put(p)

    def materialize(self, ref, dst: Path):
        key = self.key(ref)
        if dst.exists():
            raise FileExistsError(dst)
        fd, name = tempfile.mkstemp(dir=dst.parent, prefix=".download-")
        os.close(fd)
        tmp = Path(name)
        try:
            if self.s3:
                r = self.s3.get_object(Bucket=self.bucket, Key=key)
                body = r["Body"]
                try:
                    if r["ContentLength"] != ref["bytes"]:
                        raise ValueError("unexpected S3 size")
                    with tmp.open("wb") as f:
                        n = 0
                        for chunk in body.iter_chunks(chunk_size=1024*1024):
                            n += len(chunk)
                            if n > ref["bytes"]:
                                raise ValueError("object exceeds declared size")
                            f.write(chunk)
                finally:
                    body.close()
            else:
                src = self.path / key
                if src.stat().st_size != ref["bytes"]:
                    raise ValueError("unexpected local size")
                shutil.copyfile(src, tmp)
            if tmp.stat().st_size != ref["bytes"] or sha(tmp) != ref["sha256"]:
                raise ValueError("object fingerprint mismatch")
            os.replace(tmp, dst)
        finally:
            tmp.unlink(missing_ok=True)
        return dst

    def get_json(self, ref):
        if ref["bytes"] > 4*1024*1024:
            raise ValueError("manifest too large")
        with tempfile.TemporaryDirectory() as t:
            p = self.materialize(ref, Path(t)/"manifest.json")
            return json.loads(p.read_text(encoding="utf-8"))
