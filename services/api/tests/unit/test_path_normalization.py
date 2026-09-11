import unittest

from app.investigations.path_normalization import normalized_path, paths_match


class NormalizedPathTests(unittest.TestCase):
    def test_normalizes_backslashes_and_leading_dot_slash(self) -> None:
        self.assertEqual(normalized_path("./app\\checkout.py"), "app/checkout.py")

    def test_leaves_an_already_relative_path_unchanged(self) -> None:
        self.assertEqual(normalized_path("app/checkout.py"), "app/checkout.py")


class PathsMatchTests(unittest.TestCase):
    def test_identical_paths_match(self) -> None:
        self.assertTrue(paths_match("app/checkout.py", "app/checkout.py"))

    def test_absolute_deploy_path_matches_repo_relative_suffix(self) -> None:
        self.assertTrue(
            paths_match(
                "/opt/render/project/src/sandbox-target/app/checkout.py",
                "sandbox-target/app/checkout.py",
            )
        )

    def test_match_is_order_independent(self) -> None:
        self.assertTrue(
            paths_match(
                "sandbox-target/app/checkout.py",
                "/opt/render/project/src/sandbox-target/app/checkout.py",
            )
        )

    def test_windows_style_separators_still_match(self) -> None:
        self.assertTrue(
            paths_match(
                "C:\\builds\\sandbox-target\\app\\checkout.py",
                "sandbox-target/app/checkout.py",
            )
        )

    def test_never_matches_a_different_directorys_same_named_file(self) -> None:
        self.assertFalse(
            paths_match(
                "sandbox-target/other_app/checkout.py",
                "sandbox-target/app/checkout.py",
            )
        )

    def test_never_matches_on_a_bare_filename_alone(self) -> None:
        self.assertFalse(paths_match("checkout.py", "sandbox-target/app/checkout.py"))

    def test_never_matches_a_partial_segment_substring(self) -> None:
        self.assertFalse(paths_match("app/checkout.py", "other_app/checkout.py"))

    def test_unrelated_paths_do_not_match(self) -> None:
        self.assertFalse(paths_match("app/checkout.py", "app/inventory.py"))


if __name__ == "__main__":
    unittest.main()
