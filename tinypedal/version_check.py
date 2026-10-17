#  TinyPedal is an open-source overlay application for racing simulation.
#  Copyright (C) 2022-2026 TinyPedal developers, see contributors.md file
#
#  This file is part of TinyPedal.
#
#  This program is free software: you can redistribute it and/or modify
#  it under the terms of the GNU General Public License as published by
#  the Free Software Foundation, either version 3 of the License, or
#  (at your option) any later version.
#
#  This program is distributed in the hope that it will be useful,
#  but WITHOUT ANY WARRANTY; without even the implied warranty of
#  MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
#  GNU General Public License for more details.
#
#  You should have received a copy of the GNU General Public License
#  along with this program.  If not, see <https://www.gnu.org/licenses/>.

"""
Version check function
"""

from __future__ import annotations

import sys

from .constant import DATA


def parse_version_string(ver: str) -> tuple[int, int, int] | tuple[int, int, int, int]:
    """Parse version string to tuple (major, minor, patch, [raceos_build])"""
    try:
        clean = ver.strip().lstrip("v")
        # Support format: "2.51.5-raceos.2" or "2.51.5"
        if "-raceos." in clean:
            base_ver, raceos_ver = clean.split("-raceos.")
            version = base_ver.split(".")
            return int(version[0]), int(version[1]), int(version[2]), int(raceos_ver)
        version = clean.split(".")
        return int(version[0]), int(version[1]), int(version[2])
    except (AttributeError, ValueError, TypeError, IndexError):
        return DATA.VERSION_NA


def is_new_version(
    checked_version: tuple[int, ...],
    current_version: tuple[int, ...],
    version_tag: str,
) -> bool:
    """Is new version"""
    # Invalid version
    if checked_version == DATA.VERSION_NA:
        return False

    # Normalize both versions to 4 elements (major, minor, patch, raceos_build)
    # If version_tag has raceos.X, factor it into current_version if not already there
    cur = list(current_version)
    if len(cur) == 3:
        if version_tag.startswith("raceos."):
            try:
                cur.append(int(version_tag.split("raceos.")[1]))
            except ValueError:
                cur.append(0)
        else:
            cur.append(0)

    chk = list(checked_version)
    if len(chk) == 3:
        chk.append(0)

    cur_tuple = tuple(cur)
    chk_tuple = tuple(chk)

    # New version
    if chk_tuple > cur_tuple:
        return True
    return False


def python() -> str:
    """Python version"""
    return ".".join(map(str, sys.version_info))


def qt() -> str:
    """Qt version"""
    from PySide2.QtCore import qVersion

    return qVersion()


def pyside() -> str:
    """PySide version"""
    import PySide2

    return PySide2.__version__


def psutil() -> str:
    """psutil version"""
    import psutil

    return psutil.__version__
