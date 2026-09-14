"""Verifie que l'environnement de build respecte le lock de dependances."""

from __future__ import annotations

import argparse
import importlib.metadata
import re
from pathlib import Path


LOCK_LINE = re.compile(r"^([A-Za-z0-9_.-]+)==([^#\s]+)$")


def read_lock(path: Path) -> list[tuple[str, str]]:
    requirements = []
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        match = LOCK_LINE.fullmatch(line)
        if not match:
            raise ValueError(f"Ligne de lock invalide : {line}")
        requirements.append((match.group(1), match.group(2)))
    return requirements


def verify(path: Path) -> list[str]:
    errors = []
    for name, expected in read_lock(path):
        try:
            installed = importlib.metadata.version(name)
        except importlib.metadata.PackageNotFoundError:
            errors.append(f"{name}: absent (attendu {expected})")
            continue
        if installed != expected:
            errors.append(f"{name}: {installed} (attendu {expected})")
    return errors


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--lock", type=Path, default=Path("requirements-lock.txt"))
    args = parser.parse_args()
    errors = verify(args.lock.resolve())
    if errors:
        print("ENVIRONMENT_NOT_LOCKED")
        print("\n".join(errors))
        return 1
    print(f"ENVIRONMENT_LOCKED {args.lock.resolve()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
