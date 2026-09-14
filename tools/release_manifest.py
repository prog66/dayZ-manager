"""Genere un manifeste de release et des hash SHA-256 deterministes."""

from __future__ import annotations

import argparse
import hashlib
import json
import platform
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from version import APP_NAME, APP_VERSION, MANIFEST_SCHEMA  # noqa: E402


SOURCE_SUFFIXES = {".bat", ".ico", ".md", ".py", ".spec", ".txt"}
IGNORED_PARTS = {
    ".git", ".ruff_cache", ".venv", "__pycache__", "build", "dist",
}


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def source_fingerprint(root: Path = ROOT) -> str:
    """Hash stable des sources, sans secrets, caches et anciens builds."""
    digest = hashlib.sha256()
    files = []
    for path in root.rglob("*"):
        if not path.is_file() or path.suffix.lower() not in SOURCE_SUFFIXES:
            continue
        relative = path.relative_to(root)
        if any(part in IGNORED_PARTS for part in relative.parts):
            continue
        if relative.as_posix() == "config.json":
            continue
        files.append(relative)
    for relative in sorted(files, key=lambda item: item.as_posix().lower()):
        path = root / relative
        digest.update(relative.as_posix().encode("utf-8"))
        digest.update(b"\0")
        digest.update(path.read_bytes())
        digest.update(b"\0")
    return digest.hexdigest()


def build_manifest(artifact: Path, root: Path = ROOT) -> dict:
    requirements = root / "requirements.txt"
    source = {
        "fingerprint": source_fingerprint(root),
        "requirements_sha256": sha256_file(requirements),
    }
    lock = root / "requirements-lock.txt"
    if lock.is_file():
        source["requirements_lock_sha256"] = sha256_file(lock)
    return {
        "schema": MANIFEST_SCHEMA,
        "product": APP_NAME,
        "version": APP_VERSION,
        "platform": f"{platform.system().lower()}-{platform.machine().lower()}",
        "artifact": {
            "name": artifact.name,
            "size_bytes": artifact.stat().st_size,
            "sha256": sha256_file(artifact),
        },
        "source": source,
    }


def write_release_files(artifact: Path, manifest_path: Path, root: Path = ROOT) -> dict:
    manifest = build_manifest(artifact, root)
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    manifest_path.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    checksums_path = manifest_path.parent.parent / "checksums.sha256"
    checksums = [
        f"{manifest['artifact']['sha256']}  {manifest['artifact']['name']}",
        f"{sha256_file(manifest_path)}  {manifest_path.name}",
    ]
    checksums_path.write_text("\n".join(checksums) + "\n", encoding="utf-8")
    return manifest


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--artifact", required=True, type=Path)
    parser.add_argument("--manifest", type=Path)
    args = parser.parse_args()
    artifact = args.artifact.resolve()
    if not artifact.is_file():
        parser.error(f"Artefact introuvable : {artifact}")
    manifest_path = (args.manifest or artifact.parent / "manifest.json").resolve()
    manifest = write_release_files(artifact, manifest_path)
    print(f"MANIFEST_OK version={manifest['version']} sha256={manifest['artifact']['sha256']}")
    print(f"MANIFEST={manifest_path}")
    print(f"CHECKSUMS={manifest_path.parent.parent / 'checksums.sha256'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
