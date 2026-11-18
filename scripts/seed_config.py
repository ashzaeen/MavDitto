"""Seed config/ with a ready-made starter profile.

    python scripts/seed_config.py                # the UTA profile, into config/
    python scripts/seed_config.py --list         # show the available profiles
    python scripts/seed_config.py --force        # overwrite files that already exist

MavDitto's writing and page-building tools read three files from `config/`:
`brand-voice.json`, `knowledge-base.json` and `components.json`. Those are
git-ignored because they are yours. This script copies a starter set from
`config/seed/<profile>/` so you can try the tools immediately, instead of
running the dashboard's Setup Wizard first.

It never overwrites an existing file unless you pass --force, and it checks
that each seed file is valid JSON before writing anything. Standard library only.
"""
from __future__ import annotations

import argparse
import json
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SEED_DIR = ROOT / "config" / "seed"
CONFIG_FILES = ("brand-voice.json", "knowledge-base.json", "components.json")


def profiles(seed_dir: Path = SEED_DIR) -> list[str]:
    if not seed_dir.is_dir():
        return []
    return sorted(p.name for p in seed_dir.iterdir() if p.is_dir())


def seed(profile: str, *, config_dir: Path, seed_dir: Path = SEED_DIR, force: bool = False) -> dict[str, str]:
    """Copy a profile's files into `config_dir`. Returns {filename: "written" | "kept"}.

    Raises ValueError for an unknown profile or an invalid seed file, before
    anything is written.
    """
    src = seed_dir / profile
    if not src.is_dir():
        raise ValueError(f"unknown profile {profile!r}; available: {', '.join(profiles(seed_dir)) or 'none'}")

    for name in CONFIG_FILES:
        f = src / name
        if not f.is_file():
            raise ValueError(f"profile {profile!r} is missing {name}")
        try:
            json.loads(f.read_text(encoding="utf-8"))
        except json.JSONDecodeError as e:
            raise ValueError(f"{f} is not valid JSON: {e}") from e

    config_dir.mkdir(parents=True, exist_ok=True)
    result: dict[str, str] = {}
    for name in CONFIG_FILES:
        dest = config_dir / name
        if dest.exists() and not force:
            result[name] = "kept"
            continue
        shutil.copyfile(src / name, dest)
        result[name] = "written"
    return result


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Seed config/ with a starter profile.")
    ap.add_argument("--profile", default="uta", help="which profile under config/seed/ (default: uta)")
    ap.add_argument("--config-dir", type=Path, default=ROOT / "config", help="where to write (default: ./config)")
    ap.add_argument("--force", action="store_true", help="overwrite files that already exist")
    ap.add_argument("--list", action="store_true", help="list the available profiles and exit")
    args = ap.parse_args(argv)

    if args.list:
        for p in profiles():
            print(p)
        return 0

    try:
        result = seed(args.profile, config_dir=args.config_dir, force=args.force)
    except ValueError as e:
        print(f"error: {e}", file=sys.stderr)
        return 1

    for name, state in result.items():
        note = "already exists, kept (use --force to overwrite)" if state == "kept" else "written"
        print(f"  {name}: {note}")
    if "kept" in result.values() and "written" not in result.values():
        print("Nothing changed.")
    else:
        print(f"Seeded {args.config_dir} from profile '{args.profile}'.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
