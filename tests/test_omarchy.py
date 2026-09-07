import subprocess
import unittest

from dusk import omarchy
from tests import util  # noqa: F401


class ThemeCatalogTest(unittest.TestCase):
    def test_catalog_is_one_normalized_view_per_operation(self):
        adapter = omarchy.Omarchy()
        calls = []

        def run(args, timeout=None):
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

        adapter._run = run

        catalog = adapter.theme_catalog(["Tokyo Night", "missing"])

        self.assertEqual(catalog.slugs(), ("catppuccin-latte", "gruvbox", "tokyo-night"))
        self.assertEqual(catalog.display_name("catppuccin-latte"), "<span>Catppuccin Latte</span>")
        self.assertEqual(catalog.display_name("unknown"), "unknown")
        self.assertTrue(catalog.available("Tokyo Night"))
        self.assertFalse(catalog.available("missing"))
        self.assertEqual([args for args, _timeout in calls].count(["theme", "list"]), 1)

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
