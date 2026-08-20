import unittest

from app.connectors.errors import (
    GitHubIncompleteResultError,
    GitHubInvalidResponseError,
)
from app.connectors.github_diff import MAX_PATCH_CHARACTERS, parse_github_patch
from app.investigations import DiffLineKind


class GitHubDiffParserTests(unittest.TestCase):
    def test_valid_hunk_preserves_ranges_and_typed_lines(self) -> None:
        hunks = parse_github_patch(
            "@@ -10,2 +10,3 @@ def checkout():\n"
            " context\n"
            "-old value\n"
            "+new value\n"
            "+extra value"
        )

        self.assertEqual(len(hunks), 1)
        self.assertEqual(
            (hunks[0].old_start, hunks[0].old_count),
            (10, 2),
        )
        self.assertEqual(
            (hunks[0].new_start, hunks[0].new_count),
            (10, 3),
        )
        self.assertEqual(
            tuple(line.kind for line in hunks[0].lines),
            (
                DiffLineKind.CONTEXT,
                DiffLineKind.DELETION,
                DiffLineKind.ADDITION,
                DiffLineKind.ADDITION,
            ),
        )

    def test_multiple_hunks_remain_in_provider_order(self) -> None:
        hunks = parse_github_patch(
            "@@ -1 +1 @@\n-old\n+new\n"
            "@@ -20,0 +21,2 @@\n+first\n+second"
        )

        self.assertEqual(
            tuple((hunk.old_start, hunk.new_start) for hunk in hunks),
            ((1, 1), (20, 21)),
        )

    def test_no_newline_marker_is_metadata_not_a_code_line(self) -> None:
        hunks = parse_github_patch(
            "@@ -1 +1 @@\n-old\n\\ No newline at end of file\n+new"
        )

        self.assertEqual(len(hunks[0].lines), 2)

    def test_malformed_patch_is_a_sanitized_invalid_response(self) -> None:
        for patch in ("", "not a hunk", "@@ malformed @@\n-old\n+new"):
            with self.subTest(patch=patch):
                with self.assertRaises(GitHubInvalidResponseError):
                    parse_github_patch(patch)

    def test_truncated_range_is_an_explicit_incomplete_result(self) -> None:
        with self.assertRaises(GitHubIncompleteResultError):
            parse_github_patch("@@ -1,2 +1,2 @@\n-old\n+new")

    def test_patch_character_bound_is_an_explicit_incomplete_result(self) -> None:
        with self.assertRaises(GitHubIncompleteResultError):
            parse_github_patch("x" * (MAX_PATCH_CHARACTERS + 1))
