#!/usr/bin/env python3
"""Apply the fork branding (disguised identity) to this working tree.

The upstream project builds an APK whose package name is
``org.frknkrc44.hma_oss`` and whose Zygisk module is called
``hma_oss_zygisk``.  This fork ships a randomized, unrelated looking identity
instead, while keeping every internal reference consistent, so that

  * the manager APK installs as a normal app with an innocent name/icon,
  * the Zygisk module occupies its own module folder / state dir,
  * consecutive releases keep the SAME identity, which is what makes an
    in-place update over the previously published APK possible.

The mapping is derived from release ``oss-173`` of this fork:

    org.frknkrc44.hma_oss        -> <appId>
    icu.nullptr.hidemyapplist    -> <appId>.legacy
    /data/misc/hide_my_applist_  -> /data/misc/<codename>_state_
    hmaoss.sh                    -> <codename>.sh
    hma_oss_zygisk               -> <codename>
    app_name "HMA-OSS"           -> <appLabel>

Usage:
    python3 scripts/apply_branding.py            # rewrite the tree
    python3 scripts/apply_branding.py --check    # verify, exit 1 on leftovers
    python3 scripts/apply_branding.py --dry-run  # list changes, write nothing

The script is idempotent: a second run changes nothing.
"""

from __future__ import annotations

import argparse
import math
import os
import random
import shutil
import struct
import sys
import zlib
from pathlib import Path

# --------------------------------------------------------------------------
# upstream identifiers
# --------------------------------------------------------------------------

UPSTREAM_APP = "org.frknkrc44.hma_oss"
UPSTREAM_LEGACY = "icu.nullptr.hidemyapplist"
UPSTREAM_DATA_DIR = "/data/misc/hide_my_applist_"
UPSTREAM_DATA_DIR_PLAIN = "/data/misc/hide_my_applist"
UPSTREAM_STATE_TOKEN = "hide_my_applist_"
UPSTREAM_STATE_TOKEN_PLAIN = "hide_my_applist"
UPSTREAM_SCRIPT = "hmaoss.sh"
UPSTREAM_MODULE_ID = "hma_oss_zygisk"
UPSTREAM_LABEL_LINE = '<string name="app_name" translatable="false">HMA-OSS</string>'
UPSTREAM_UPDATE_API = "https://api.github.com/repos/frknkrc44/HMA-OSS/releases/latest"
UPSTREAM_MODULE_UPDATE_JSON = "https://furkank.net/hma_oss_update_checker.json"
UPSTREAM_ARCHIVE_NAME = \
    'archiveName = "${rootProject.name}-ZYGISK-${android.defaultConfig.versionName}"'

# files / dirs that are never rewritten
SKIP_DIRS = {
    ".git",
    ".gradle",
    ".idea",
    "build",
    "external",       # git submodule, third party
    "fastlane",       # store metadata, not part of the APK
    ".github",        # workflow definitions stay upstream-shaped
    "scripts",        # this tool holds the upstream names on purpose
    "__pycache__",
    ".dsh",
}
SKIP_SUFFIXES = {".md", ".png", ".webp", ".jpg", ".jpeg", ".gif", ".jar", ".zip"}
SKIP_NAMES = {"LICENSE.md", "branding.properties"}

# source roots whose java/kotlin packages have to be moved on disk
SOURCE_ROOTS = (
    "app/src/main/java",
    "common/src/main/java",
    "common/src/main/aidl",
    "stub/src/main/java",
    "zygote/src/main/java",
)

ICON_DENSITIES = {
    "mdpi": 108,
    "hdpi": 162,
    "xhdpi": 216,
    "xxhdpi": 324,
    "xxxhdpi": 432,
}


# --------------------------------------------------------------------------
# configuration
# --------------------------------------------------------------------------

