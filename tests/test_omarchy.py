import subprocess
import unittest

from dusk import omarchy
from tests import util  # noqa: F401


class ThemeCatalogTest(unittest.TestCase):
    def test_catalog_is_one_normalized_view_per_operation(self):
        calls = []

        def run(args, timeout):
            calls.append((args, timeout))
            if args == ["theme", "list"]:
                return subprocess.CompletedProcess(
                    args,
                    0,
                    "<span>Catppuccin Latte</span>\nGruvbox\nCatppuccin Latte\n",
                    "",
                )
            if args == ["theme", "dir", "tokyo-night"]:
                return subprocess.CompletedProcess(args, 0, "/themes/tokyo-night\n", "")
            return subprocess.CompletedProcess(args, 1, "", "missing")

        adapter = omarchy.Omarchy(runner=run)

        catalog = adapter.theme_catalog(["Tokyo Night", "missing"])

        self.assertEqual(catalog.slugs(), ("catppuccin-latte", "gruvbox", "tokyo-night"))
        self.assertEqual(catalog.display_name("catppuccin-latte"), "<span>Catppuccin Latte</span>")
        self.assertEqual(catalog.display_name("unknown"), "unknown")
        self.assertTrue(catalog.available("Tokyo Night"))
        self.assertFalse(catalog.available("missing"))
        self.assertIsNone(catalog.discovery_error)
        self.assertIs(catalog.availability("missing"), False)
        self.assertEqual([args for args, _timeout in calls].count(["theme", "list"]), 1)

    def test_catalog_distinguishes_empty_installation_from_failed_discovery(self):
        empty = omarchy.Omarchy(
            runner=lambda args, timeout: subprocess.CompletedProcess(args, 0, "", "")
        )

        def fail(_args, timeout):
            raise OSError("omarchy not found")

        unavailable = omarchy.Omarchy(runner=fail)

        self.assertEqual(empty.theme_catalog().themes, ())
        self.assertIsNone(empty.theme_catalog().discovery_error)
        self.assertEqual(unavailable.theme_catalog().themes, ())
        self.assertIn("omarchy not found", unavailable.theme_catalog().discovery_error)
        self.assertIs(unavailable.theme_catalog().availability("gruvbox"), None)

    def test_catalog_preserves_nonzero_list_failure_while_probing_candidates(self):
        def run(args, timeout):
            if args == ["theme", "list"]:
                return subprocess.CompletedProcess(args, 2, "", "catalog unavailable")
            if args == ["theme", "dir", "gruvbox"]:
                return subprocess.CompletedProcess(args, 0, "/themes/gruvbox\n", "")
            return subprocess.CompletedProcess(args, 1, "", "missing")

        adapter = omarchy.Omarchy(runner=run)

        catalog = adapter.theme_catalog(["gruvbox"])

        self.assertTrue(catalog.available("gruvbox"))
        self.assertIn("catalog unavailable", catalog.discovery_error)

    def test_failed_list_can_still_confirm_candidate_absence(self):
        def run(args, timeout):
            return subprocess.CompletedProcess(args, 1, "", "missing")

        catalog = omarchy.Omarchy(runner=run).theme_catalog(["missing"])

        self.assertIn("could not list", catalog.discovery_error)
        self.assertIs(catalog.availability("missing"), False)
        self.assertIs(catalog.availability("unprobed"), None)

    def test_duplicate_failed_candidate_is_probed_once(self):
        calls = []

        def run(args, timeout):
            calls.append(args)
            if args == ["theme", "list"]:
                return subprocess.CompletedProcess(args, 0, "", "")
            return subprocess.CompletedProcess(args, 1, "", "missing")

        catalog = omarchy.Omarchy(runner=run).theme_catalog(["Missing", "missing"])

        self.assertIs(catalog.availability("missing"), False)
        self.assertEqual(calls.count(["theme", "dir", "missing"]), 1)

    def test_catalog_preserves_candidate_probe_failure(self):
        def run(args, timeout):
            if args == ["theme", "list"]:
                return subprocess.CompletedProcess(args, 0, "Gruvbox\n", "")
            raise OSError("probe unavailable")

        adapter = omarchy.Omarchy(runner=run)

        catalog = adapter.theme_catalog(["Tokyo Night"])

        self.assertFalse(catalog.available("tokyo-night"))
        self.assertIs(catalog.availability("tokyo-night"), None)
        self.assertIn("probe unavailable", catalog.discovery_error)

    def test_catalog_entries_are_consumer_ready(self):
        catalog = omarchy.ThemeCatalog(
            (
                omarchy.Theme("catppuccin", "Catppuccin"),
                omarchy.Theme("gruvbox", "Gruvbox"),
            )
        )

        self.assertEqual(
            catalog.as_dicts(),
            [
                {"slug": "catppuccin", "name": "Catppuccin"},
                {"slug": "gruvbox", "name": "Gruvbox"},
            ],
        )


if __name__ == "__main__":
    unittest.main()
