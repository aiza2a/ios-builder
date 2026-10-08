import importlib.util
import os
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch

SPEC = importlib.util.spec_from_file_location(
    "release_number", Path(__file__).resolve().parents[1] / "tools/release_number.py")
release_number = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(release_number)


def release(tag, draft=False, size=12, state="uploaded"):
    return {"id": 123, "tag_name": tag, "draft": draft,
            "assets": [{"name": f"App-{tag}.ipa", "size": size, "state": state}]}


class ReleaseNumberTests(unittest.TestCase):
    def test_new_version_starts_at_one(self):
        self.assertEqual(release_number.next_number([release("v1.0.0-10")], "1.0.1", "App"), 1)

    def test_legacy_numbers_continue_from_maximum(self):
        items = [release("v0.8.3-53"), release("v0.8.3-57"), release("v0.8.2-99")]
        self.assertEqual(release_number.next_number(items, "0.8.3", "App"), 58)

    def test_subtitle_series_does_not_share_stable_version_counter(self):
        items = [release("v0.8.5-80"), release("v0.8.5-S2"), release("v0.8.5-S3", draft=True)]
        self.assertEqual(release_number.next_number(items, "0.8.5", "App", "S"), 3)
        self.assertEqual(release_number.next_number(items, "0.8.5", "App"), 81)
        with self.assertRaises(ValueError):
            release_number.next_number(items, "0.8.5", "App", "S\nBAD=1")

    def test_failed_drafts_and_incomplete_uploads_do_not_count(self):
        items = [release("v1.0.0-2"), release("v1.0.0-3", draft=True),
                 release("v1.0.0-4", size=0), release("v1.0.0-5", state="starter")]
        self.assertEqual(release_number.next_number(items, "1.0.0", "App"), 3)

    def test_matching_is_exact(self):
        items = [release("v1.0.01-90"), release("v1.0.0-10-extra"), release("pending-build-99")]
        self.assertEqual(release_number.next_number(items, "1.0.0", "App"), 1)
        with self.assertRaises(ValueError):
            release_number.next_number([], "1.0.0\nBAD=1", "App")

    def test_api_failure_propagates_instead_of_resetting_counter(self):
        with patch.object(release_number, "api", side_effect=RuntimeError("network")):
            with self.assertRaisesRegex(RuntimeError, "network"):
                release_number.available_number("owner/repo", "1.0.0", "App")

    def test_all_release_pages_are_read(self):
        with patch.object(release_number, "api", side_effect=[[release("v1.0.0-1")] * 100,
                                                               [release("v1.0.0-101")]]) as api:
            items = release_number.releases("owner/repo")
        self.assertEqual(len(items), 101)
        self.assertIn("page=2", api.call_args.args[1])

    def test_orphan_tag_blocks_without_deleting_or_skipping_it(self):
        with patch.object(release_number, "api", side_effect=[[], [{"ref": "refs/tags/v1.0.0-1"}]]):
            with self.assertRaisesRegex(RuntimeError, "already exists"):
                release_number.available_number("owner/repo", "1.0.0", "App")

    def run_publish(self, responses, upload_error=None, series=""):
        with tempfile.TemporaryDirectory() as directory:
            artifact = Path(directory) / f"App-v1.0.0-{series}1.ipa"
            artifact.write_bytes(b"test archive")
            notes = Path(directory) / "notes.md"
            notes.write_text("Test", encoding="utf-8")
            with patch.object(release_number, "available_number", return_value=1), \
                 patch.object(release_number, "api", side_effect=responses) as api, \
                 patch.object(release_number.subprocess, "run", side_effect=upload_error), \
                 patch.dict(os.environ, {"GITHUB_RUN_ID": "100", "GITHUB_RUN_ATTEMPT": "2"}):
                try:
                    release_number.publish("owner/repo", "1.0.0", "App", 1, "a" * 40, artifact, notes, series)
                finally:
                    self.api_calls = api.call_args_list

    def test_publish_only_after_upload_verification(self):
        self.run_publish([{"id": 123}, release("v1.0.0-1", draft=True), release("v1.0.0-1")])
        created = self.api_calls[0].args[3]
        self.assertTrue(created["draft"])
        self.assertEqual(created["tag_name"], "pending-build-100-2")
        published = self.api_calls[-1].args[3]
        self.assertEqual(published, {"tag_name": "v1.0.0-1", "target_commitish": "a" * 40, "draft": False})

    def test_subtitle_build_is_a_prerelease_and_does_not_replace_latest(self):
        self.run_publish([{"id": 123}, release("v1.0.0-S1", draft=True), release("v1.0.0-S1")], series="S")
        published = self.api_calls[-1].args[3]
        self.assertEqual(published["tag_name"], "v1.0.0-S1")
        self.assertEqual(published["target_commitish"], "a" * 40)
        self.assertTrue(published["prerelease"])
        self.assertEqual(published["make_latest"], "false")

    def test_failed_upload_removes_only_its_draft_and_raises(self):
        with self.assertRaises(subprocess.CalledProcessError):
            self.run_publish([{"id": 123}, release("pending-build-100-2", draft=True), None],
                             subprocess.CalledProcessError(1, "gh"))
        self.assertEqual(self.api_calls[-1].args, ("owner/repo", "releases/123", "DELETE"))
        self.assertFalse(any(call.args[2:3] == ("PATCH",) for call in self.api_calls))

    def test_failed_publish_does_not_consume_a_number(self):
        with self.assertRaises(RuntimeError):
            self.run_publish([{"id": 123}, release("v1.0.0-1", draft=True),
                              RuntimeError("publish failed"), release("v1.0.0-1", draft=True), None])
        self.assertEqual(self.api_calls[-1].args[2], "DELETE")

    def test_lost_response_confirms_published_state_without_deleting(self):
        self.run_publish([{"id": 123}, release("v1.0.0-1", draft=True),
                          RuntimeError("response lost"), release("v1.0.0-1")])
        self.assertFalse(any(call.args[2:3] == ("DELETE",) for call in self.api_calls))


if __name__ == "__main__":
    unittest.main()
