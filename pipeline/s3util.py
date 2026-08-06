"""Garage S3 存取（LAN 直連 .190:3900）。

歷史 parquet 與模型檔都放 bucket `youbike`：本機訓練完上傳，容器啟動時下載。
金鑰由環境變數帶入（Dokploy compose 的 Environment），不進 git。
"""
from __future__ import annotations

import os
from pathlib import Path

import boto3
from botocore.config import Config

ENDPOINT = os.getenv("S3_ENDPOINT", "http://192.168.50.190:3900")
BUCKET = os.getenv("S3_BUCKET", "youbike")


def client():
    key = os.getenv("S3_ACCESS_KEY")
    secret = os.getenv("S3_SECRET_KEY")
    if not key or not secret:
        raise RuntimeError("缺少 S3_ACCESS_KEY / S3_SECRET_KEY")
    return boto3.client(
        "s3",
        endpoint_url=ENDPOINT,
        aws_access_key_id=key,
        aws_secret_access_key=secret,
        region_name="garage",
        config=Config(s3={"addressing_style": "path"}),
    )


def upload(local: Path, key: str) -> None:
    from boto3.s3.transfer import TransferConfig

    cfg = TransferConfig(multipart_threshold=32 * 1024 * 1024,
                         multipart_chunksize=32 * 1024 * 1024)
    client().upload_file(str(local), BUCKET, key, Config=cfg)
    print(f"[s3] ↑ {key} ({local.stat().st_size / 1e6:.1f} MB)")


def download(key: str, local: Path) -> None:
    local.parent.mkdir(parents=True, exist_ok=True)
    tmp = local.with_suffix(local.suffix + ".part")
    client().download_file(BUCKET, key, str(tmp))
    tmp.replace(local)
    print(f"[s3] ↓ {key} → {local} ({local.stat().st_size / 1e6:.1f} MB)")


def list_keys(prefix: str = "") -> list[str]:
    paginator = client().get_paginator("list_objects_v2")
    out: list[str] = []
    for page in paginator.paginate(Bucket=BUCKET, Prefix=prefix):
        out += [o["Key"] for o in page.get("Contents", [])]
    return out