class Branding:
    def __init__(self, values: dict[str, str]):
        self.values = values
        self.app_id = values["appid"]
        self.app_label = values["applabel"]
        self.codename = values["codename"]
        self.icon_seed = int(values.get("iconseed", "0"))
        self.author = values.get("author", "unknown")
        self.module_name = values.get("modulename", "HMA-OSS Zygisk")
        self.update_check_api = values.get("updatecheckapi", "")
        self.module_update_json = values.get("moduleupdatejson", "")

    @property
    def app_id_path(self) -> str:
        return self.app_id.replace(".", "/")

    def replacements(self) -> list[tuple[str, str]]:
        """Ordered replacement pairs, most specific first."""
        return [
            (UPSTREAM_APP, self.app_id),
            (UPSTREAM_APP.replace(".", "/"), self.app_id_path),
            (UPSTREAM_LEGACY, self.app_id + ".legacy"),
            (UPSTREAM_LEGACY.replace(".", "/"), self.app_id_path + "/legacy"),
            (UPSTREAM_DATA_DIR, f"/data/misc/{self.codename}_state_"),
            (UPSTREAM_DATA_DIR_PLAIN, f"/data/misc/{self.codename}_state"),
            (UPSTREAM_STATE_TOKEN, f"{self.codename}_state_"),
            (UPSTREAM_STATE_TOKEN_PLAIN, f"{self.codename}_state"),
            (UPSTREAM_SCRIPT, f"{self.codename}.sh"),
            (UPSTREAM_MODULE_ID, self.codename),
            (UPSTREAM_UPDATE_API, self.update_check_api),
        ]

    def extras(self) -> list[tuple[str, str]]:
        return [
            (UPSTREAM_LABEL_LINE,
             f'<string name="app_name" translatable="false">{self.app_label}</string>'),
            ('author = "frknkrc44"', f'author = "{self.author}"'),
            (UPSTREAM_MODULE_UPDATE_JSON, self.module_update_json),
            (UPSTREAM_ARCHIVE_NAME,
             'archiveName = "${rootProject.name}-${android.defaultConfig.versionName}"'),
            ('name = "HMA-OSS Zygisk"', f'name = "{self.module_name}"'),
        ]


def load_branding(root: Path) -> Branding:
    path = root / "branding.properties"
    if not path.is_file():
        raise SystemExit(f"error: {path} not found")

    values: dict[str, str] = {}
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        values[key.strip().lower()] = value.strip()

    missing = [key for key in ("appid", "applabel", "codename") if not values.get(key)]
    if missing:
        raise SystemExit(f"error: branding.properties misses {', '.join(missing)}")
    return Branding(values)


# --------------------------------------------------------------------------
# text rewriting
# --------------------------------------------------------------------------

def iter_text_files(root: Path):
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [name for name in dirnames if name not in SKIP_DIRS]
        for name in filenames:
            path = Path(dirpath) / name
            if name in SKIP_NAMES:
                continue
            if path.suffix.lower() in SKIP_SUFFIXES:
                continue
            yield path


def rewrite_texts(root: Path, branding: Branding, dry_run: bool) -> list[str]:
    pairs = branding.replacements() + branding.extras()
    changed: list[str] = []

    for path in iter_text_files(root):
        try:
            text = path.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            continue
        new = text
        for old, replacement in pairs:
            if old and old in new:
                new = new.replace(old, replacement)
        if new != text:
            changed.append(str(path.relative_to(root)))
            if not dry_run:
                path.write_text(new, encoding="utf-8")
    return changed


# --------------------------------------------------------------------------
# package directories / asset file names
# --------------------------------------------------------------------------

def prune_empty(path: Path, stop: Path) -> None:
    while path != stop and path.is_dir() and not any(path.iterdir()):
        path.rmdir()
        path = path.parent


