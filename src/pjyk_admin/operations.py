"""Management operations shared by the command line and MCP server."""
import json
from datetime import date
from typing import Any, Dict, List, Literal, Optional

from pjyk_admin.client import AdminApiClient, AdminApiError

Season = Literal["WINTER", "SPRING", "SUMMER", "FALL"]
ReviewStatus = Literal["PENDING", "APPROVED", "REJECTED"]
StatusFilter = Literal["PENDING", "APPROVED", "REJECTED", "ALL"]
Platform = Literal["Bangumi", "AniList", "MyAnimeList"]
TaskName = Literal["anime-fetch", "mapping-fetch", "mapping-link", "metric-recalculation"]


def _compact_titles(title_obj: Optional[Dict[str, Any]]) -> Dict[str, Optional[str]]:
    if not title_obj:
        return {"cn": None, "native": None, "romaji": None, "en": None}
    return {
        "cn": title_obj.get("titleCn"),
        "native": title_obj.get("titleNative"),
        "romaji": title_obj.get("titleRomaji"),
        "en": title_obj.get("titleEn"),
    }


def _compact_mapping(m: Dict[str, Any], include_cover: bool = False) -> dict[str, Any]:
    pk = m.get("platformKey") or {}
    info = m.get("mappingInfo") or {}
    item: Dict[str, Any] = {
        "mappingId": m.get("mappingId"),
        "animeId": m.get("animeId"),
        "platform": pk.get("platform"),
        "platformId": pk.get("platformId"),
        "rawScore": m.get("rawScore"),
        "startDate": info.get("startDate"),
        "title": _compact_titles(info.get("title")),
    }
    if include_cover:
        item["coverImage"] = info.get("coverImage")
    return item


def _compact_anime(a: Dict[str, Any], include_cover: bool = False) -> dict[str, Any]:
    mappings = a.get("mappings") or []
    item: Dict[str, Any] = {
        "animeId": a.get("animeId"),
        "reviewStatus": a.get("reviewStatus"),
        "startDate": a.get("startDate"),
        "averageScore": a.get("averageScore"),
        "title": _compact_titles(a.get("title")),
        "mappings": [_compact_mapping(m, include_cover=include_cover) for m in mappings],
    }
    if include_cover:
        item["coverImage"] = a.get("coverImage")
    return item


def _matches_keyword(item_dict: Dict[str, Any], keyword: str) -> bool:
    kw = keyword.lower().strip()
    if not kw:
        return True
    raw_text = json.dumps(item_dict, ensure_ascii=False).lower()
    return kw in raw_text


TITLE_FIELDS = {
    "titleCn": ("titleCn", "cn", "title_cn"),
    "titleNative": ("titleNative", "native", "title_native"),
    "titleRomaji": ("titleRomaji", "romaji", "title_romaji"),
    "titleEn": ("titleEn", "en", "title_en"),
}


def _build_title_payload(
    existing_title: Optional[Dict[str, Any]],
    new_fields: Dict[str, Any],
) -> Optional[Dict[str, Optional[str]]]:
    """Merge partial title updates into a complete AnimeTitles object so existing fields aren't wiped."""
    has_any_update = False
    updates: Dict[str, Optional[str]] = {}
    for canonical, aliases in TITLE_FIELDS.items():
        for alias in aliases:
            if alias in new_fields and new_fields[alias] is not None:
                updates[canonical] = new_fields[alias]
                has_any_update = True
                break

    if not has_any_update:
        return None

    base = existing_title or {}
    return {
        "titleCn": updates.get("titleCn", base.get("titleCn")),
        "titleNative": updates.get("titleNative", base.get("titleNative")),
        "titleRomaji": updates.get("titleRomaji", base.get("titleRomaji")),
        "titleEn": updates.get("titleEn", base.get("titleEn")),
    }


def _find_anime_by_id(client: AdminApiClient, anime_id: int) -> Optional[Dict[str, Any]]:
    for a in client.list_animes():
        if a.get("animeId") == anime_id:
            return a
    return None


def _execute_merge_animes(
    client: AdminApiClient,
    target_anime_id: int,
    source_anime_id: int,
    delete_source: bool = True,
    progress: Optional[Dict[str, Any]] = None,
) -> dict[str, Any]:
    if target_anime_id == source_anime_id:
        raise AdminApiError(f"targetAnimeId and sourceAnimeId cannot be identical ({target_anime_id})")

    animes = {anime["animeId"]: anime for anime in client.list_animes()}
    if target_anime_id not in animes:
        raise AdminApiError(f"Target Anime {target_anime_id} not found")
    if source_anime_id not in animes:
        raise AdminApiError(f"Source Anime {source_anime_id} not found")

    mapping_ids = [int(m["mappingId"]) for m in animes[source_anime_id].get("mappings") or []]
    result = progress if progress is not None else {}
    moved: List[int] = []
    result.update(
        targetAnimeId=target_anime_id,
        sourceAnimeId=source_anime_id,
        movedMappingIds=moved,
        sourceDeleted=False,
    )
    for mapping_id in mapping_ids:
        client.update_mapping_anime(mapping_id, target_anime_id)
        moved.append(mapping_id)

    if delete_source:
        client.delete_anime(source_anime_id)
        result["sourceDeleted"] = True
    return result


