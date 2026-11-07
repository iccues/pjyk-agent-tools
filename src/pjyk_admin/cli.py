from __future__ import annotations

import argparse
import json
import sys
from datetime import date
from pathlib import Path
from typing import Any, Dict, List, Optional

from pjyk_admin.client import AdminApiClient, AdminApiError


def _print_json(data: Any, pretty: bool = False) -> None:
    if pretty:
        print(json.dumps(data, ensure_ascii=False, indent=2))
    else:
        print(json.dumps(data, ensure_ascii=False))


def _compact_titles(title_obj: Optional[Dict[str, Any]]) -> Dict[str, Optional[str]]:
    if not title_obj:
        return {"cn": None, "native": None, "romaji": None, "en": None}
    return {
        "cn": title_obj.get("titleCn"),
        "native": title_obj.get("titleNative"),
        "romaji": title_obj.get("titleRomaji"),
        "en": title_obj.get("titleEn"),
    }


def _compact_mapping(m: Dict[str, Any], include_cover: bool = False) -> Dict[str, Any]:
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


def _compact_anime(a: Dict[str, Any], include_cover: bool = False) -> Dict[str, Any]:
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


def cmd_status(client: AdminApiClient, args: argparse.Namespace) -> None:
    pending = client.list_animes(review_status="PENDING", year=args.year, season=args.season)
    approved = client.list_animes(review_status="APPROVED", year=args.year, season=args.season)
    rejected = client.list_animes(review_status="REJECTED", year=args.year, season=args.season)
    unlinked = client.list_unlinked_mappings()

    result = {
        "filter": {"year": args.year, "season": args.season},
        "animes": {
            "PENDING": len(pending),
            "APPROVED": len(approved),
            "REJECTED": len(rejected),
            "total": len(pending) + len(approved) + len(rejected),
        },
        "unlinkedMappingsCount": len(unlinked),
    }
    _print_json(result, pretty=args.pretty)


def cmd_dump(client: AdminApiClient, args: argparse.Namespace) -> None:
    status_filter = None if args.status == "ALL" else args.status
    animes = client.list_animes(
        review_status=status_filter,
        year=args.year,
        season=args.season,
    )
    compact_animes = [_compact_anime(a, include_cover=args.include_cover) for a in animes]
    if args.keyword:
        compact_animes = [a for a in compact_animes if _matches_keyword(a, args.keyword)]

    result: Dict[str, Any] = {
        "filter": {
            "status": args.status,
            "year": args.year,
            "season": args.season,
            "keyword": args.keyword,
        },
        "animeCount": len(compact_animes),
        "animes": compact_animes,
    }

    if not args.no_unlinked:
        unlinked = client.list_unlinked_mappings()
        compact_unlinked = [
            _compact_mapping(m, include_cover=args.include_cover) for m in unlinked
        ]
        if args.keyword:
            compact_unlinked = [
                m for m in compact_unlinked if _matches_keyword(m, args.keyword)
            ]
        result["unlinkedMappingCount"] = len(compact_unlinked)
        result["unlinkedMappings"] = compact_unlinked

    _print_json(result, pretty=args.pretty)


def cmd_animes(client: AdminApiClient, args: argparse.Namespace) -> None:
    status_filter = None if args.status == "ALL" else args.status
    animes = client.list_animes(
        review_status=status_filter,
        year=args.year,
        season=args.season,
    )
    items = [_compact_anime(a, include_cover=args.include_cover) for a in animes]
    if args.keyword:
        items = [a for a in items if _matches_keyword(a, args.keyword)]
    _print_json({"count": len(items), "animes": items}, pretty=args.pretty)


def cmd_unlinked(client: AdminApiClient, args: argparse.Namespace) -> None:
    unlinked = client.list_unlinked_mappings()
    items = [_compact_mapping(m, include_cover=args.include_cover) for m in unlinked]
    if args.keyword:
        items = [m for m in items if _matches_keyword(m, args.keyword)]
    _print_json({"count": len(items), "unlinkedMappings": items}, pretty=args.pretty)


