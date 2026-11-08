from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, List, Optional

from pjyk_admin.client import AdminApiClient, AdminApiError
from pjyk_admin.operations import AdminOperations


def _print_json(data: Any, pretty: bool = False) -> None:
    if pretty:
        print(json.dumps(data, ensure_ascii=False, indent=2))
    else:
        print(json.dumps(data, ensure_ascii=False))


def _load_plan(filename: str) -> List[dict]:
    plan_path = Path(filename)
    if not plan_path.is_file():
        raise AdminApiError(f"Batch plan file not found: {plan_path}")

    try:
        raw_plan = json.loads(plan_path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise AdminApiError(f"Cannot read batch plan {plan_path}: {exc}") from exc
    if isinstance(raw_plan, list):
        return raw_plan
    elif isinstance(raw_plan, dict) and isinstance(raw_plan.get("actions"), list):
        return raw_plan["actions"]
    else:
        raise AdminApiError(
            "Invalid plan JSON format: expected a list of actions or an object with an 'actions' array."
        )


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

    # unlinked
    p_unlinked = subparsers.add_parser("unlinked", help="List unlinked platform mappings")
    p_unlinked.add_argument("--keyword", default=None, help="Filter by keyword")
    p_unlinked.add_argument("--include-cover", action="store_true", help="Include coverImage URLs")

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

    # link-mapping
    p_link = subparsers.add_parser("link-mapping", help="Link or unlink a mapping to an anime")
    p_link.add_argument("mapping_id", type=int, help="Target mappingId")
    target = p_link.add_mutually_exclusive_group(required=True)
    target.add_argument("--anime-id", type=int, default=None, help="Target animeId to link to")
    target.add_argument("--unlink", action="store_true", help="Unlink mapping from its anime")

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

    return parser


def main(argv: Optional[List[str]] = None) -> None:
    parser = build_parser()
    args = vars(parser.parse_args(argv))
    command = args.pop("subcommand").replace("-", "_")
    pretty = args.pop("pretty")
    client = AdminApiClient(base_url=args.pop("base_url"), token=args.pop("token"))
    try:
        if command == "apply":
            args["actions"] = _load_plan(args.pop("file"))
        result = getattr(AdminOperations(client), command)(**args)
        _print_json(result, pretty=pretty)
        if command == "apply" and result.get("failed"):
            sys.exit(1)
    except AdminApiError as exc:
        _print_json(
            {
                "success": False,
                "error": str(exc),
                "statusCode": exc.status_code,
                "code": exc.code,
            },
            pretty=pretty,
        )
        sys.exit(1)


if __name__ == "__main__":
    main()
