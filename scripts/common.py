from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path

import requests


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def download_atomic(url: str, destination: Path,
                    expected_sha256: str | None = None) -> str:
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_suffix(destination.suffix + ".tmp")
    with requests.get(url, stream=True, timeout=(30, 300)) as response:
        response.raise_for_status()
        if "text/html" in response.headers.get("content-type", ""):
            raise ValueError(f"refusing HTML response from {url}")
        with temporary.open("wb") as stream:
            for chunk in response.iter_content(1024 * 1024):
                if chunk:
                    stream.write(chunk)
    digest = sha256_file(temporary)
    if expected_sha256 and digest != expected_sha256:
        temporary.unlink(missing_ok=True)
        raise ValueError(f"checksum mismatch for {url}")
    os.replace(temporary, destination)
    return digest


def write_manifest(path: Path, manifest: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n")
    os.replace(temporary, path)
