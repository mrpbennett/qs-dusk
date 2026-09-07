"""Facade around the public Omarchy CLI.

The scheduler and CLI speak to Omarchy only through `omarchy theme ...`.
Arguments are always passed as individual argv entries — never interpolated
into shell source and never passed to a shell.
"""

from __future__ import annotations

import re
import subprocess
from collections.abc import Callable, Iterable
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


@dataclass(frozen=True)
class Theme:
    slug: str
    name: str


@dataclass(frozen=True)
class ThemeCatalog:
    themes: tuple[Theme, ...]
    discovery_error: str | None = None
    unknown_slugs: frozenset[str] = frozenset()
    absent_slugs: frozenset[str] = frozenset()
    discovery_complete: bool = True

    def available(self, slug: str) -> bool:
        return self.availability(slug) is True

    def availability(self, slug: str) -> bool | None:
        slug = normalize_slug(slug)
        if slug in self.slugs():
            return True
        if slug in self.absent_slugs:
            return False
        if not self.discovery_complete or slug in self.unknown_slugs:
            return None
        return False

    def display_name(self, slug: str | None) -> str:
        if not slug:
            return ""
        target = normalize_slug(slug)
        for theme in self.themes:
            if theme.slug == target:
                return theme.name
        return slug

    def slugs(self) -> tuple[str, ...]:
        return tuple(theme.slug for theme in self.themes)

    def as_dicts(self) -> list[dict[str, str]]:
        return [{"slug": theme.slug, "name": theme.name} for theme in self.themes]


class Omarchy:
    """Real Omarchy interaction. Override or fake this in tests."""

    def __init__(
        self,
        omarchy_bin: str = "omarchy",
        theme_name_file: Any = None,
        apply_timeout: float = 600.0,
        runner: Callable[[list[str], float | None], subprocess.CompletedProcess] | None = None,
    ) -> None:
        self.omarchy_bin = omarchy_bin
        self.theme_name_file = Path(theme_name_file) if theme_name_file else paths.omarchy_current_theme_file()
        self.apply_timeout = apply_timeout
        self._runner = runner or self._run

    def _run(self, args: list[str], timeout: float | None = None) -> subprocess.CompletedProcess:
        return subprocess.run(
            [self.omarchy_bin, *args],
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
        )

    def theme_catalog(self, candidates: Iterable[str] = ()) -> ThemeCatalog:
        """Return one coherent view of installed themes for an operation."""
        names: list[str] = []
        discovery_errors: list[str] = []
        discovery_complete = False
        try:
            proc = self._runner(["theme", "list"], 30)
        except (OSError, subprocess.SubprocessError) as exc:
            proc = None
            discovery_errors.append(f"could not list Omarchy themes: {exc}")
        if proc is not None and proc.returncode == 0:
            names = [line.strip() for line in proc.stdout.splitlines() if line.strip()]
            discovery_complete = True
        elif proc is not None:
            detail = (proc.stderr or proc.stdout or f"exit code {proc.returncode}").strip()
            discovery_errors.append(f"could not list Omarchy themes: {detail}")

        themes: list[Theme] = []
        seen: set[str] = set()
        probed: set[str] = set()
        unknown_slugs: set[str] = set()
        absent_slugs: set[str] = set()
        for name in names:
            slug = normalize_slug(name)
            if slug and slug not in seen:
                themes.append(Theme(slug, name))
                seen.add(slug)

        for candidate in candidates:
            slug = normalize_slug(candidate)
            if not slug or slug in seen or slug in probed:
                continue
            probed.add(slug)
            try:
                proc = self._runner(["theme", "dir", slug], 15)
            except (OSError, subprocess.SubprocessError) as exc:
                discovery_errors.append(f"could not inspect Omarchy theme {slug!r}: {exc}")
                unknown_slugs.add(slug)
                continue
            if proc.returncode == 0:
                themes.append(Theme(slug, slug.replace("-", " ").title()))
                seen.add(slug)
            else:
                absent_slugs.add(slug)
        return ThemeCatalog(
            tuple(themes),
            "; ".join(dict.fromkeys(discovery_errors)) or None,
            frozenset(unknown_slugs),
            frozenset(absent_slugs),
            discovery_complete=discovery_complete,
        )

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
            proc = self._runner(["theme", "set", slug], self.apply_timeout)
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
