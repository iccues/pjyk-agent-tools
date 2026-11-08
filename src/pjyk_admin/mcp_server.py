"""Local stdio MCP entry point for the Project Yuki admin API."""
import json
from typing import Any, Dict, List, Optional

from pjyk_admin.client import AdminApiClient
from pjyk_admin.operations import AdminOperations


def create_server(client: Optional[AdminApiClient] = None):
    from mcp.server.fastmcp import FastMCP
    from mcp.types import CallToolResult, TextContent, ToolAnnotations

    server = FastMCP("pjyk-agent-tools")
    ops = AdminOperations(client if client is not None else AdminApiClient())
    for tool in (ops.status, ops.dump, ops.animes, ops.unlinked):
        server.add_tool(tool, annotations=ToolAnnotations(readOnlyHint=True))
    for tool in (ops.update_anime, ops.link_mapping, ops.merge_anime, ops.task):
        server.add_tool(tool)

    @server.tool()
    def apply(
        actions: List[Dict[str, Any]], dry_run: bool = False, fail_fast: bool = False
    ) -> CallToolResult:
        """Validate and execute an ordered array of admin actions.

        Use dry_run=true to validate locally. Each action has an op and its fields:
        link_mapping(mappingId, animeId; null unlinks), merge_animes(targetAnimeId,
        sourceAnimeId, optional deleteSource), update_anime(animeId, optional title,
        reviewStatus, startDate, coverImage), create_anime(optional title, startDate,
        coverImage, mappingIds), delete_anime(animeId), create_mapping(platform,
        platformId, optional animeId), or delete_mapping(mappingId). Writes completed
        before a failure persist. Inspect results before retrying.
        """
        summary = ops.apply(actions, dry_run=dry_run, fail_fast=fail_fast)
        return CallToolResult(
            content=[TextContent(type="text", text=json.dumps(summary, ensure_ascii=False))],
            structuredContent=summary,
            isError=bool(summary.get("failed")),
        )

    return server


def main() -> None:
    try:
        server = create_server()
    except ModuleNotFoundError as exc:
        if exc.name != "mcp":
            raise
        raise SystemExit("Install MCP support with Python 3.10+ and pip install '.[mcp]'") from exc
    server.run(transport="stdio")


if __name__ == "__main__":
    main()
