"""Mises à jour de DayZ Manager via les releases GitHub.

Le protocole est volontairement sans dépendance externe : API GitHub en HTTPS,
archive ZIP complète, SHA-256 obligatoire et remplacement différé après la
fermeture de l'application.
"""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
import os
from pathlib import Path
import shutil
import stat
import subprocess
import sys
import tempfile
import urllib.error
import urllib.parse
import urllib.request
import zipfile
import re

from packaging.version import InvalidVersion, Version

from version import APP_NAME, APP_VERSION, GITHUB_REPOSITORY, UPDATE_ASSET_NAME


GITHUB_API = "https://api.github.com"
MAX_UPDATE_BYTES = 2 * 1024 * 1024 * 1024
_USER_AGENT = f"{APP_NAME}/{APP_VERSION}"
_SHA256_RE = re.compile(r"\b[a-fA-F0-9]{64}\b")


class UpdateError(RuntimeError):
    """Erreur lisible par l'interface lors d'une mise à jour."""


@dataclass(frozen=True)
class UpdateInfo:
    repository: str
    version: str
    tag_name: str
    release_name: str
    release_url: str
    download_url: str
    asset_name: str
    size_bytes: int
    sha256: str | None
    checksum_url: str | None
    notes: str
    is_newer: bool


@dataclass(frozen=True)
class UpdatePlan:
    """Archive validée et prête à être installée après fermeture de l'UI."""

    temp_root: Path
    staged_dir: Path
    install_dir: Path
    info: UpdateInfo


def normalize_repository(value: str | None) -> str:
    """Normalise ``owner/repository`` ou une URL GitHub en identifiant court."""
    raw = str(value or "").strip().rstrip("/")
    if not raw:
        raise UpdateError(
            "Dépôt GitHub non configuré. Renseigne owner/repository dans À propos."
        )
    if "://" in raw or raw.lower().startswith("github.com/"):
        if "://" not in raw:
            raw = "https://" + raw
        parsed = urllib.parse.urlsplit(raw)
        if parsed.scheme.lower() != "https" or parsed.netloc.lower() != "github.com":
            raise UpdateError("Le dépôt de mise à jour doit être une URL HTTPS GitHub.")
        raw = parsed.path.strip("/")
    raw = raw.removesuffix(".git")
    parts = raw.split("/")
    if len(parts) != 2 or not all(parts):
        raise UpdateError("Dépôt GitHub invalide. Format attendu : owner/repository.")
    if any(part in {".", ".."} for part in parts):
        raise UpdateError("Dépôt GitHub invalide.")
    return "/".join(parts)


def _version(value: str) -> Version:
    text = str(value or "").strip()
    if text[:1].lower() == "v":
        text = text[1:]
    try:
        return Version(text)
    except InvalidVersion as exc:
        raise UpdateError(f"Version GitHub invalide : {value}") from exc