def _execute_merge_animes(
    client: AdminApiClient,
    target_anime_id: int,
    source_anime_id: int,
    delete_source: bool = True,
    progress: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
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


def cmd_update_anime(client: AdminApiClient, args: argparse.Namespace) -> None:
    title_input = {
        "titleCn": args.title_cn,
        "titleNative": args.title_native,
        "titleRomaji": args.title_romaji,
        "titleEn": args.title_en,
    }
    title_payload: Optional[Dict[str, Optional[str]]] = None
    if any(v is not None for v in title_input.values()):
        existing = _find_anime_by_id(client, args.anime_id)
        if not existing:
            raise AdminApiError(f"Anime {args.anime_id} not found")
        title_payload = _build_title_payload(existing.get("title"), title_input)

    updated = client.update_anime(
        anime_id=args.anime_id,
        title=title_payload,
        cover_image=args.cover_image,
        review_status=args.status,
        start_date=args.start_date,
    )
    _print_json(_compact_anime(updated, include_cover=True), pretty=args.pretty)


def cmd_link_mapping(client: AdminApiClient, args: argparse.Namespace) -> None:
    target_id = None if args.unlink else args.anime_id
    updated = client.update_mapping_anime(args.mapping_id, target_id)
    _print_json(_compact_mapping(updated, include_cover=True), pretty=args.pretty)


def cmd_merge_anime(client: AdminApiClient, args: argparse.Namespace) -> None:
    res = _execute_merge_animes(
        client,
        target_anime_id=args.target_anime_id,
        source_anime_id=args.source_anime_id,
        delete_source=not args.keep_source,
    )
    _print_json(res, pretty=args.pretty)


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


def cmd_apply(client: AdminApiClient, args: argparse.Namespace) -> None:
    plan_path = Path(args.file)
    if not plan_path.is_file():
        raise AdminApiError(f"Batch plan file not found: {plan_path}")

    try:
        raw_plan = json.loads(plan_path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise AdminApiError(f"Cannot read batch plan {plan_path}: {exc}") from exc
    if isinstance(raw_plan, list):
        actions = raw_plan
    elif isinstance(raw_plan, dict) and isinstance(raw_plan.get("actions"), list):
        actions = raw_plan["actions"]
    else:
        raise AdminApiError(
            "Invalid plan JSON format: expected a list of actions or an object with an 'actions' array."
        )

    operations = []
    for idx, action in enumerate(actions):
        try:
            operations.append(_validate_action(action))
        except ValueError as exc:
            raise AdminApiError(f"Invalid action at index {idx}: {exc}") from exc

    if args.dry_run:
        _print_json(
            {
                "dryRun": True,
                "totalActions": len(actions),
                "actions": actions,
            },
            pretty=args.pretty,
        )
        return

    results: List[Dict[str, Any]] = []
    succeeded = 0
    failed = 0

    for idx, (op, action) in enumerate(zip(operations, actions)):
        result = {"index": idx, "op": op, "reason": action.get("reason")}
        results.append(result)
        try:
            _apply_action(client, op, action, result)
            result["success"] = True
            succeeded += 1
        except Exception as exc:
            result.update(success=False, error=str(exc), action=action)
            failed += 1
            if args.fail_fast:
                break

    summary = {
        "totalActions": len(actions),
        "succeeded": succeeded,
        "failed": failed,
        "results": results,
    }
    _print_json(summary, pretty=args.pretty)
    if failed > 0:
        sys.exit(1)


def cmd_task(client: AdminApiClient, args: argparse.Namespace) -> None:
    if args.task_name in ("anime-fetch", "mapping-fetch") and not args.year:
        raise AdminApiError(f"--year is required for task '{args.task_name}'")

    if args.task_name == "anime-fetch":
        msg = client.trigger_anime_fetch(year=args.year, season=args.season, platform=args.platform)
    elif args.task_name == "mapping-fetch":
        msg = client.trigger_mapping_fetch(
            year=args.year, season=args.season, platform=args.platform
        )
    elif args.task_name == "mapping-link":
        msg = client.trigger_mapping_link()
    elif args.task_name == "metric-recalculation":
        msg = client.trigger_metric_recalculation()
    else:
        raise AdminApiError(f"Unknown task: {args.task_name}")

    _print_json({"task": args.task_name, "message": msg}, pretty=args.pretty)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="pjyk-admin",
        description="Project Yuki Admin CLI for AI-assisted anime & mapping management.",
    )
    parser.add_argument(
        "--base-url",
        default=None,
        help="Admin API base URL (default: PJYK_ADMIN_BASE_URL or http://localhost:8080)",
    )
    parser.add_argument(
        "--token",
        default=None,
        help="Optional OIDC Bearer token (default: PJYK_ADMIN_TOKEN)",
    )
    parser.add_argument(
        "--pretty",
        action="store_true",
        help="Pretty-print JSON output with indentation",
    )

    subparsers = parser.add_subparsers(dest="subcommand", required=True)

    # status
    p_status = subparsers.add_parser("status", help="Show counts of animes and unlinked mappings")
    p_status.add_argument("--year", type=int, default=None, help="Filter anime counts by year")
    p_status.add_argument(
        "--season",
        choices=["WINTER", "SPRING", "SUMMER", "FALL"],
        default=None,
        help="Filter anime counts by season",
    )
    p_status.set_defaults(func=cmd_status)

    # dump
    p_dump = subparsers.add_parser(
        "dump",
        help="Dump compact JSON of animes and unlinked mappings for AI inspection",
    )
    p_dump.add_argument(
        "--status",
        choices=["PENDING", "APPROVED", "REJECTED", "ALL"],
        default="PENDING",
        help="ReviewStatus filter (default: PENDING)",
    )
    p_dump.add_argument("--year", type=int, default=None, help="Filter by start year")
    p_dump.add_argument(
        "--season",
        choices=["WINTER", "SPRING", "SUMMER", "FALL"],
        default=None,
        help="Filter by start season",
    )
    p_dump.add_argument("--keyword", default=None, help="Filter items by keyword substring")
    p_dump.add_argument(
        "--no-unlinked",
        action="store_true",
        help="Omit unlinked mappings from dump output",
    )
    p_dump.add_argument(
        "--include-cover",
        action="store_true",
        help="Include coverImage URLs in output (omitted by default to save tokens)",
    )
    p_dump.set_defaults(func=cmd_dump)

    # animes
    p_animes = subparsers.add_parser("animes", help="List animes with optional filters")
    p_animes.add_argument(
        "--status",
        choices=["PENDING", "APPROVED", "REJECTED", "ALL"],
        default="PENDING",
        help="ReviewStatus filter (default: PENDING)",
    )
    p_animes.add_argument("--year", type=int, default=None, help="Filter by start year")
    p_animes.add_argument(
        "--season",
        choices=["WINTER", "SPRING", "SUMMER", "FALL"],
        default=None,
        help="Filter by start season",
    )
    p_animes.add_argument("--keyword", default=None, help="Filter by keyword")
    p_animes.add_argument("--include-cover", action="store_true", help="Include coverImage URLs")
    p_animes.set_defaults(func=cmd_animes)

    # unlinked
    p_unlinked = subparsers.add_parser("unlinked", help="List unlinked platform mappings")
    p_unlinked.add_argument("--keyword", default=None, help="Filter by keyword")
    p_unlinked.add_argument("--include-cover", action="store_true", help="Include coverImage URLs")
    p_unlinked.set_defaults(func=cmd_unlinked)

    # update-anime
    p_update = subparsers.add_parser("update-anime", help="Update a single anime's fields")
    p_update.add_argument("anime_id", type=int, help="Target animeId")
    p_update.add_argument(
        "--status",
        choices=["PENDING", "APPROVED", "REJECTED"],
        default=None,
        help="New reviewStatus",
    )
    p_update.add_argument("--title-cn", default=None, help="Update Chinese title (titleCn)")
    p_update.add_argument("--title-native", default=None, help="Update native title (titleNative)")
    p_update.add_argument("--title-romaji", default=None, help="Update romaji title (titleRomaji)")
    p_update.add_argument("--title-en", default=None, help="Update English title (titleEn)")
    p_update.add_argument("--start-date", default=None, help="Update startDate (YYYY-MM-DD)")
    p_update.add_argument("--cover-image", default=None, help="Update coverImage URL")
    p_update.set_defaults(func=cmd_update_anime)

    # link-mapping
    p_link = subparsers.add_parser("link-mapping", help="Link or unlink a mapping to an anime")
    p_link.add_argument("mapping_id", type=int, help="Target mappingId")
    target = p_link.add_mutually_exclusive_group(required=True)
    target.add_argument("--anime-id", type=int, default=None, help="Target animeId to link to")
    target.add_argument("--unlink", action="store_true", help="Unlink mapping from its anime")
    p_link.set_defaults(func=cmd_link_mapping)

    # merge-anime
    p_merge = subparsers.add_parser(
        "merge-anime",
        help="Move all mappings from source anime to target anime and delete source anime",
    )
    p_merge.add_argument("target_anime_id", type=int, help="Target animeId to keep")
    p_merge.add_argument("source_anime_id", type=int, help="Source animeId to merge and delete")
    p_merge.add_argument(
        "--keep-source",
        action="store_true",
        help="Do not delete source anime after moving its mappings",
    )
    p_merge.set_defaults(func=cmd_merge_anime)

    # apply
    p_apply = subparsers.add_parser(
        "apply",
        help="Execute a batch of operations from a JSON plan file",
    )
    p_apply.add_argument(
        "--file",
        "-f",
        required=True,
        help="Path to JSON file containing batch actions",
    )
    p_apply.add_argument(
        "--dry-run",
        action="store_true",
        help="Validate and preview actions without sending write requests",
    )
    p_apply.add_argument(
        "--fail-fast",
        action="store_true",
        help="Stop execution on the first failed action",
    )
    p_apply.set_defaults(func=cmd_apply)

    # task
    p_task = subparsers.add_parser("task", help="Trigger an async backend admin task")
    p_task.add_argument(
        "task_name",
        choices=["anime-fetch", "mapping-fetch", "mapping-link", "metric-recalculation"],
        help="Backend task to trigger",
    )
    p_task.add_argument("--year", type=int, default=None, help="Year (for fetch tasks)")
    p_task.add_argument(
        "--season",
        choices=["WINTER", "SPRING", "SUMMER", "FALL"],
        default=None,
        help="Season (optional for fetch tasks)",
    )
    p_task.add_argument(
        "--platform",
        choices=["Bangumi", "AniList", "MyAnimeList"],
        default=None,
        help="Platform (optional for fetch tasks)",
    )
    p_task.set_defaults(func=cmd_task)

    return parser


def main(argv: Optional[List[str]] = None) -> None:
    parser = build_parser()
    args = parser.parse_args(argv)
    client = AdminApiClient(base_url=args.base_url, token=args.token)
    try:
        args.func(client, args)
    except AdminApiError as exc:
        _print_json(
            {
                "success": False,
                "error": str(exc),
                "statusCode": exc.status_code,
                "code": exc.code,
            },
            pretty=args.pretty,
        )
        sys.exit(1)


if __name__ == "__main__":
    main()
