import importlib.util
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock

SRC = Path(__file__).resolve().parents[1] / "src"
sys.path.insert(0, str(SRC))

from pjyk_admin.client import AdminApiClient, AdminApiError
from pjyk_admin.mcp_server import create_server


@unittest.skipUnless(importlib.util.find_spec("mcp"), "requires the mcp extra")
class McpTests(unittest.IsolatedAsyncioTestCase):
    async def test_stdio_discovery_and_batch_preview(self):
        from mcp import ClientSession, StdioServerParameters
        from mcp.client.stdio import stdio_client

        actions = [{"op": "delete_anime", "animeId": 7}]
        with tempfile.TemporaryDirectory() as cwd:
            params = StdioServerParameters(
                command=sys.executable, args=["-m", "pjyk_admin.mcp_server"],
                cwd=cwd, env={"PYTHONPATH": str(SRC)},
            )
            async with stdio_client(params) as (reader, writer), ClientSession(reader, writer) as session:
                await session.initialize()
                tools = {tool.name: tool for tool in (await session.list_tools()).tools}
                self.assertEqual(set(tools), {
                    "status", "dump", "animes", "unlinked", "update_anime", "link_mapping",
                    "merge_anime", "apply", "task",
                })
                self.assertTrue(tools["status"].annotations.readOnlyHint)
                self.assertNotIn("file", tools["apply"].inputSchema["properties"])
                result = await session.call_tool("apply", {"actions": actions, "dry_run": True})
                self.assertFalse(result.isError)
                self.assertEqual(result.structuredContent["actions"], actions)
                error = await session.call_tool("link_mapping", {"mapping_id": 7})
                self.assertTrue(error.isError)
                bad_status = await session.call_tool("animes", {"status": "TYPO"})
                self.assertTrue(bad_status.isError)

    async def test_read_write_and_partial_failure(self):
        client = Mock(spec=AdminApiClient)
        server = create_server(client)
        client.list_animes.return_value = [{"animeId": 3}]
        _, data = await server.call_tool("animes", {"status": "ALL", "year": 2026})
        self.assertEqual(data["animes"][0]["animeId"], 3)
        client.list_animes.assert_called_once_with(review_status=None, year=2026, season=None)

        client.update_mapping_anime.return_value = {"mappingId": 5, "animeId": 3}
        _, data = await server.call_tool("link_mapping", {"mapping_id": 5, "anime_id": 3})
        self.assertEqual(data["animeId"], 3)
        client.update_mapping_anime.assert_called_once_with(5, 3)

        client.create_anime.return_value = {"animeId": 8}
        client.update_mapping_anime.side_effect = AdminApiError("mapping missing")
        result = await server.call_tool("apply", {
            "actions": [{"op": "create_anime", "mappingIds": [4]}],
        })
        self.assertTrue(result.isError)
        self.assertEqual(result.structuredContent["results"][0]["animeId"], 8)
