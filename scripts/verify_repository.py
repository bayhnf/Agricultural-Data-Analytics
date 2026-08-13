"""Task 11 slice B: privacy, size, and static-page reference verifier."""

from __future__ import annotations

import re
import subprocess
from dataclasses import dataclass, field
from html.parser import HTMLParser
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MAX_TRACKED_BYTES = 10 * 1024 * 1024

# Filename rules match lowercased path components (files and directories).
# Content rules require a plausible assigned value so documentation that
# merely names the prefixes/field names as scanner rules stays accepted.
FILENAME_RULES = (
    (".env", ".env file"),
    ("classroom", "Classroom archive"),
    ("oauth", "OAuth material"),
    ("token", "token material"),
)

CREDENTIAL_PATTERNS = (
    (re.compile(r"ghp_[A-Za-z0-9]{20,}"), "GitHub classic PAT"),
    (re.compile(r"github_pat_[A-Za-z0-9_]{20,}"), "GitHub fine-grained PAT"),
    (re.compile(r"GOCSPX-[A-Za-z0-9_-]{10,}"), "Google OAuth client secret"),
    (re.compile(r"refresh_token[\"']?\s*[:=]\s*[\"'][^\"']{8,}[\"']"),
     "assigned refresh_token"),
    (re.compile(r"client_secret[\"']?\s*[:=]\s*[\"'][^\"']{8,}[\"']"),
     "assigned client_secret"),
)


@dataclass
class ScanResult:
    tracked_count: int = 0
    reference_count: int = 0
    findings: list[str] = field(default_factory=list)


def list_tracked_files(root: Path, git: str = "git") -> list[str]:
    process = subprocess.run(
        [git, "-C", str(root), "ls-files", "-z"],
        check=True, capture_output=True)
    return [name for name in
            process.stdout.decode("utf-8", "replace").split("\0") if name]


def scan_tracked_file(root: Path, relative: str) -> list[str]:
    path = root / relative
    findings: list[str] = []
    for part in relative.split("/"):
        lowered = part.lower()
        for marker, label in FILENAME_RULES:
            if marker in lowered:
                findings.append(
                    f"privacy: tracked file '{relative}' matches the "
                    f"{label} filename rule; remove it from tracking")
        if lowered.endswith(".zip"):
            findings.append(
                f"privacy: tracked file '{relative}' matches the private "
                f"source ZIP rule; remove it from tracking")
    size = path.stat().st_size
    if size > MAX_TRACKED_BYTES:
        findings.append(
            f"size: tracked file '{relative}' is {size} bytes "
            f"(limit {MAX_TRACKED_BYTES}); reduce or stop tracking it")
        return findings
    try:
        content = path.read_bytes().decode("latin-1")
    except OSError:
        return findings
    for pattern, label in CREDENTIAL_PATTERNS:
        if pattern.search(content):
            findings.append(
                f"privacy: tracked file '{relative}' contains a "
                f"{label} (value redacted); rotate and remove it")
    return findings


class ReferenceParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.references: list[tuple[str, str]] = []

    def handle_starttag(self, tag: str,
                        attrs: list[tuple[str, str | None]]) -> None:
        values = dict(attrs)
        if tag == "img" and values.get("src"):
            self.references.append(("image", values["src"]))
        elif (tag == "link" and values.get("href")
                and "stylesheet" in (values.get("rel") or "").lower()):
            self.references.append(("stylesheet", values["href"]))
        elif tag == "script" and values.get("src"):
            self.references.append(("script", values["src"]))
        elif tag == "a" and (values.get("href") or "").endswith(".json"):
            self.references.append(("json", values["href"]))
        if values.get("data-dashboard"):
            self.references.append(("dashboard", values["data-dashboard"]))


def is_local_reference(value: str) -> bool:
    stripped = value.strip()
    if not stripped or stripped.startswith("#"):
        return False
    return re.match(r"^(?:[a-z][a-z0-9+.-]*:|//)", stripped, re.IGNORECASE) is None


def scan_html_references(index: Path, docs: Path) -> tuple[int, list[str]]:
    parser = ReferenceParser()
    parser.feed(index.read_text(encoding="utf-8"))
    findings: list[str] = []
    checked = 0
    for kind, value in parser.references:
        if not is_local_reference(value):
            continue
        checked += 1
        target = value.split("?", 1)[0].split("#", 1)[0]
        if not (docs / target).is_file():
            findings.append(
                f"reference: docs/index.html {kind} reference '{value}' "
                f"does not resolve; add the file or fix the path")
    return checked, findings


def verify(root: Path = ROOT) -> ScanResult:
    result = ScanResult()
    files = list_tracked_files(root)
    result.tracked_count = len(files)
    for relative in files:
        result.findings.extend(scan_tracked_file(root, relative))
    index = root / "docs/index.html"
    if index.is_file():
        result.reference_count, ref_findings = scan_html_references(
            index, root / "docs")
        result.findings.extend(ref_findings)
    return result


def main(root: Path = ROOT) -> int:
    result = verify(root)
    for finding in result.findings:
        print("FAIL:", finding)
    print(f"checked {result.tracked_count} tracked files and "
          f"{result.reference_count} local HTML references")
    return 1 if result.findings else 0


if __name__ == "__main__":
    raise SystemExit(main())
