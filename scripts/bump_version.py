#!/usr/bin/env python3
"""Bump the single source of truth for the version: ansiblecli/__init__.py.

Usage:
    python scripts/bump_version.py patch|minor|major [pre-release tag]
    python scripts/bump_version.py --set 2.4.0

Examples:
    make bump                       # 1.1.0 -> 1.1.1
    make bump PART=minor            # 1.1.1 -> 1.2.0
    make bump PART=major            # 1.2.0 -> 2.0.0
"""

import argparse
import re
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
INIT_FILE = REPO_ROOT / "ansiblecli" / "__init__.py"
VERSION_RE = re.compile(r'^__version__\s*=\s*["\'](?P<version>[^"\']+)["\']', re.M)


def read_version():
    match = VERSION_RE.search(INIT_FILE.read_text())
    if not match:
        sys.exit(f"Could not find __version__ in {INIT_FILE}")
    return match.group("version")


def parse(version):
    core, _, suffix = version.partition("-")
    parts = [int(p) for p in core.split(".")]
    while len(parts) < 3:
        parts.append(0)
    return parts, suffix


def bump(version, part):
    (major, minor, patch), _suffix = parse(version)
    if part == "major":
        return f"{major + 1}.0.0"
    if part == "minor":
        return f"{major}.{minor + 1}.0"
    if part == "patch":
        return f"{major}.{minor}.{patch + 1}"
    sys.exit(f"Unknown bump part: {part!r} (use major|minor|patch)")


def write_version(new_version):
    text = INIT_FILE.read_text()
    INIT_FILE.write_text(VERSION_RE.sub(f'__version__ = "{new_version}"', text, count=1))


def main():
    parser = argparse.ArgumentParser(description="Bump the ansiblecli version.")
    parser.add_argument("part", nargs="?", default="patch",
                        choices=["major", "minor", "patch"])
    parser.add_argument("--set", dest="set_version",
                        help="Set an explicit version instead of bumping.")
    parser.add_argument("--dry-run", action="store_true",
                        help="Print the new version without writing it.")
    parser.add_argument("--current", action="store_true",
                        help="Print the current version and exit.")
    args = parser.parse_args()

    current = read_version()
    if args.current:
        print(current)
        return 0

    new = args.set_version or bump(current, args.part)

    if not re.fullmatch(r"\d+\.\d+\.\d+(?:[-.\w]+)?", new):
        sys.exit(f"Refusing to write a non-semver version: {new}")

    if args.dry_run:
        print(new)
        return 0

    write_version(new)
    print(f"{current} -> {new}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