def move_package_dirs(root: Path, branding: Branding, dry_run: bool) -> list[str]:
    moves: list[str] = []
    pairs = [
        ("org/frknkrc44/hma_oss", branding.app_id_path),
        ("icu/nullptr/hidemyapplist", branding.app_id_path + "/legacy"),
    ]

    for base_rel in SOURCE_ROOTS:
        base = root / base_rel
        if not base.is_dir():
            continue
        for old_rel, new_rel in pairs:
            old = base / old_rel
            if not old.is_dir():
                continue
            new = base / new_rel
            moves.append(f"{old.relative_to(root)} -> {new.relative_to(root)}")
            if dry_run:
                continue
            new.parent.mkdir(parents=True, exist_ok=True)
            if new.exists():
                # merge into an existing tree (keeps already-moved files)
                shutil.copytree(old, new, dirs_exist_ok=True)
                shutil.rmtree(old)
            else:
                shutil.move(str(old), str(new))
            prune_empty(old.parent, base)
    return moves


def rename_assets(root: Path, branding: Branding, dry_run: bool) -> list[str]:
    moves: list[str] = []
    assets = root / "zygote/src/main/assets"
    if not assets.is_dir():
        return moves
    for path in sorted(assets.rglob(f"*{UPSTREAM_SCRIPT}")):
        if not path.is_file():
            continue
        target = path.with_name(path.name.replace(UPSTREAM_SCRIPT, f"{branding.codename}.sh"))
        moves.append(f"{path.relative_to(root)} -> {target.relative_to(root)}")
        if not dry_run:
            path.rename(target)
    return moves


# --------------------------------------------------------------------------
# launcher icon
# --------------------------------------------------------------------------

def _png_chunk(tag: bytes, data: bytes) -> bytes:
    return (
        struct.pack(">I", len(data))
        + tag
        + data
        + struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF)
    )


def write_png(path: Path, width: int, height: int, pixels: bytes) -> None:
    """pixels: RGBA bytes, row-major, no filter bytes."""

    raw = bytearray()
    stride = width * 4
    for y in range(height):
        raw.append(0)  # filter: none
        raw += pixels[y * stride:(y + 1) * stride]

    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(
        b"\x89PNG\r\n\x1a\n"
        + _png_chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 6, 0, 0, 0))
        + _png_chunk(b"IDAT", zlib.compress(bytes(raw), 9))
        + _png_chunk(b"IEND", b"")
    )