def _request(url: str, timeout: float = 15.0) -> bytes:
    if not url.lower().startswith("https://"):
        raise UpdateError("URL de mise à jour refusée : HTTPS obligatoire.")
    request = urllib.request.Request(
        url,
        headers={
            "Accept": "application/vnd.github+json",
            "User-Agent": _USER_AGENT,
        },
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return response.read()
    except urllib.error.HTTPError as exc:
        if exc.code == 404:
            raise UpdateError("Dépôt GitHub ou release introuvable.") from exc
        if exc.code == 403:
            raise UpdateError("GitHub limite temporairement les vérifications.") from exc
        raise UpdateError(f"GitHub a répondu HTTP {exc.code}.") from exc
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        raise UpdateError(f"GitHub est inaccessible : {exc}") from exc


def _json_request(url: str, timeout: float = 15.0) -> dict:
    try:
        payload = json.loads(_request(url, timeout).decode("utf-8"))
    except json.JSONDecodeError as exc:
        raise UpdateError("Réponse GitHub invalide.") from exc
    if not isinstance(payload, dict):
        raise UpdateError("Réponse GitHub inattendue.")
    return payload


def _select_asset(assets: list[dict], preferred_name: str) -> dict:
    exact = [item for item in assets if item.get("name") == preferred_name]
    if exact:
        return exact[0]
    compatible = [
        item for item in assets
        if str(item.get("name", "")).lower().endswith(".zip")
        and str(item.get("name", "")).lower().startswith("dayzmanager")
    ]
    if len(compatible) == 1:
        return compatible[0]
    raise UpdateError(
        f"La release ne contient pas l'asset {preferred_name}."
    )


def _find_checksum_asset(assets: list[dict], asset_name: str) -> dict | None:
    names = {
        f"{asset_name}.sha256",
        f"{asset_name}.sha256sum",
    }
    for asset in assets:
        if asset.get("name") in names:
            return asset
    return None


def fetch_latest_release(
    repository: str | None = None,
    current_version: str = APP_VERSION,
    asset_name: str = UPDATE_ASSET_NAME,
) -> UpdateInfo:
    """Récupère la release stable et indique si elle est plus récente."""
    repo = normalize_repository(repository or GITHUB_REPOSITORY)
    encoded_repo = urllib.parse.quote(repo, safe="/")
    release = _json_request(f"{GITHUB_API}/repos/{encoded_repo}/releases/latest")
    if release.get("draft") or release.get("prerelease"):
        raise UpdateError("La dernière release GitHub n'est pas stable.")
    tag_name = str(release.get("tag_name") or "").strip()
    remote_version = str(_version(tag_name))
    is_newer = _version(remote_version) > _version(current_version)
    assets = release.get("assets") or []
    if not isinstance(assets, list):
        assets = []
    if not is_newer:
        return UpdateInfo(
            repository=repo,
            version=remote_version,
            tag_name=tag_name,
            release_name=str(release.get("name") or tag_name),
            release_url=str(release.get("html_url") or ""),
            download_url="",
            asset_name=asset_name,
            size_bytes=0,
            sha256=None,
            checksum_url=None,
            notes=str(release.get("body") or ""),
            is_newer=False,
        )

    asset = _select_asset(assets, asset_name)
    download_url = str(asset.get("browser_download_url") or "")
    if not download_url.startswith("https://github.com/"):
        raise UpdateError("URL de téléchargement GitHub invalide.")
    digest = str(asset.get("digest") or "").strip().lower()
    sha256 = digest.removeprefix("sha256:") or None
    if sha256 and not _SHA256_RE.fullmatch(sha256):
        sha256 = None
    checksum_asset = _find_checksum_asset(assets, str(asset.get("name") or asset_name))
    size = int(asset.get("size", 0) or 0)
    if size < 0 or size > MAX_UPDATE_BYTES:
        raise UpdateError("La taille de la mise à jour est excessive ou invalide.")
    return UpdateInfo(
        repository=repo,
        version=remote_version,
        tag_name=tag_name,
        release_name=str(release.get("name") or tag_name),
        release_url=str(release.get("html_url") or ""),
        download_url=download_url,
        asset_name=str(asset.get("name") or asset_name),
        size_bytes=size,
        sha256=sha256,
        checksum_url=(
            str(checksum_asset.get("browser_download_url"))
            if checksum_asset else None
        ),
        notes=str(release.get("body") or ""),
        is_newer=True,
    )


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _checksum_from_asset(url: str) -> str:
    text = _request(url, timeout=15).decode("utf-8", errors="replace")
    match = _SHA256_RE.search(text)
    if not match:
        raise UpdateError("Le fichier SHA-256 de la release est invalide.")
    return match.group(0).lower()


def _download(url: str, destination: Path, expected_size: int = 0) -> None:
    if not url.lower().startswith("https://"):
        raise UpdateError("Téléchargement refusé : HTTPS obligatoire.")
    request = urllib.request.Request(url, headers={"User-Agent": _USER_AGENT})
    total = 0
    try:
        with urllib.request.urlopen(request, timeout=60) as response:
            with destination.open("wb") as stream:
                while True:
                    block = response.read(1024 * 1024)
                    if not block:
                        break
                    total += len(block)
                    if total > MAX_UPDATE_BYTES:
                        raise UpdateError("La mise à jour dépasse la taille maximale autorisée.")
                    stream.write(block)
    except UpdateError:
        raise
    except urllib.error.HTTPError as exc:
        raise UpdateError(f"Téléchargement GitHub HTTP {exc.code}.") from exc
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        raise UpdateError(f"Téléchargement impossible : {exc}") from exc
    if expected_size and total != expected_size:
        raise UpdateError(
            f"Taille téléchargée incohérente ({total} au lieu de {expected_size})."
        )


def _safe_extract(archive: Path, destination: Path) -> None:
    destination = destination.resolve()
    total_size = 0
    with zipfile.ZipFile(archive) as zipped:
        for member in zipped.infolist():
            filename = member.filename.replace("\\", "/")
            parts = Path(filename).parts
            if not filename or Path(filename).is_absolute() or ".." in parts:
                raise UpdateError("Archive de mise à jour non sûre.")
            mode = (member.external_attr >> 16) & 0o170000
            if mode == stat.S_IFLNK:
                raise UpdateError("Archive de mise à jour contenant un lien interdit.")
            target = (destination / Path(*parts)).resolve()
            if os.path.commonpath((str(destination), str(target))) != str(destination):
                raise UpdateError("Archive de mise à jour sortant de son dossier.")
            if member.is_dir():
                target.mkdir(parents=True, exist_ok=True)
                continue
            total_size += int(member.file_size or 0)
            if total_size > MAX_UPDATE_BYTES:
                raise UpdateError("Archive de mise à jour trop volumineuse.")
            target.parent.mkdir(parents=True, exist_ok=True)
            with zipped.open(member, "r") as source, target.open("wb") as stream:
                shutil.copyfileobj(source, stream, length=1024 * 1024)


def _validate_payload(extracted_root: Path, info: UpdateInfo) -> Path:
    candidate = extracted_root / "DayZManager"
    if not candidate.is_dir():
        candidate = extracted_root
    executable = candidate / "DayZManager.exe"
    manifest_path = candidate / "manifest.json"
    if not executable.is_file() or not manifest_path.is_file():
        raise UpdateError("Archive valide mais paquet DayZ Manager incomplet.")
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        packaged_version = str(manifest["version"])
        expected_exe_hash = str(manifest["artifact"]["sha256"]).lower()
    except (OSError, ValueError, KeyError, TypeError) as exc:
        raise UpdateError("Manifeste de mise à jour invalide.") from exc
    if _version(packaged_version) != _version(info.version):
        raise UpdateError("La version du paquet ne correspond pas à la release GitHub.")
    if not _SHA256_RE.fullmatch(expected_exe_hash):
        raise UpdateError("Hash SHA-256 absent du manifeste.")
    if _sha256_file(executable) != expected_exe_hash:
        raise UpdateError("Le hash de l'exécutable ne correspond pas au manifeste.")
    return candidate


def prepare_update(info: UpdateInfo, install_dir: str | Path | None = None) -> UpdatePlan:
    """Télécharge, vérifie et extrait une release sans modifier l'installation."""
    if not info.is_newer:
        raise UpdateError("L'application est déjà à jour.")
    if install_dir is None:
        if not getattr(sys, "frozen", False):
            raise UpdateError(
                "La mise à jour automatique est disponible depuis l'exécutable installé."
            )
        install_path = Path(sys.executable).resolve().parent
    else:
        install_path = Path(install_dir).resolve()
    if not install_path.is_dir():
        raise UpdateError("Dossier d'installation introuvable.")
    if install_path == Path(install_path.anchor) or not (install_path / "DayZManager.exe").is_file():
        raise UpdateError("Le dossier cible ne contient pas une installation DayZ Manager.")

    temp_root = Path(tempfile.mkdtemp(prefix="dayz-manager-update-"))
    archive = temp_root / info.asset_name
    try:
        _download(info.download_url, archive, info.size_bytes)
        expected_hash = info.sha256
        if expected_hash is None and info.checksum_url:
            expected_hash = _checksum_from_asset(info.checksum_url)
        if not expected_hash:
            raise UpdateError("La release ne fournit pas de hash SHA-256 vérifiable.")
        actual_hash = _sha256_file(archive)
        if actual_hash.lower() != expected_hash.lower():
            raise UpdateError("Le hash SHA-256 de la mise à jour est incorrect.")
        extracted_root = temp_root / "payload"
        extracted_root.mkdir()
        _safe_extract(archive, extracted_root)
        staged_dir = _validate_payload(extracted_root, info)
        # Les fichiers locaux ne font pas partie des releases GitHub et sont
        # restaurés par l'installateur différé après le remplacement du paquet.
        preserved_dir = temp_root / "preserved"
        preserved_dir.mkdir()
        for name in ("config.json", "map_profiles.json", "known_hosts"):
            source = install_path / name
            if source.is_file():
                shutil.copy2(source, preserved_dir / name)
        return UpdatePlan(temp_root, staged_dir, install_path, info)
    except Exception:
        shutil.rmtree(temp_root, ignore_errors=True)
        raise


_INSTALL_SCRIPT = r'''param(
    [Parameter(Mandatory=$true)][string]$Target,
    [Parameter(Mandatory=$true)][string]$Staged,
    [Parameter(Mandatory=$true)][string]$Preserved,
    [Parameter(Mandatory=$true)][string]$TempRoot,
    [Parameter(Mandatory=$true)][string]$Executable,
    [Parameter(Mandatory=$true)][string]$ScriptPath,
    [Parameter(Mandatory=$true)][int]$ParentPid
)

$ErrorActionPreference = "Stop"

for ($attempt = 0; $attempt -lt 60; $attempt++) {
    try {
        Get-Process -Id $ParentPid -ErrorAction Stop | Out-Null
        Start-Sleep -Milliseconds 500
    } catch {
        break
    }
}

$Target = [IO.Path]::GetFullPath($Target)
$Staged = [IO.Path]::GetFullPath($Staged)
if ($Target.TrimEnd('\') -eq [IO.Path]::GetPathRoot($Target).TrimEnd('\')) { exit 1 }
if (-not (Test-Path -LiteralPath (Join-Path $Target 'DayZManager.exe'))) { exit 1 }
if (-not (Test-Path -LiteralPath (Join-Path $Staged 'DayZManager.exe'))) { exit 1 }
if (Get-Process -Id $ParentPid -ErrorAction SilentlyContinue) { exit 1 }
$backup = "$Target.__previous-$([guid]::NewGuid().ToString('N'))"
$movedOld = $false
$installedNew = $false
try {
    Move-Item -LiteralPath $Target -Destination $backup
    $movedOld = $true
    Move-Item -LiteralPath $Staged -Destination $Target
    $installedNew = $true

    foreach ($name in @("config.json", "map_profiles.json", "known_hosts")) {
        $oldData = Join-Path $backup $name
        if (Test-Path -LiteralPath $oldData) {
            Copy-Item -LiteralPath $oldData -Destination (Join-Path $Target $name) -Force
        }
    }

    if (-not (Test-Path -LiteralPath $Executable)) {
        throw "Exécutable absent après installation."
    }
    Start-Process -FilePath $Executable -WorkingDirectory $Target
} catch {
    try {
        if ($installedNew -and (Test-Path -LiteralPath $Target)) {
            Move-Item -LiteralPath $Target -Destination "$Target.__failed-$([guid]::NewGuid().ToString('N'))"
        }
    } catch {}
    try {
        if ($movedOld -and (Test-Path -LiteralPath $backup)) {
            Move-Item -LiteralPath $backup -Destination $Target
        }
    } catch {}
    exit 1
}

try { Remove-Item -LiteralPath $TempRoot -Recurse -Force } catch {}
try { Remove-Item -LiteralPath $ScriptPath -Force } catch {}
exit 0
'''


def launch_update(plan: UpdatePlan) -> Path:
    """Lance l'installateur PowerShell puis rend la main à l'interface."""
    if sys.platform != "win32":
        raise UpdateError("L'installation automatique est disponible sous Windows.")
    script_path = plan.temp_root / "install-update.ps1"
    script_path.write_text(_INSTALL_SCRIPT, encoding="utf-8")
    powershell = Path(os.environ.get("WINDIR", r"C:\Windows")) / (
        "System32/WindowsPowerShell/v1.0/powershell.exe"
    )
    if not powershell.is_file():
        raise UpdateError("PowerShell Windows est introuvable.")
    executable = plan.install_dir / "DayZManager.exe"
    preserved_dir = plan.temp_root / "preserved"
    args = [
        str(powershell),
        "-NoProfile",
        "-NonInteractive",
        "-ExecutionPolicy",
        "Bypass",
        "-File",
        str(script_path),
        "-Target",
        str(plan.install_dir),
        "-Staged",
        str(plan.staged_dir),
        "-Preserved",
        str(preserved_dir),
        "-TempRoot",
        str(plan.temp_root),
        "-Executable",
        str(executable),
        "-ScriptPath",
        str(script_path),
        "-ParentPid",
        str(os.getpid()),
    ]
    try:
        subprocess.Popen(
            args,
            cwd=str(plan.temp_root),
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
    except OSError as exc:
        raise UpdateError(f"Installateur impossible à lancer : {exc}") from exc
    return script_path
