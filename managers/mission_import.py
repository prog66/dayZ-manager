"""Bounded ZIP preparation and transactional mission import."""

from contextlib import contextmanager
from pathlib import Path, PurePosixPath
import shutil
import stat
import tempfile
import zipfile

from managers.map_manager import prepare_mission_source
from managers.cfg_editor import _validate_map_names, mpmissions_path
from ssh.connection import connection

MAX_FILES = 20000
MAX_BYTES = 2 * 1024 ** 3


@contextmanager
def mission_source(path):
    source = Path(path).expanduser().resolve()
    if source.is_dir():
        yield prepare_mission_source(source)
        return
    if not source.is_file() or not zipfile.is_zipfile(source):
        raise ValueError("Sélectionne un dossier de mission ou une archive ZIP valide.")
    with tempfile.TemporaryDirectory(prefix="dayz-mission-") as temporary:
        root = Path(temporary)
        with zipfile.ZipFile(source) as archive:
            entries = archive.infolist()
            if len(entries) > MAX_FILES or sum(item.file_size for item in entries) > MAX_BYTES:
                raise ValueError("Archive trop volumineuse (maximum 20 000 entrées / 2 Go extraits).")
            seen = set()
            for item in entries:
                path = PurePosixPath(item.filename.replace("\\", "/"))
                parts = path.parts
                mode = item.external_attr >> 16
                if (path.is_absolute() or ".." in parts or not parts
                        or any(":" in part or part.endswith((" ", ".")) for part in parts)
                        or stat.S_ISLNK(mode)
                        or any(part.split(".")[0].upper() in {
                            "CON", "PRN", "AUX", "NUL", *[f"COM{i}" for i in range(10)],
                            *[f"LPT{i}" for i in range(10)]} for part in parts)):
                    raise ValueError(f"Chemin non accepté dans le ZIP : {item.filename}")
                key = str(path).casefold()
                if key in seen:
                    raise ValueError(f"Chemin dupliqué dans le ZIP : {item.filename}")
                seen.add(key)
            for item in entries:
                destination = root.joinpath(*PurePosixPath(item.filename.replace("\\", "/")).parts)
                if item.is_dir():
                    destination.mkdir(parents=True, exist_ok=True)
                else:
                    destination.parent.mkdir(parents=True, exist_ok=True)
                    with archive.open(item) as incoming, destination.open("wb") as outgoing:
                        shutil.copyfileobj(incoming, outgoing)
        missions = [file.parent for file in root.rglob("init.c")]
        if len(missions) != 1:
            raise ValueError("Le ZIP doit contenir exactement une mission (init.c). Extrais-le pour choisir le bon dossier.")
        yield prepare_mission_source(missions[0])


def import_source(cfg, source, name="", replace=False, progress=None):
    emit = progress or (lambda *_: None)
    emit(0, 0, "Préparation et validation de la mission…")
    with mission_source(source) as (local_dir, suggested):
        _, template = _validate_map_names(None, name.strip() or suggested)
        files = [p for p in Path(local_dir).rglob("*") if p.is_file()]
        if len(files) > MAX_FILES or sum(p.stat().st_size for p in files) > MAX_BYTES:
            raise ValueError("Mission trop volumineuse (20 000 fichiers / 2 Go).")
        count = 0

        def uploaded(path):
            nonlocal count
            count += 1
            emit(count, len(files), Path(path).name)

        result = connection.import_mission(
            local_dir, f"{mpmissions_path(cfg).rstrip('/')}/{template}", replace, uploaded,
        )
        result["template"] = template
        result["files"] = count
        return result
