import json
from datetime import datetime, timezone

from dusk import config as config_mod
from dusk import omarchy as omarchy_mod
from dusk.omarchy import ApplyResult, normalize_slug


def utc_aware(y, m, d, hh=0, mm=0):
    return datetime(y, m, d, hh, mm, tzinfo=timezone.utc)


def write_config(path, overrides):
    cfg = config_mod.defaults()
    cfg.update(overrides)
    config_mod.save_config(cfg, path)
    return cfg


def write_state(path, data):
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(data, fh)


class FakeOmarchy(omarchy_mod.Omarchy):
    def __init__(self, installed=None, current=None, fail_on=None, fail_once=False):
        self.installed = {normalize_slug(s) for s in (installed or [])}
        self.current = current
        self.applied = []
        self.fail_on = fail_on or []  # slugs that should always fail
        self.fail_once = fail_once  # fail the very first apply, then succeed

    def theme_available(self, slug):
        return normalize_slug(slug) in self.installed

    def current_theme(self):
        return self.current

    def apply_theme(self, slug):
        slug = normalize_slug(slug)
        if self.fail_once:
            self.fail_once = False
            return ApplyResult(False, 1, "", f"boom: {slug}")
        if slug in self.fail_on:
            return ApplyResult(False, 1, "", f"boom: {slug}")
        self.applied.append(slug)
        self.current = slug
        return ApplyResult(True, 0, "", "")

    def list_theme_slugs(self):
        return set(self.installed)