ACTION_FIELDS = {
    "link_mapping": ("mappingId", "animeId"),
    "merge_animes": ("targetAnimeId", "sourceAnimeId"),
    "update_anime": ("animeId",),
    "delete_anime": ("animeId",),
    "create_anime": (),
    "create_mapping": ("platform", "platformId"),
    "delete_mapping": ("mappingId",),
}

TITLE_KEYS = {key for aliases in TITLE_FIELDS.values() for key in aliases}
ANIME_FIELDS = TITLE_KEYS | {"title", "startDate", "coverImage"}
OPTIONAL_FIELDS = {
    "merge_animes": {"deleteSource"},
    "update_anime": ANIME_FIELDS | {"status", "reviewStatus"},
    "create_anime": ANIME_FIELDS | {"mappingIds"},
    "create_mapping": {"animeId"},
}


def _validate_id(value: Any, field: str) -> None:
    if type(value) is int or isinstance(value, str) and value.strip().isdecimal():
        if 0 < int(value) <= 2**63 - 1:
            return
    raise ValueError(f"{field} must be a positive integer ID")


def _validate_action(action: Any) -> str:
    if not isinstance(action, dict):
        raise ValueError("expected an action object")
    op = action.get("op") or action.get("action") or action.get("type")
    if not isinstance(op, str) or op not in ACTION_FIELDS:
        raise ValueError(f"Unsupported operation '{op}'")
    required = set(ACTION_FIELDS[op])
    missing = required - action.keys()
    if missing:
        raise ValueError(f"Missing fields: {', '.join(sorted(missing))}")
    unknown = action.keys() - required - OPTIONAL_FIELDS.get(op, set()) - {"op", "type", "action", "reason"}
    if unknown:
        raise ValueError(f"Unknown fields: {', '.join(sorted(unknown))}")

    for field in ("mappingId", "animeId", "targetAnimeId", "sourceAnimeId"):
        if field in action:
            if field == "animeId" and op in ("link_mapping", "create_mapping") and action[field] is None:
                continue
            _validate_id(action[field], field)
    if op == "merge_animes":
        if not isinstance(action.get("deleteSource", True), bool):
            raise ValueError("deleteSource must be a JSON boolean")
        if int(action["targetAnimeId"]) == int(action["sourceAnimeId"]):
            raise ValueError("targetAnimeId and sourceAnimeId cannot be identical")
    if op == "create_mapping":
        if action["platform"] not in ("Bangumi", "AniList", "MyAnimeList"):
            raise ValueError("Unknown platform")
        if type(action["platformId"]) not in (str, int) or not str(action["platformId"]).strip():
            raise ValueError("platformId must be a non-empty string or integer")
    if "mappingIds" in action:
        if not isinstance(action["mappingIds"], list):
            raise ValueError("mappingIds must be an array")
        for mid in action["mappingIds"]:
            _validate_id(mid, "mappingIds")
    if "title" in action:
        if not isinstance(action["title"], dict) or action["title"].keys() - TITLE_KEYS:
            raise ValueError("title must be an object with supported title fields")
    titles = action.get("title", action)
    for field in TITLE_KEYS.intersection(titles):
        if titles[field] is not None and not isinstance(titles[field], str):
            raise ValueError(f"{field} must be a string")
    if action.get("coverImage") is not None and not isinstance(action["coverImage"], str):
        raise ValueError("coverImage must be a string")
    if action.get("startDate") is not None:
        value = action["startDate"]
        if not isinstance(value, str) or date.fromisoformat(value).isoformat() != value:
            raise ValueError("startDate must use YYYY-MM-DD")
    status = action.get("reviewStatus") or action.get("status")
    if status is not None and status not in ("PENDING", "APPROVED", "REJECTED"):
        raise ValueError("Invalid review status")
    return op


