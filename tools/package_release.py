"""Crée l'archive Windows distribuable et son hash SHA-256."""

from __future__ import annotations

import argparse
import hashlib
from pathlib import Path
import zipfile


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def build_archive(source: Path, output: Path) -> tuple[Path, Path]:
    source = source.resolve()
    output = output.resolve()
    if not source.is_dir():
        raise FileNotFoundError(f"Dossier à empaqueter introuvable : {source}")
    if not (source / "DayZManager.exe").is_file():
        raise FileNotFoundError("DayZManager.exe absent du dossier à empaqueter.")
    if not (source / "manifest.json").is_file():
        raise FileNotFoundError("manifest.json absent du dossier à empaqueter.")
    output.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(
        output,
        "w",
        compression=zipfile.ZIP_DEFLATED,
        compresslevel=9,
    ) as archive:
        for path in sorted(source.rglob("*"), key=lambda item: item.as_posix().lower()):
            if not path.is_file():
                continue
            relative = Path(source.name) / path.relative_to(source)
            info = zipfile.ZipInfo(relative.as_posix())
            info.date_time = (1980, 1, 1, 0, 0, 0)
            info.compress_type = zipfile.ZIP_DEFLATED
            info.external_attr = 0o644 << 16
            archive.writestr(info, path.read_bytes())
    checksum = output.with_name(output.name + ".sha256")
    checksum.write_text(
        f"{sha256_file(output)}  {output.name}\n",
        encoding="ascii",
    )
    return output, checksum


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    archive, checksum = build_archive(args.source, args.output)
    print(f"PACKAGE_OK {archive} sha256={sha256_file(archive)}")
    print(f"CHECKSUM={checksum}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
