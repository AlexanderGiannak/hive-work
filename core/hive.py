"""Loading hive.yml files and finding the bot classes they name."""

import importlib
import inspect
import os
import pkgutil
from dataclasses import dataclass, field
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent
HIVES_DIR = ROOT / "hives"

# Bots any hive can use without writing its own, like Recorder and DiscordAlert.
SHARED_BOTS_MODULE = "core.shared_bots"


@dataclass
class BotSpec:
    hive: str
    cls_name: str
    config: dict = field(default_factory=dict)


@dataclass
class HiveSpec:
    name: str
    bots: list[BotSpec]


def available_hives() -> list[str]:
    return sorted(p.parent.name for p in HIVES_DIR.glob("*/hive.yml"))


def enabled_hives() -> list[str]:
    """Hives listed in the HIVES env var (comma separated), or all of them."""
    wanted = [h.strip() for h in os.environ.get("HIVES", "").split(",") if h.strip()]
    return wanted or available_hives()


def load_hive(folder: str) -> HiveSpec:
    path = HIVES_DIR / folder / "hive.yml"
    raw = yaml.safe_load(path.read_text()) or {}
    name = raw.get("hive") or folder
    if name != folder:
        raise ValueError(f"{path}: hive name '{name}' should match its folder '{folder}'")
    bots = [BotSpec(name, cls_name, cfg or {}) for cls_name, cfg in (raw.get("bots") or {}).items()]
    return HiveSpec(name, bots)


def find_bot_class(hive: str, cls_name: str):
    """Look for the class in hives/<hive>/bots/*.py first, then the shared bots."""
    from core.bot import Bot

    modules = []
    pkg_name = f"hives.{hive}.bots"
    pkg_dir = HIVES_DIR / hive / "bots"
    if pkg_dir.is_dir():
        for info in pkgutil.iter_modules([str(pkg_dir)]):
            modules.append(f"{pkg_name}.{info.name}")
    modules.append(SHARED_BOTS_MODULE)

    for mod_name in modules:
        mod = importlib.import_module(mod_name)
        cls = getattr(mod, cls_name, None)
        if inspect.isclass(cls) and issubclass(cls, Bot) and cls is not Bot:
            return cls
    raise LookupError(f"no bot class named {cls_name} in hives/{hive}/bots/ or {SHARED_BOTS_MODULE}")
