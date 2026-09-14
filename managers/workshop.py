"""Client de l'API Web Steam pour parcourir le Workshop DayZ.

- ``search``  : liste/recherche d'objets Workshop (nécessite une clé API
  Steam gratuite — https://steamcommunity.com/dev/apikey).
- ``get_details`` : détails d'IDs précis, SANS clé.
- ``download_image`` : récupère une vignette de prévisualisation.

On utilise ``urllib`` (bibliothèque standard) pour éviter toute nouvelle
dépendance.
"""

import json
import urllib.parse
import urllib.request

DAYZ_APP_ID = "221100"

_USER_AGENT = "DayZManager/0.3 (+workshop-browser)"
_TIMEOUT = 15

# Types de tri Steam (k_PublishedFileQueryType_*)
_QUERY_TEXT = 11               # RankedByTextSearch
_QUERY_POPULAR = 12            # RankedByTotalUniqueSubscriptions


class WorkshopError(Exception):
    """Erreur réseau / API lisible côté UI."""


def _get(url, params):
    full = url + "?" + urllib.parse.urlencode(params, doseq=True)
    req = urllib.request.Request(full, headers={"User-Agent": _USER_AGENT})
    try:
        with urllib.request.urlopen(req, timeout=_TIMEOUT) as resp:
            return json.loads(resp.read().decode("utf-8", errors="ignore"))
    except urllib.error.HTTPError as exc:
        if exc.code in (401, 403):
            raise WorkshopError("Clé API Steam invalide ou refusée.")
        raise WorkshopError(f"Erreur HTTP {exc.code}.")
    except Exception as exc:
        raise WorkshopError(f"Réseau indisponible : {exc}")


def _post(url, params):
    data = urllib.parse.urlencode(params, doseq=True).encode()
    req = urllib.request.Request(url, data=data, headers={"User-Agent": _USER_AGENT})
    try:
        with urllib.request.urlopen(req, timeout=_TIMEOUT) as resp:
            return json.loads(resp.read().decode("utf-8", errors="ignore"))
    except Exception as exc:
        raise WorkshopError(f"Réseau indisponible : {exc}")


def _normalize(item):
    """Transforme un objet brut de l'API en dict simple pour l'UI."""
    tags = [t.get("tag", "") for t in (item.get("tags") or []) if t.get("tag")]
    try:
        size = int(item.get("file_size", 0) or 0)
    except (TypeError, ValueError):
        size = 0
    subs = (
        item.get("subscriptions")
        or item.get("lifetime_subscriptions")
        or item.get("favorited")
        or 0
    )
    return {
        "id": str(item.get("publishedfileid", "")),
        "title": item.get("title", "(sans titre)"),
        "description": (item.get("short_description") or item.get("file_description") or "").strip(),
        "preview_url": item.get("preview_url", ""),
        "size_mb": round(size / (1024 * 1024), 1) if size else 0,
        "subscriptions": int(subs or 0),
        "tags": tags,
    }


def search(api_key, query="", page=1, per_page=20, maps_only=False):
    """Recherche dans le Workshop DayZ. Renvoie (items, total)."""
    if not api_key:
        raise WorkshopError(
            "Clé API Steam manquante. Renseigne-la dans Réglages "
            "(https://steamcommunity.com/dev/apikey)."
        )

    params = {
        "key": api_key,
        "appid": DAYZ_APP_ID,
        "query_type": _QUERY_TEXT if query.strip() else _QUERY_POPULAR,
        "page": max(1, int(page)),
        "numperpage": per_page,
        "search_text": query.strip(),
        "return_details": "true",
        "return_tags": "true",
        "return_previews": "true",
        "return_short_description": "true",
        "return_vote_data": "true",
    }
    if maps_only:
        # Tag officiel DayZ pour les cartes : c'est « Terrain » dans le
        # Workshop (et non « Map »), sinon la recherche ne renvoie rien.
        params["requiredtags[0]"] = "Terrain"

    payload = _get(
        "https://api.steampowered.com/IPublishedFileService/QueryFiles/v1/", params
    )
    response = payload.get("response", {})
    raw = response.get("publishedfiledetails", []) or []
    total = int(response.get("total", len(raw)) or 0)
    items = [_normalize(it) for it in raw if it.get("publishedfileid")]
    return items, total


def get_collection(collection_id):
    """Résout une collection Workshop en liste d'IDs enfants (sans clé API)."""
    collection_id = str(collection_id).strip()
    if not collection_id:
        return []
    params = {
        "collectioncount": 1,
        "publishedfileids[0]": collection_id,
    }
    payload = _post(
        "https://api.steampowered.com/ISteamRemoteStorage/GetCollectionDetails/v1/",
        params,
    )
    details = payload.get("response", {}).get("collectiondetails", []) or []
    if not details:
        return []
    children = details[0].get("children", []) or []
    # filetype 2 = sous-collection ; on ne garde que les mods (filetype 0).
    ids = [
        str(c.get("publishedfileid"))
        for c in children
        if c.get("publishedfileid") and int(c.get("filetype", 0) or 0) != 2
    ]
    return ids


def get_details(ids):
    """Détails d'IDs précis (sans clé API). Renvoie une liste de dicts."""
    ids = [str(i) for i in ids if str(i).strip()]
    if not ids:
        return []
    params = {"itemcount": len(ids)}
    for i, mod_id in enumerate(ids):
        params[f"publishedfileids[{i}]"] = mod_id
    payload = _post(
        "https://api.steampowered.com/ISteamRemoteStorage/GetPublishedFileDetails/v1/",
        params,
    )
    raw = payload.get("response", {}).get("publishedfiledetails", []) or []
    return [_normalize(it) for it in raw if it.get("publishedfileid")]


def get_update_times(ids):
    """Renvoie {id: {"time_updated": epoch, "title": str}} (sans clé API).

    ``time_updated`` est la date de dernière publication de l'item sur le
    Workshop ; on la compare au mtime local pour détecter les MAJ.
    """
    ids = [str(i) for i in ids if str(i).strip()]
    if not ids:
        return {}
    params = {"itemcount": len(ids)}
    for i, mod_id in enumerate(ids):
        params[f"publishedfileids[{i}]"] = mod_id
    payload = _post(
        "https://api.steampowered.com/ISteamRemoteStorage/GetPublishedFileDetails/v1/",
        params,
    )
    raw = payload.get("response", {}).get("publishedfiledetails", []) or []
    result = {}
    for it in raw:
        pid = str(it.get("publishedfileid", ""))
        if not pid:
            continue
        try:
            t = int(it.get("time_updated", 0) or 0)
        except (TypeError, ValueError):
            t = 0
        result[pid] = {"time_updated": t, "title": it.get("title", "")}
    return result


def download_image(url):
    """Télécharge une image (vignette) et renvoie ses octets, ou None."""
    if not url:
        return None
    req = urllib.request.Request(url, headers={"User-Agent": _USER_AGENT})
    try:
        with urllib.request.urlopen(req, timeout=_TIMEOUT) as resp:
            return resp.read()
    except Exception:
        return None