def _hsv(h: float, s: float, v: float) -> tuple[float, float, float]:
    h = h % 360.0
    c = v * s
    x = c * (1 - abs((h / 60.0) % 2 - 1))
    m = v - c
    index = int(h // 60) % 6
    r, g, b = [
        (c, x, 0.0), (x, c, 0.0), (0.0, c, x),
        (0.0, x, c), (x, 0.0, c), (c, 0.0, x),
    ][index]
    return r + m, g + m, b + m


def _to_rgb(color: tuple[float, float, float]) -> tuple[int, int, int]:
    return tuple(max(0, min(255, int(round(c * 255)))) for c in color)  # type: ignore[return-value]


class Canvas:
    """Supersampled rasterizer working in normalized 0..1 coordinates."""

    def __init__(self, size: int, samples: int = 3):
        self.size = size
        self.samples = samples
        self.buf = bytearray(size * size * 4)

    def _blend(self, index: int, rgb: tuple[float, float, float], alpha: float) -> None:
        if alpha <= 0:
            return
        r, g, b = _to_rgb(rgb)
        a = min(1.0, max(0.0, alpha))
        offset = index * 4
        dst_a = self.buf[offset + 3] / 255.0
        out_a = a + dst_a * (1 - a)
        if out_a <= 0:
            return
        for channel, value in enumerate((r, g, b)):
            dst = self.buf[offset + channel] / 255.0
            src = value / 255.0
            self.buf[offset + channel] = int(round(
                (src * a + dst * dst_a * (1 - a)) / out_a * 255
            ))
        self.buf[offset + 3] = int(round(out_a * 255))

    def fill(self, inside, rgb, alpha: float = 1.0) -> None:
        size = self.size
        samples = self.samples
        step = 1.0 / size
        sub_step = step / samples
        total = samples * samples
        for py in range(size):
            for px in range(size):
                hits = 0
                for sy in range(samples):
                    y = py * step + (sy + 0.5) * sub_step
                    for sx in range(samples):
                        x = px * step + (sx + 0.5) * sub_step
                        if inside(x, y):
                            hits += 1
                if hits:
                    self._blend(py * size + px, rgb, alpha * hits / total)


def _poly_contains(cx, cy, radius, sides, rotation, x, y) -> bool:
    dx, dy = x - cx, y - cy
    distance = math.hypot(dx, dy)
    if distance > radius:
        return False
    if distance == 0:
        return True
    segment = 2 * math.pi / sides
    angle = (math.atan2(dy, dx) - rotation) % segment
    delta = min(angle, segment - angle)
    limit = radius * math.cos(segment / 2) / math.cos(segment / 2 - delta)
    return distance <= abs(limit)


def _segment_distance(px, py, ax, ay, bx, by) -> float:
    dx, dy = bx - ax, by - ay
    length_sq = dx * dx + dy * dy
    if length_sq == 0:
        return math.hypot(px - ax, py - ay)
    t = max(0.0, min(1.0, ((px - ax) * dx + (py - ay) * dy) / length_sq))
    return math.hypot(px - (ax + t * dx), py - (ay + t * dy))


def _palette(rnd: random.Random) -> tuple[tuple[float, float, float], tuple[float, float, float], tuple[float, float, float]]:
    """Pick a tasteful (background, glyph, accent) trio."""

    hue = rnd.uniform(0, 360)
    analog = (hue + rnd.choice((-28, -18, 18, 28))) % 360

    if rnd.random() < 0.6:          # deep background, light glyph
        background = _hsv(hue, rnd.uniform(0.42, 0.70), rnd.uniform(0.32, 0.46))
        glyph = _hsv(hue, 0.03, 0.98)
        accent = _hsv(analog, rnd.uniform(0.55, 0.75), 0.97)
    else:                           # light background, dark glyph
        background = _hsv(hue, rnd.uniform(0.10, 0.22), rnd.uniform(0.94, 0.99))
        glyph = _hsv(hue, rnd.uniform(0.72, 0.88), rnd.uniform(0.34, 0.48))
        accent = _hsv(analog, rnd.uniform(0.78, 0.92), rnd.uniform(0.62, 0.78))
    return background, glyph, accent


def draw_icon(size: int, seed: int) -> tuple[Canvas, tuple[int, int, int]]:
    rnd = random.Random(seed)

    background, glyph, accent = _palette(rnd)
    canvas = Canvas(size)
    center = 0.5
    radius = 0.29           # inside the adaptive icon safe zone
    family = rnd.randrange(5)

    if family == 0:         # orbit: ring + satellite + core
        orbit = rnd.uniform(0.0, math.tau)
        canvas.fill(
            lambda x, y: radius * 0.64 <= math.hypot(x - center, y - center) <= radius,
            glyph,
        )
        dot_x = center + math.cos(orbit) * radius * 0.80
        dot_y = center + math.sin(orbit) * radius * 0.80
        canvas.fill(
            lambda x, y: math.hypot(x - dot_x, y - dot_y) <= radius * 0.24,
            accent,
        )
        canvas.fill(
            lambda x, y: math.hypot(x - center, y - center) <= radius * 0.18,
            glyph,
        )
    elif family == 1:       # stacked rounded bars
        angle = rnd.uniform(-0.45, 0.45)
        half_thick = radius * 0.105
        half_len = radius * 0.50
        nx, ny = -math.sin(angle), math.cos(angle)   # stacking axis
        dx, dy = -ny, nx                             # bar axis
        for index in (-1, 0, 1):
            offset = index * radius * 0.42
            cx = center + nx * offset
            cy = center + ny * offset
            ax, ay = cx - dx * half_len, cy - dy * half_len
            bx, by = cx + dx * half_len, cy + dy * half_len
            colour = accent if index == 0 else glyph
            canvas.fill(
                lambda x, y, ax=ax, ay=ay, bx=bx, by=by, t=half_thick: (
                    _segment_distance(x, y, ax, ay, bx, by) <= t
                ),
                colour,
            )
    elif family == 2:       # polygon ring + core
        sides = rnd.choice((3, 5, 6))
        rotation = rnd.uniform(0, math.tau)
        canvas.fill(
            lambda x, y: _poly_contains(center, center, radius, sides, rotation, x, y)
            and not _poly_contains(center, center, radius * 0.70, sides, rotation, x, y),
            glyph,
        )
        canvas.fill(
            lambda x, y: _poly_contains(center, center, radius * 0.34, sides, rotation, x, y),
            accent,
        )
    elif family == 3:       # venn
        offset = radius * 0.40
        canvas.fill(
            lambda x, y: math.hypot(x - (center - offset), y - center) <= radius * 0.72,
            glyph,
            0.95,
        )
        canvas.fill(
            lambda x, y: math.hypot(x - (center + offset), y - center) <= radius * 0.72,
            accent,
            0.85,
        )
    else:                   # open ring + head dot
        gap = rnd.uniform(0.8, 1.3)
        sweep_start = rnd.uniform(0, math.tau)
        inner = radius * 0.60

        def ring(x, y):
            dx, dy = x - center, y - center
            distance = math.hypot(dx, dy)
            if not inner <= distance <= radius:
                return False
            return (math.atan2(dy, dx) - sweep_start) % math.tau > gap

        canvas.fill(ring, glyph)
        head_x = center + math.cos(sweep_start + gap) * (radius + inner) / 2
        head_y = center + math.sin(sweep_start + gap) * (radius + inner) / 2
        canvas.fill(
            lambda x, y: math.hypot(x - head_x, y - head_y) <= (radius - inner) * 0.62,
            accent,
        )

    return canvas, _to_rgb(background)


def _downscale(pixels: bytes, source: int, target: int) -> bytes:
    """Box filter downscale of RGBA data (alpha weighted to avoid fringes)."""

    factor = source / target
    out = bytearray(target * target * 4)
    for ty in range(target):
        y0 = int(ty * factor)
        y1 = max(y0 + 1, int((ty + 1) * factor))
        for tx in range(target):
            x0 = int(tx * factor)
            x1 = max(x0 + 1, int((tx + 1) * factor))
            r = g = b = a = 0.0
            count = 0
            for sy in range(y0, y1):
                row = sy * source
                for sx in range(x0, x1):
                    offset = (row + sx) * 4
                    alpha = pixels[offset + 3] / 255.0
                    r += pixels[offset] * alpha
                    g += pixels[offset + 1] * alpha
                    b += pixels[offset + 2] * alpha
                    a += alpha
                    count += 1
            offset = (ty * target + tx) * 4
            if a <= 0 or count == 0:
                continue
            out[offset] = int(round(r / a))
            out[offset + 1] = int(round(g / a))
            out[offset + 2] = int(round(b / a))
            out[offset + 3] = int(round(a / count * 255))
    return bytes(out)


def write_icons(root: Path, branding: Branding) -> list[str]:
    res = root / "app/src/main/res"
    written: list[str] = []

    master = 432
    canvas, background = draw_icon(master, branding.icon_seed)
    hex_color = "#%02X%02X%02X" % background

    for density, size in ICON_DENSITIES.items():
        target = res / f"mipmap-{density}" / "brand_icon_foreground.png"
        pixels = bytes(canvas.buf) if size == master else _downscale(canvas.buf, master, size)
        write_png(target, size, size, pixels)
        written.append(str(target.relative_to(root)))

    adaptive = res / "mipmap-anydpi-v26" / "ic_launcher.xml"
    adaptive.parent.mkdir(parents=True, exist_ok=True)
    adaptive.write_text(
        '<?xml version="1.0" encoding="utf-8"?>\n'
        '<adaptive-icon xmlns:android="http://schemas.android.com/apk/res/android">\n'
        '    <background android:drawable="@color/brand_icon_background"/>\n'
        '    <foreground android:drawable="@mipmap/brand_icon_foreground"/>\n'
        '</adaptive-icon>\n',
        encoding="utf-8",
    )
    written.append(str(adaptive.relative_to(root)))

    colors = res / "values" / "brand_icon.xml"
    colors.parent.mkdir(parents=True, exist_ok=True)
    colors.write_text(
        '<?xml version="1.0" encoding="utf-8"?>\n'
        "<resources>\n"
        f'    <color name="brand_icon_background">{hex_color}</color>\n'
        "</resources>\n",
        encoding="utf-8",
    )
    written.append(str(colors.relative_to(root)))
    return written


# --------------------------------------------------------------------------
# verification
# --------------------------------------------------------------------------

def check(root: Path, branding: Branding) -> list[str]:
    problems: list[str] = []
    needles = [
        UPSTREAM_APP,
        UPSTREAM_LEGACY,
        UPSTREAM_DATA_DIR_PLAIN,
        UPSTREAM_STATE_TOKEN_PLAIN,
        UPSTREAM_SCRIPT,
        UPSTREAM_MODULE_ID,
    ]
    for path in iter_text_files(root):
        try:
            text = path.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            continue
        for needle in needles:
            if needle in text:
                problems.append(f"{path.relative_to(root)}: {needle}")

    # a couple of high value spot checks
    gradle = (root / "build.gradle.kts").read_text(encoding="utf-8")
    if f'val appPackageName = "{branding.app_id}"' not in gradle:
        problems.append("build.gradle.kts: appPackageName is not branded")

    strings = (root / "app/src/main/res/values/strings.xml").read_text(encoding="utf-8")
    expected_label_line = (
        f'<string name="app_name" translatable="false">{branding.app_label}</string>'
    )
    if expected_label_line not in strings:
        problems.append("app/src/main/res/values/strings.xml: app_name is not branded")

    zygote = (root / "zygote/build.gradle.kts").read_text(encoding="utf-8")
    if f'id = "{branding.codename}"' not in zygote:
        problems.append("zygote/build.gradle.kts: module id is not branded")

    if not (root / "app/src/main/res/mipmap-anydpi-v26/ic_launcher.xml").is_file():
        problems.append("app launcher icon is missing")

    return problems


# --------------------------------------------------------------------------
# main
# --------------------------------------------------------------------------

def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--root", default=Path(__file__).resolve().parent.parent, type=Path)
    parser.add_argument("--check", action="store_true", help="only verify the branding")
    parser.add_argument("--dry-run", action="store_true", help="list changes, write nothing")
    args = parser.parse_args(argv)

    root: Path = args.root.resolve()
    branding = load_branding(root)

    if args.check:
        problems = check(root, branding)
        if problems:
            print("branding check FAILED:", file=sys.stderr)
            for item in problems[:40]:
                print("  " + item, file=sys.stderr)
            if len(problems) > 40:
                print(f"  ... and {len(problems) - 40} more", file=sys.stderr)
            return 1
        print(f"branding check OK ({branding.app_id} / {branding.app_label} / {branding.codename})")
        return 0

    changed = rewrite_texts(root, branding, args.dry_run)
    moves = move_package_dirs(root, branding, args.dry_run)
    assets = rename_assets(root, branding, args.dry_run)

    print(f"identity: {branding.app_id}")
    print(f"label:    {branding.app_label}")
    print(f"module:   {branding.codename}")
    print(f"rewritten files: {len(changed)}")
    for item in moves + assets:
        print("  move " + item)

    if args.dry_run:
        return 0

    written = write_icons(root, branding)
    print(f"generated icon files: {len(written)}")

    problems = check(root, branding)
    if problems:
        print("branding check FAILED after rewrite:", file=sys.stderr)
        for item in problems[:40]:
            print("  " + item, file=sys.stderr)
        return 1
    print("branding applied")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
