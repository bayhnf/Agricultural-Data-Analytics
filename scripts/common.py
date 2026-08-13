from __future__ import annotations

import hashlib
import json
import os
import time
from pathlib import Path

import requests

DOWNLOAD_RETRIES = 3
RETRY_DELAY_SECONDS = 1.0


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _transient_status(status: int | None) -> bool:
    return status == 429 or (status is not None and status >= 500)


def download_atomic(url: str, destination: Path,
                    expected_sha256: str | None = None) -> str:
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_suffix(destination.suffix + ".tmp")
    for attempt in range(DOWNLOAD_RETRIES):
        try:
            with requests.get(url, stream=True, timeout=(30, 300)) as response:
                response.raise_for_status()
                if "text/html" in response.headers.get("content-type", ""):
                    raise ValueError(f"refusing HTML response from {url}")
                with temporary.open("wb") as stream:
                    for chunk in response.iter_content(1024 * 1024):
                        if chunk:
                            stream.write(chunk)
            break
        except ValueError:
            temporary.unlink(missing_ok=True)
            raise
        except requests.HTTPError as error:
            status = (error.response.status_code
                      if error.response is not None else None)
            if not _transient_status(status) or attempt == DOWNLOAD_RETRIES - 1:
                temporary.unlink(missing_ok=True)
                raise
            time.sleep(RETRY_DELAY_SECONDS)
        except requests.RequestException:
            if attempt == DOWNLOAD_RETRIES - 1:
                temporary.unlink(missing_ok=True)
                raise
            time.sleep(RETRY_DELAY_SECONDS)
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