def _apply_action(client: AdminApiClient, op: str, action: Dict[str, Any], result: Dict[str, Any]) -> None:
    if op == "link_mapping":
        mid = int(action["mappingId"])
        target = action["animeId"]
        updated = client.update_mapping_anime(mid, int(target) if target is not None else None)
        result.update(mappingId=mid, animeId=updated.get("animeId"))
    elif op == "merge_animes":
        _execute_merge_animes(
            client,
            target_anime_id=int(action["targetAnimeId"]),
            source_anime_id=int(action["sourceAnimeId"]),
            delete_source=action.get("deleteSource", True),
            progress=result,
        )
    elif op == "update_anime":
        anime_id = int(action["animeId"])
        titles = action.get("title", action)
        payload = None
        if TITLE_KEYS.intersection(titles):
            existing = _find_anime_by_id(client, anime_id)
            if existing is None:
                raise AdminApiError(f"Anime {anime_id} not found")
            payload = _build_title_payload(existing.get("title"), titles)
        updated = client.update_anime(
            anime_id,
            title=payload,
            cover_image=action.get("coverImage"),
            review_status=action.get("reviewStatus") or action.get("status"),
            start_date=action.get("startDate"),
        )
        result.update(animeId=anime_id, reviewStatus=updated.get("reviewStatus"),
                      title=_compact_titles(updated.get("title")))
    elif op == "create_anime":
        created = client.create_anime(
            title=_build_title_payload(None, action.get("title", action)),
            cover_image=action.get("coverImage"),
            start_date=action.get("startDate"),
        )
        anime_id = created["animeId"]
        linked: List[int] = []
        result.update(animeId=anime_id, linkedMappingIds=linked)
        for mid in action.get("mappingIds", []):
            client.update_mapping_anime(int(mid), anime_id)
            linked.append(int(mid))
    elif op == "create_mapping":
        platform = action["platform"]
        platform_id = str(action["platformId"])
        created = client.create_mapping(platform, platform_id)
        mid = created["mappingId"]
        result.update(mappingId=mid, platform=platform, platformId=platform_id, animeId=created.get("animeId"))
        if action.get("animeId") is not None:
            target = int(action["animeId"])
            client.update_mapping_anime(mid, target)
            result["animeId"] = target
    elif op == "delete_mapping":
        mid = int(action["mappingId"])
        client.delete_mapping(mid)
        result["mappingId"] = mid
    elif op == "delete_anime":
        anime_id = int(action["animeId"])
        client.delete_anime(anime_id)
        result["animeId"] = anime_id


