"""Facade around the public Omarchy CLI.

The scheduler and CLI speak to Omarchy only through `omarchy theme ...`.
Arguments are always passed as individual argv entries — never interpolated
into shell source and never passed to a shell.
"""

from __future__ import annotations

import re
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from . import paths

_TAG_RE = re.compile(r"<[^>]+>")


def normalize_slug(name: str) -> str:
    """Mirror `omarchy theme set`'s own normalization of a theme argument."""
    return _TAG_RE.sub("", name).lower().replace(" ", "-")


@dataclass
class ApplyResult:
    success: bool
    returncode: int | None = None
    stdout: str = ""
    stderr: str = ""


class Omarchy:
    """Real Omarchy interaction. Override or fake this in tests."""

    def __init__(
        self,
        omarchy_bin: str = "omarchy",
        theme_name_file: Any = None,
        apply_timeout: float = 600.0,
    ) -> None:
        self.omarchy_bin = omarchy_bin
        self.theme_name_file = Path(theme_name_file) if theme_name_file else paths.omarchy_current_theme_file()
        self.apply_timeout = apply_timeout

    def _run(self, args: list[str], timeout: float | None = None) -> subprocess.CompletedProcess:
        return subprocess.run(
            [self.omarchy_bin, *args],
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
        )

    def list_theme_names(self) -> list[str]:
        """Raw display lines from `omarchy theme list`, in Omarchy's order."""
        try:
            proc = self._run(["theme", "list"], timeout=30)
        except (OSError, subprocess.SubprocessError):
            return []
        if proc.returncode != 0:
            return []
        return [line.strip() for line in proc.stdout.splitlines() if line.strip()]

    def list_theme_slugs(self) -> set[str]:
        return {normalize_slug(name) for name in self.list_theme_names() if name}

    def pretty_name(self, slug: str | None) -> str:
        """The display name Omarchy prints for `slug`, or the slug itself."""
        if not slug:
            return ""
        target = normalize_slug(slug)
        for name in self.list_theme_names():
            if normalize_slug(name) == target:
                return name
        return slug

    def theme_available(self, slug: str) -> bool:
        slug = normalize_slug(slug)
        if not slug:
            return False
        if slug in self.list_theme_slugs():
            return True
        try:
            proc = self._run(["theme", "dir", slug], timeout=15)
        except (OSError, subprocess.SubprocessError):
            return False
        return proc.returncode == 0

    def current_theme(self) -> str | None:
        try:
            raw = self.theme_name_file.read_text(encoding="utf-8").strip()
        except OSError:
            return None
        slug = normalize_slug(raw)
        return slug or None

    def apply_theme(self, slug: str) -> ApplyResult:
        slug = normalize_slug(slug)
        try:
            proc = self._run(["theme", "set", slug], timeout=self.apply_timeout)
        except subprocess.TimeoutExpired:
            return ApplyResult(success=False, stderr=f"omarchy theme set timed out after {self.apply_timeout}s")
        except OSError as exc:
            return ApplyResult(success=False, stderr=f"could not run omarchy: {exc}")
        return ApplyResult(
            success=proc.returncode == 0,
            returncode=proc.returncode,
            stdout=proc.stdout,
            stderr=proc.stderr,
        )


def weather_location(path: Any = None) -> tuple[float, float] | None:
    """Coordinates from Omarchy's weather state, or None if absent/invalid."""
    import json

    path = Path(path) if path is not None else paths.omarchy_weather_file()
    try:
        with path.open("r", encoding="utf-8") as fh:
            data = json.load(fh)
    except (OSError, ValueError):
        return None
    if not isinstance(data, dict):
        return None
    try:
        latitude = float(data.get("latitude"))
        longitude = float(data.get("longitude"))
    except (TypeError, ValueError):
        return None
    if not (-90.0 <= latitude <= 90.0 and -180.0 <= longitude <= 180.0):
        return None
    return latitude, longitude