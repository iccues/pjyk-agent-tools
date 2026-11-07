import io
import json
import sys
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from unittest.mock import Mock, call, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from pjyk_admin.cli import main
from pjyk_admin.client import AdminApiClient, AdminApiError


class AdminCliTests(unittest.TestCase):
    def setUp(self):
        self.client = Mock(spec=AdminApiClient)
        client_patch = patch("pjyk_admin.cli.AdminApiClient", return_value=self.client)
        client_patch.start()
        self.addCleanup(client_patch.stop)

    def invoke(self, *args):
        out = io.StringIO()
        with redirect_stdout(out), redirect_stderr(io.StringIO()):
            try:
                main(list(args))
            except SystemExit as exc:
                return exc.code, json.loads(out.getvalue()) if out.getvalue() else None
        return 0, json.loads(out.getvalue())

    def apply(self, plan, *flags):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "plan.json"
            path.write_text(json.dumps(plan), encoding="utf-8")
            return self.invoke("apply", "--file", str(path), *flags)

    def test_chain_merge_reads_current_mappings(self):
        self.client.list_animes.side_effect = [
            [{"animeId": 1, "mappings": [{"mappingId": 11}]}, {"animeId": 2}, {"animeId": 3}],
            [{"animeId": 2, "mappings": [{"mappingId": 11}, {"mappingId": 22}]}, {"animeId": 3}],
        ]
        code, summary = self.apply([
            {"op": "merge_animes", "sourceAnimeId": 1, "targetAnimeId": 2},
            {"op": "merge_animes", "sourceAnimeId": 2, "targetAnimeId": 3, "deleteSource": False},
        ])
        self.assertEqual(code, 0)
        self.assertEqual(summary["results"][1]["movedMappingIds"], [11, 22])
        self.assertEqual(self.client.update_mapping_anime.call_args_list,
                         [call(11, 2), call(11, 3), call(22, 3)])
        self.client.delete_anime.assert_called_once_with(1)

    def test_missing_target_preserves_empty_source(self):
        self.client.list_animes.return_value = [{"animeId": 1, "mappings": []}]
        code, error = self.invoke("merge-anime", "2", "1")
        self.assertEqual(code, 1)
        self.assertIn("Target Anime 2", error["error"])
        self.client.delete_anime.assert_not_called()
        self.client.update_mapping_anime.assert_not_called()

    def test_link_requires_exactly_one_target_option(self):
        for flags in ([], ["--unlink", "--anime-id", "2"]):
            self.assertEqual(self.invoke("link-mapping", "8", *flags)[0], 2)
        self.client.update_mapping_anime.assert_not_called()
        self.client.update_mapping_anime.return_value = {"mappingId": 8}
        for flags in (["--unlink"], ["--anime-id", "2"]):
            self.assertEqual(self.invoke("link-mapping", "8", *flags)[0], 0)
        self.assertEqual(self.client.update_mapping_anime.call_args_list, [call(8, None), call(8, 2)])

    def test_preflight_checks_all_actions_before_writes(self):
        invalid_actions = [
            None, {"op": "typo"}, {"op": "link_mapping", "mappingId": 8},
            {"op": "merge_animes", "targetAnimeId": 1, "sourceAnimeId": 2, "deleteSource": "false"},
            {"op": "merge_animes", "targetAnimeId": "1", "sourceAnimeId": 1},
            {"op": "create_anime", "mappingIds": [1, False]},
            {"op": "create_mapping", "platform": "AniList"},
            {"op": "update_anime", "animeId": 1, "reviewStatus": "typo"},
        ]
        for flags in ([], ["--dry-run"]):
            for action in invalid_actions:
                with self.subTest(flags=flags, action=action):
                    code, error = self.apply([{"op": "delete_anime", "animeId": 1}, action], *flags)
                    self.assertEqual(code, 1)
                    self.assertIn("index 1", error["error"])
        self.assertEqual(self.client.mock_calls, [])

    def test_explicit_batch_unlink_and_dry_run(self):
        plan = {"actions": [{"action": "link_mapping", "mappingId": "8", "animeId": None}]}
        self.assertTrue(self.apply(plan, "--dry-run")[1]["dryRun"])
        self.assertEqual(self.client.mock_calls, [])
        self.client.update_mapping_anime.return_value = {"animeId": None}
        self.assertEqual(self.apply(plan)[0], 0)
        self.client.update_mapping_anime.assert_called_once_with(8, None)

    def test_partial_create_reports_id_and_completed_links(self):
        self.client.create_anime.return_value = {"animeId": 99}
        self.client.update_mapping_anime.side_effect = [{}, AdminApiError("link failed")]
        code, summary = self.apply([
            {"op": "create_anime", "mappingIds": [4, 5]},
            {"op": "delete_mapping", "mappingId": 7},
        ], "--fail-fast")
        self.assertEqual(code, 1)
        result, = summary["results"]
        self.assertFalse(result["success"])
        self.assertEqual((result["animeId"], result["linkedMappingIds"]), (99, [4]))
        self.client.delete_mapping.assert_not_called()

    def test_partial_merge_and_create_mapping_report_progress(self):
        self.client.list_animes.return_value = [
            {"animeId": 1, "mappings": [{"mappingId": 4}, {"mappingId": 5}]}, {"animeId": 2},
        ]
        self.client.update_mapping_anime.side_effect = [{}, AdminApiError("move failed"), AdminApiError("link failed")]
        self.client.create_mapping.return_value = {"mappingId": 9}
        code, summary = self.apply([
            {"op": "merge_animes", "targetAnimeId": 2, "sourceAnimeId": 1},
            {"op": "create_mapping", "platform": "AniList", "platformId": "123", "animeId": 2},
        ])
        self.assertEqual(code, 1)
        merge, create = summary["results"]
        self.assertEqual(merge["movedMappingIds"], [4])
        self.assertFalse(merge["sourceDeleted"])
        self.assertEqual(create["mappingId"], 9)
        self.assertIsNone(create["animeId"])
        self.client.delete_anime.assert_not_called()