class AdminOperations:
    def __init__(self, client: AdminApiClient):
        self.client = client

    def status(
        self,
        year: Optional[int] = None,
        season: Optional[Season] = None,
    ) -> dict[str, Any]:
        """Count anime by review status and report the global unlinked mapping count."""
        pending = self.client.list_animes(review_status="PENDING", year=year, season=season)
        approved = self.client.list_animes(review_status="APPROVED", year=year, season=season)
        rejected = self.client.list_animes(review_status="REJECTED", year=year, season=season)
        unlinked = self.client.list_unlinked_mappings()

        result = {
            "filter": {"year": year, "season": season},
            "animes": {
                "PENDING": len(pending),
                "APPROVED": len(approved),
                "REJECTED": len(rejected),
                "total": len(pending) + len(approved) + len(rejected),
            },
            "unlinkedMappingsCount": len(unlinked),
        }
        return result

    def dump(
        self,
        status: StatusFilter = "PENDING",
        year: Optional[int] = None,
        season: Optional[Season] = None,
        keyword: Optional[str] = None,
        no_unlinked: bool = False,
        include_cover: bool = False,
    ) -> dict[str, Any]:
        """Export compact anime and unlinked mapping data for inspection."""
        status_filter = None if status == "ALL" else status
        animes = self.client.list_animes(
            review_status=status_filter,
            year=year,
            season=season,
        )
        compact_animes = [_compact_anime(a, include_cover=include_cover) for a in animes]
        if keyword:
            compact_animes = [a for a in compact_animes if _matches_keyword(a, keyword)]

        result: Dict[str, Any] = {
            "filter": {
                "status": status,
                "year": year,
                "season": season,
                "keyword": keyword,
            },
            "animeCount": len(compact_animes),
            "animes": compact_animes,
        }

        if not no_unlinked:
            unlinked = self.client.list_unlinked_mappings()
            compact_unlinked = [
                _compact_mapping(m, include_cover=include_cover) for m in unlinked
            ]
            if keyword:
                compact_unlinked = [
                    m for m in compact_unlinked if _matches_keyword(m, keyword)
                ]
            result["unlinkedMappingCount"] = len(compact_unlinked)
            result["unlinkedMappings"] = compact_unlinked

        return result

    def animes(
        self,
        status: StatusFilter = "PENDING",
        year: Optional[int] = None,
        season: Optional[Season] = None,
        keyword: Optional[str] = None,
        include_cover: bool = False,
    ) -> dict[str, Any]:
        """List compact anime records by status, year, season or keyword."""
        status_filter = None if status == "ALL" else status
        animes = self.client.list_animes(
            review_status=status_filter,
            year=year,
            season=season,
        )
        items = [_compact_anime(a, include_cover=include_cover) for a in animes]
        if keyword:
            items = [a for a in items if _matches_keyword(a, keyword)]
        return {"count": len(items), "animes": items}

    def unlinked(
        self,
        keyword: Optional[str] = None,
        include_cover: bool = False,
    ) -> dict[str, Any]:
        """List unlinked platform mappings, optionally filtered by keyword."""
        unlinked = self.client.list_unlinked_mappings()
        items = [_compact_mapping(m, include_cover=include_cover) for m in unlinked]
        if keyword:
            items = [m for m in items if _matches_keyword(m, keyword)]
        return {"count": len(items), "unlinkedMappings": items}

    def update_anime(
        self,
        anime_id: int,
        status: Optional[ReviewStatus] = None,
        title_cn: Optional[str] = None,
        title_native: Optional[str] = None,
        title_romaji: Optional[str] = None,
        title_en: Optional[str] = None,
        start_date: Optional[str] = None,
        cover_image: Optional[str] = None,
    ) -> dict[str, Any]:
        """Update anime metadata or review status. Omitted title fields retain their values."""
        title_input = {
            "titleCn": title_cn,
            "titleNative": title_native,
            "titleRomaji": title_romaji,
            "titleEn": title_en,
        }
        title_payload: Optional[Dict[str, Optional[str]]] = None
        if any(v is not None for v in title_input.values()):
            existing = _find_anime_by_id(self.client, anime_id)
            if not existing:
                raise AdminApiError(f"Anime {anime_id} not found")
            title_payload = _build_title_payload(existing.get("title"), title_input)

        updated = self.client.update_anime(
            anime_id=anime_id,
            title=title_payload,
            cover_image=cover_image,
            review_status=status,
            start_date=start_date,
        )
        return _compact_anime(updated, include_cover=True)

    def link_mapping(
        self,
        mapping_id: int,
        anime_id: Optional[int] = None,
        unlink: bool = False,
    ) -> dict[str, Any]:
        """Link to anime_id, or explicitly set unlink=true to remove the existing link."""
        if unlink == (anime_id is not None):
            raise AdminApiError("Specify either anime_id or unlink=true")
        target_id = None if unlink else anime_id
        updated = self.client.update_mapping_anime(mapping_id, target_id)
        return _compact_mapping(updated, include_cover=True)

    def merge_anime(
        self,
        target_anime_id: int,
        source_anime_id: int,
        keep_source: bool = False,
    ) -> dict[str, Any]:
        """Move source mappings to the target and delete the source unless keep_source is true."""
        return _execute_merge_animes(
            self.client,
            target_anime_id=target_anime_id,
            source_anime_id=source_anime_id,
            delete_source=not keep_source,
        )

    def apply(
        self,
        actions: List[Dict[str, Any]],
        dry_run: bool = False,
        fail_fast: bool = False,
    ) -> dict[str, Any]:
        """Validate and execute an ordered batch. Set dry_run=true for local validation. Writes before a failure persist."""
        operations = []
        for idx, action in enumerate(actions):
            try:
                operations.append(_validate_action(action))
            except ValueError as exc:
                raise AdminApiError(f"Invalid action at index {idx}: {exc}") from exc

        if dry_run:
            return {"dryRun": True, "totalActions": len(actions), "actions": actions}

        results: List[Dict[str, Any]] = []
        succeeded = 0
        failed = 0

        for idx, (op, action) in enumerate(zip(operations, actions)):
            result = {"index": idx, "op": op, "reason": action.get("reason")}
            results.append(result)
            try:
                _apply_action(self.client, op, action, result)
                result["success"] = True
                succeeded += 1
            except Exception as exc:
                result.update(success=False, error=str(exc), action=action)
                failed += 1
                if fail_fast:
                    break

        return {
            "totalActions": len(actions),
            "succeeded": succeeded,
            "failed": failed,
            "results": results,
        }

    def task(
        self,
        task_name: TaskName,
        year: Optional[int] = None,
        season: Optional[Season] = None,
        platform: Optional[Platform] = None,
    ) -> dict[str, Any]:
        """Trigger a backend task. Fetch tasks require a year."""
        if task_name in ("anime-fetch", "mapping-fetch") and not year:
            raise AdminApiError(f"--year is required for task '{task_name}'")

        if task_name == "anime-fetch":
            msg = self.client.trigger_anime_fetch(year=year, season=season, platform=platform)
        elif task_name == "mapping-fetch":
            msg = self.client.trigger_mapping_fetch(
                year=year, season=season, platform=platform
            )
        elif task_name == "mapping-link":
            msg = self.client.trigger_mapping_link()
        elif task_name == "metric-recalculation":
            msg = self.client.trigger_metric_recalculation()
        else:
            raise AdminApiError(f"Unknown task: {task_name}")

        return {"task": task_name, "message": msg}
