#!/usr/bin/env python3
"""Apply / verify this fork's identity on an upstream worktree.

The fork never commits changes to upstream's own files: a pristine upstream
checkout (a branch, a tag or a single upstream commit) is transformed at build
time by this script.  That keeps `git rebase upstream/master` conflict-free and
makes every release reproducible from (upstream commit + fork/fork.env).

    scripts/fork_identity.py apply   [--root DIR] [--dry-run] [--check-anchors]
    scripts/fork_identity.py verify  [--root DIR]

Exit status is non-zero when a required anchor is missing, when a rename cannot
be performed, or when upstream identity strings survive in the build inputs.

Three mechanisms are used, in this order:

1. token substitution   - package names, module id, URLs, state directory, ...
2. resource scrubbing   - fork/strings-sanitize.tsv (token rules per locale) and
                          fork/strings-override.tsv (whole string overrides)
                          remove brand words from the shipped UI text
3. literal hiding       - literals that must survive at runtime (package names
                          of *other* apps, e.g. the original Hide My Applist, the
                          original Magisk manager) are base64 encoded and decoded
                          at runtime by a generated helper, so they no longer
                          appear as plain strings in the built artifacts
"""

from __future__ import annotations

import argparse
import base64
import re
import shutil
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent

# Only build inputs are rewritten.  Documentation, credits, fastlane metadata
# and the licence are left untouched on purpose: they carry the upstream
# attribution that AGPL-3.0 requires.
PATCH_SCOPE_GLOBS = (
    "build.gradle.kts",
    "settings.gradle.kts",
    "gradle.properties",
    "gradle/libs.versions.toml",
    "app/build.gradle.kts",
    "common/build.gradle.kts",
    "stub/build.gradle.kts",
    "zygote/build.gradle.kts",
    "app/proguard-rules.pro",
    "common/proguard-rules.pro",
    "stub/proguard-rules.pro",
    "zygote/proguard-rules.pro",
    "app/src/**/*",
    "common/src/**/*",
    "stub/src/**/*",
    "zygote/src/**/*",
)

TEXT_SUFFIXES = {
    ".kt", ".java", ".kts", ".gradle", ".xml", ".aidl", ".pro",
    ".sh", ".json", ".properties", ".toml", ".txt", ".md",
}

UPSTREAM_PACKAGE = "org.frknkrc44.hma_oss"
UPSTREAM_PACKAGE_PATH = "org/frknkrc44/hma_oss"
UPSTREAM_LEGACY = "icu.nullptr.hidemyapplist"
UPSTREAM_LEGACY_PATH = "icu/nullptr/hidemyapplist"
UPSTREAM_STUB_NS = "org.frknkrc44.stub"
UPSTREAM_MODULE_ID = "hma_oss_zygisk"
UPSTREAM_MODULE_NAME = "HMA-OSS Zygisk"
UPSTREAM_MODULE_AUTHOR = "frknkrc44"
UPSTREAM_MODULE_DESC = "A Zygisk backend for HMA-OSS"
UPSTREAM_STATE_PREFIX = "hide_my_applist"
UPSTREAM_BOOT_SCRIPT = "hmaoss.sh"
UPSTREAM_FRAMEWORK_CHECK = "22-check-zygisk.sh"
UPSTREAM_PROJECT_NAME = "HMA-OSS"
UPSTREAM_UPDATE_JSON = "https://furkank.net/hma_oss_update_checker.json"
UPSTREAM_RELEASE_API = "https://api.github.com/repos/frknkrc44/HMA-OSS/releases/latest"
UPSTREAM_REPO_URL = "https://github.com/frknkrc44/HMA-OSS"
UPSTREAM_WIKI_URL = "https://github.com/frknkrc44/HMA-OSS/wiki/About-HMA%E2%80%90OSS"
UPSTREAM_TRANSLATE_URL = "https://crowdin.com/project/frknkrc44-hma-oss"
UPSTREAM_TRANSLATORS_URL = "https://github.com/frknkrc44/HMA-OSS/releases/latest/download/translators.json"

# Build-time only references that must keep their upstream spelling: they never
# reach an artifact, and the translator avatar fetch has to work before this
# fork has published anything.  Masked while the token phase runs so the brand
# rule cannot mangle them.
PROTECTED_LITERALS = (UPSTREAM_TRANSLATORS_URL,)

# Terms that must not survive in the artifacts.  Anything that is only needed
# because a *third party* component defines it is handled case by case (see
# RESIDUE_NOTE / the allow lists in scripts/fork_verify_artifacts.sh).
BANNED_TERMS = ("magisk", "zygisk", "lsposed", "hidemyapplist", "frknkrc44", "hmal")
BANNED_RE = re.compile("|".join(BANNED_TERMS), re.I)
# Checks that must stay case sensitive: a case insensitive "hma" would also
# match HashMap / WeakHashMap.  "HMA" itself is *this* fork's product name (the
# project is named after upstream), so it is not listed here.
BANNED_CASE_SENSITIVE = ("hma_", "hmaApp", "hmaoss")

# Gradle/Android paths are shell-safe, no quoting needed.
MODULE_BLOCK_KEYS = ("id", "name", "author", "description")

# Source directories that follow their java package name:
# (source path, destination template)
DIR_MOVES = (
    ("app/src/main/java/" + UPSTREAM_PACKAGE_PATH, "app/src/main/java/{app}"),
    ("zygote/src/main/java/" + UPSTREAM_PACKAGE_PATH, "zygote/src/main/java/{app}"),
    ("app/src/main/java/" + UPSTREAM_LEGACY_PATH, "app/src/main/java/{legacy}"),
    ("common/src/main/java/" + UPSTREAM_LEGACY_PATH, "common/src/main/java/{legacy}"),
    ("common/src/main/aidl/" + UPSTREAM_LEGACY_PATH, "common/src/main/aidl/{legacy}"),
)

FILE_RENAMES = (
    (f"zygote/src/main/assets/{UPSTREAM_BOOT_SCRIPT}", "zygote/src/main/assets/{boot_script}"),
    (
        f"zygote/src/main/assets/customize.d/{UPSTREAM_FRAMEWORK_CHECK}",
        "zygote/src/main/assets/customize.d/22-check-framework.sh",
    ),
)

# Substitutions valid for one file only.  `{placeholder}` is filled with values
# from build_identity(); patterns containing literal braces are safe because the
# replacement uses a plain placeholder syntax, not str.format on the pattern.
FILE_SCOPED_SUBSTITUTIONS: dict[str, tuple[tuple[str, str, str], ...]] = {
    "settings.gradle.kts": (
        (f'rootProject.name = "{UPSTREAM_PROJECT_NAME}"', 'rootProject.name = "{project_name}"',
         "gradle root project name"),
    ),
    "zygote/build.gradle.kts": (
        ('archiveName = "${rootProject.name}-ZYGISK-${android.defaultConfig.versionName}"',
         'archiveName = "${rootProject.name}-${android.defaultConfig.versionName}"',
         "module archive name"),
    ),
    "fragment_about.xml": (
        ("@+id/list_hma_oss", "@+id/list_maintainers", "about view id"),
    ),
    "AboutFragment.kt": (
        ("binding.listHmaOss", "binding.listMaintainers", "about view id (kotlin)"),
        ('addDevItem(this, R.drawable.cont_fk, "frknkrc44", "HMA-OSS Developer", "https://github.com/frknkrc44")',
         'addDevItem(this, R.drawable.cont_fk, "Upstream", "Original project (AGPL-3.0)", "{fork_url}")',
         "about credits (upstream author)"),
        ('"HMA-OSS Alt Icon Designer"', '"Alt icon designer"', "about credits (role)"),
        ('"HMA-OSS Contributor"', '"Contributor"', "about credits (role)"),
        ('"HMA Developer"', '"Original developer"', "about credits (role)"),
        ('"HMA Collaborator"', '"Collaborator"', "about credits (role)"),
        ('"HMA Icon Designer"', '"Icon designer"', "about credits (role)"),
        ('"HMA Idea Provider"', '"Idea provider"', "about credits (role)"),
    ),
    "HomeFragment.kt": ((UPSTREAM_WIKI_URL, "{docs_url}", "help link"),),
    "StatsFragment.kt": ((UPSTREAM_WIKI_URL, "{docs_url}", "help link"),),
    "BulkConfigWizardFragment.kt": ((UPSTREAM_WIKI_URL, "{docs_url}", "help link"),),
    "Constants.kt": ((UPSTREAM_TRANSLATE_URL, "{fork_url}", "translate link"),),
}

# Files whose string literals are hidden behind a runtime decoder.  Only
# literals that must keep their exact runtime value are affected.
OBFUSCATE_FILES = (
    "common/src/main/java/icu/nullptr/hidemyapplist/common/Utils.kt",
    "common/src/main/java/icu/nullptr/hidemyapplist/common/app_presets/RootAppsPreset.kt",
    "common/src/main/java/icu/nullptr/hidemyapplist/common/app_presets/DetectorAppsPreset.kt",
)
OBFUSCATE_HELPER = '''
private fun unhide(encoded: String): String = String(
    android.util.Base64.decode(encoded, android.util.Base64.DEFAULT),
    Charsets.UTF_8,
)
'''

# Installer script: user visible text loses the framework words, while the
# environment variables / binaries the framework itself defines are kept.
INSTALLER_SUBSTITUTIONS = (
    ("ZYGISK_MULTI_ERR", "FW_MULTI_ERR", "installer variable"),
    ("ZYGISK_NOT_FOUND_ERR", "FW_NOT_FOUND_ERR", "installer variable"),
    ("ZYGISK_DETECTED_MSG", "FW_DETECTED_MSG", "installer variable"),
    ("FALLBACK_ZYGISK_NAME", "FALLBACK_FW_NAME", "installer variable"),
    ("MAGISK_ZYGISK", "MAGISK_OFF", "installer variable"),
    ('FALLBACK_FW_NAME="Zygisk"', 'FALLBACK_FW_NAME="module framework"', "installer fallback label"),
    ("! Multiple Zygisk frameworks were found. Aborting installation to prevent conflicts",
     "! Multiple module frameworks were found. Aborting installation to prevent conflicts",
     "installer message"),
    ("! No known Zygisk frameworks (e.g. ZygiskNext) is found, HMA-OSS requires Zygisk to work. Installation aborted",
     "! No known module framework was found. Installation aborted", "installer message"),
    ("! 检测到多个 Zygisk 框架, 为了避免冲突, 安装程序已退出",
     "! 检测到多个模块框架, 为了避免冲突, 安装程序已退出", "installer message"),
    ("! 未找到已知的 Zygisk 框架 (例如 ZygiskNext), HMA-OSS 需要 Zygisk 才能正常运行, 安装程序已退出",
     "! 未找到已知的模块框架, 安装程序已退出", "installer message"),
)

# Files that must contain `anchor` before the patch runs; a missing anchor means
# upstream restructured something and the patch would silently do nothing.
ANCHORS = (
    ("build.gradle.kts", f'val appPackageName by extra("{UPSTREAM_PACKAGE}")'),
    ("build.gradle.kts", 'val gitCommitCount = "git rev-list refs/remotes/origin/master --count"'),
    ("settings.gradle.kts", f'rootProject.name = "{UPSTREAM_PROJECT_NAME}"'),
    ("zygote/build.gradle.kts", f'id = "{UPSTREAM_MODULE_ID}"'),
    ("zygote/build.gradle.kts", f'name = "{UPSTREAM_MODULE_NAME}"'),
    ("zygote/build.gradle.kts", f'updateJson = "{UPSTREAM_UPDATE_JSON}"'),
    ("zygote/build.gradle.kts", f'"{UPSTREAM_PACKAGE_PATH}/zygote/Magic.java"'),
    ("app/src/main/java/icu/nullptr/hidemyapplist/data/AppConstants.kt",
     f'UPDATE_CHECK_URL = "{UPSTREAM_RELEASE_API}"'),
    ("zygote/src/main/assets/" + UPSTREAM_BOOT_SCRIPT, f"MODDIR=/data/adb/modules/{UPSTREAM_MODULE_ID}"),
    ("zygote/src/main/assets/customize.d/" + UPSTREAM_FRAMEWORK_CHECK, "ZYGISK_ENABLED"),
    ("common/src/main/aidl/" + UPSTREAM_LEGACY_PATH + "/common/IHMAService.aidl",
     f"package {UPSTREAM_LEGACY}.common;"),
    ("app/build.gradle.kts", UPSTREAM_TRANSLATORS_URL),
    ("common/src/main/java/icu/nullptr/hidemyapplist/common/Constants.kt", UPSTREAM_TRANSLATE_URL),
    ("common/src/main/java/icu/nullptr/hidemyapplist/common/Utils.kt", "com.tsng.hidemyapplist"),
)

LITERAL_RE = re.compile(r'"((?:[^"\\]|\\.)*)"')


class ForkError(RuntimeError):
    pass


def load_config(path: Path) -> dict[str, str]:
    cfg: dict[str, str] = {}
    for lineno, raw in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if "=" not in line:
            raise ForkError(f"{path}:{lineno}: expected KEY=VALUE, got {raw!r}")
        key, value = line.split("=", 1)
        cfg[key.strip()] = value.strip()
    return cfg


def load_tsv(path: Path) -> list[tuple[str, str]]:
    rows: list[tuple[str, str]] = []
    if not path.is_file():
        return rows
    for lineno, raw in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        if not raw.strip() or raw.lstrip().startswith("#"):
            continue
        parts = raw.split("\t")
        if len(parts) < 2:
            raise ForkError(f"{path}:{lineno}: expected two tab separated columns")
        # the pattern keeps its exact spelling, the value may be empty
        rows.append((parts[0], "\t".join(parts[1:]).rstrip()))
    return rows


def build_identity(cfg: dict[str, str]) -> dict[str, str]:
    required = (
        "FORK_OWNER", "FORK_REPO", "UPSTREAM_SLUG", "APP_ID", "LEGACY_NS",
        "PROJECT_NAME", "APP_NAME", "MODULE_ID", "MODULE_NAME",
        "MODULE_AUTHOR", "MODULE_DESC", "STATE_PREFIX",
    )
    missing = [key for key in required if not cfg.get(key)]
    if missing:
        raise ForkError("fork/fork.env is missing: " + ", ".join(missing))

    app_id = cfg["APP_ID"]
    legacy_ns = cfg["LEGACY_NS"]
    pkg_re = re.compile(r"^[a-z][a-z0-9_]*(\.[a-z][a-z0-9_]*)+$")
    if not pkg_re.match(app_id):
        raise ForkError(f"APP_ID {app_id!r} is not a valid java package name")
    if not pkg_re.match(legacy_ns):
        raise ForkError(f"LEGACY_NS {legacy_ns!r} is not a valid java package name")
    if not legacy_ns.startswith(app_id + "."):
        raise ForkError(f"LEGACY_NS {legacy_ns!r} must be a child of APP_ID {app_id!r}")
    token_re = re.compile(r"^[a-zA-Z][a-zA-Z0-9_]*$")
    for key, value in (("MODULE_ID", cfg["MODULE_ID"]), ("STATE_PREFIX", cfg["STATE_PREFIX"])):
        if not token_re.match(value):
            raise ForkError(f"{key} {value!r} must match {token_re.pattern}")
    # MODULE_NAME / MODULE_DESC are deliberately upstream spelled (the module
    # shows up as the original one in the manager), so they are not checked here
    for key in ("APP_ID", "LEGACY_NS", "MODULE_ID", "STATE_PREFIX",
                "PROJECT_NAME", "APP_NAME"):
        if BANNED_RE.search(cfg[key]):
            raise ForkError(f"{key} {cfg[key]!r} still contains a banned term "
                            f"({'/'.join(BANNED_TERMS)})")

    fork_url = f"https://github.com/{cfg['FORK_OWNER']}/{cfg['FORK_REPO']}"
    return {
        **cfg,
        "FORK_URL": fork_url,
        "APP_ID_PATH": app_id.replace(".", "/"),
        "LEGACY_NS_PATH": legacy_ns.replace(".", "/"),
        "STUB_NS": f"{app_id}.stub",
        "BOOT_SCRIPT": f"{cfg['MODULE_ID']}.sh",
        "UPDATE_JSON_URL": f"{fork_url}/releases/latest/download/update.json",
        "RELEASE_API_URL": f"https://api.github.com/repos/{cfg['FORK_OWNER']}/{cfg['FORK_REPO']}/releases/latest",
        "DOCS_URL": f"{fork_url}/blob/master/FORK.md",
    }


def iter_scope_files(root: Path):
    seen: set[Path] = set()
    for pattern in PATCH_SCOPE_GLOBS:
        for path in sorted(root.glob(pattern)):
            if not path.is_file() or path in seen:
                continue
            seen.add(path)
            yield path


def fill(template: str, ident: dict[str, str]) -> str:
    out = template
    for key, value in ident.items():
        out = out.replace("{" + key.lower() + "}", value)
    return out


def patch_text_files(root: Path, ident: dict[str, str], dry_run: bool) -> tuple[dict[str, int], list[str]]:
    # phase 1: URLs (the bare repo URL rule must not eat the more specific ones)
    url_substitutions = [
        (UPSTREAM_RELEASE_API, ident["RELEASE_API_URL"], "app update-check API"),
        (UPSTREAM_UPDATE_JSON, ident["UPDATE_JSON_URL"], "module update json"),
        (re.compile(r"https://github\.com/frknkrc44/HMA-OSS(?![-\w/])"), ident["FORK_URL"], "repo url"),
    ]
    # phase 3: everything else.  Runs after the file scoped rules so those can
    # still match the original upstream spelling (e.g. "HMA-OSS Developer").
    token_substitutions = [
        # packages: the path form and the dotted form never overlap
        (UPSTREAM_PACKAGE_PATH, ident["APP_ID_PATH"], "package path"),
        (UPSTREAM_LEGACY_PATH, ident["LEGACY_NS_PATH"], "legacy package path"),
        (UPSTREAM_PACKAGE, ident["APP_ID"], "applicationId / namespace"),
        (UPSTREAM_LEGACY, ident["LEGACY_NS"], "legacy namespace"),
        (UPSTREAM_STUB_NS, ident["STUB_NS"], "stub namespace"),
        (UPSTREAM_PROJECT_NAME, ident["PROJECT_NAME"], "product brand"),
        ("HMA-UserService", f'{ident["PROJECT_NAME"]}-Service', "log tag"),
        ("HMA-Service", f'{ident["PROJECT_NAME"]}-Service', "log tag"),
        ("HMA-Bridge", f'{ident["PROJECT_NAME"]}-Bridge', "log tag"),
        ("HMA service initialized", "service initialized", "log text"),
        ("HMAServiceDataHolder", "BridgeServiceDataHolder", "class name"),
        ("IHMAService", "IBridgeService", "aidl interface name"),
        ("HMAService", "BridgeService", "class name"),
        ("hmaApp", "managerApp", "application property"),
        (re.compile(r"list_hma(?!_oss)"), "list_upstream_devs", "about view id"),
        (re.compile(r"listHma(?!Oss)"), "listUpstreamDevs", "about view id (kotlin)"),
        (UPSTREAM_MODULE_ID, ident["MODULE_ID"], "magisk module id"),
        (UPSTREAM_STATE_PREFIX, ident["STATE_PREFIX"], "system service state dir"),
        (UPSTREAM_BOOT_SCRIPT, ident["BOOT_SCRIPT"], "boot script name"),
    ]

    if ident["PROJECT_NAME"] == UPSTREAM_PROJECT_NAME:
        # the fork keeps the upstream project name: nothing to rebrand, and
        # upstream's own product strings stay exactly as they are
        skip = {"product brand", "log tag", "log text"}
        token_substitutions = [rule for rule in token_substitutions if rule[2] not in skip]

    counts: dict[str, int] = {label: 0 for _, _, label in url_substitutions + token_substitutions}
    counts["app_name string"] = 0
    for key in MODULE_BLOCK_KEYS:
        counts[f"module {key} field"] = 0
    touched: list[str] = []

    for path in iter_scope_files(root):
        if path.suffix not in TEXT_SUFFIXES:
            continue
        try:
            original = path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            continue
        text = original

        # protect build-time-only upstream references from the token phase
        masked: dict[str, str] = {}
        for index, literal in enumerate(PROTECTED_LITERALS):
            if literal in text:
                sentinel = f"\x01protected{index}\x01"
                masked[sentinel] = literal
                text = text.replace(literal, sentinel)

        for phase in (url_substitutions, None, token_substitutions):
            if phase is None:
                # keys are either a repo relative path or a bare file name
                scoped = (FILE_SCOPED_SUBSTITUTIONS.get(str(path.relative_to(root)))
                          or FILE_SCOPED_SUBSTITUTIONS.get(path.name)
                          or ())
                if scoped:
                    for old, new, label in scoped:
                        text, hits = re.subn(re.escape(old), fill(new, ident), text)
                        counts[label] = counts.get(label, 0) + hits
                continue
            for old, new, label in phase:
                if isinstance(old, re.Pattern):
                    text, hits = old.subn(new, text)
                else:
                    hits = text.count(old)
                    if hits:
                        text = text.replace(old, new)
                counts[label] += hits

        if path.name == "strings.xml":
            text, hits = re.subn(
                r'(<string name="app_name"[^>]*>)[^<]*(</string>)',
                lambda m: m.group(1) + ident["APP_NAME"] + m.group(2),
                text,
            )
            counts["app_name string"] += hits

        if path.name == "build.gradle.kts" and path.parent.name == "zygote":
            # only rewrite fields of the `zygisk { ... }` block: the same file
            # also contains unrelated `description = "..."` task properties.
            block_match = re.search(r"(?ms)^zygisk \{\n(.*?)^\}", text)
            if not block_match:
                raise ForkError(f"zygisk block not found in {path.relative_to(root)}")
            block = block_match.group(1)
            patched_block = block
            for key, value in (
                ("id", ident["MODULE_ID"]),
                ("name", ident["MODULE_NAME"]),
                ("author", ident["MODULE_AUTHOR"]),
                ("description", ident["MODULE_DESC"]),
            ):
                patched_block, hits = re.subn(
                    rf'(?m)^(\s*){key} = ".*"$',
                    lambda m, k=key, v=value: f'{m.group(1)}{k} = "{v}"',
                    patched_block,
                )
                counts[f"module {key} field"] += hits
            if patched_block != block:
                text = text[:block_match.start(1)] + patched_block + text[block_match.end(1):]

        for sentinel, literal in masked.items():
            text = text.replace(sentinel, literal)

        if text != original:
            touched.append(str(path.relative_to(root)))
            if not dry_run:
                path.write_text(text, encoding="utf-8")

    return counts, touched


def sanitize_res_strings(root: Path, ident: dict[str, str], dry_run: bool) -> dict[str, int]:
    # patterns are regular expressions, applied in file order
    rules = [
        (re.compile(pattern, re.I), fill(value, ident))
        for pattern, value in load_tsv(root / "fork" / "strings-sanitize.tsv")
    ]
    overrides = load_tsv(root / "fork" / "strings-override.tsv")

    counts = {"resource token rewrite": 0, "resource string override": 0}

    element_re = re.compile(r"(<string\b[^>]*>)(.*?)(</string>)", re.S)

    for path in sorted((root / "app/src/main/res").glob("values*/strings.xml")):
        original = path.read_text(encoding="utf-8")
        text = original

        def rewrite(match: re.Match[str]) -> str:
            # only the element text is rewritten: resource *names* never contain
            # a brand word, and touching attributes would break R.string lookups
            head, body, tail = match.group(1), match.group(2), match.group(3)
            for pattern, value in rules:
                body, hits = pattern.subn(value, body)
                counts["resource token rewrite"] += hits
            return head + body + tail

        text = element_re.sub(rewrite, text)
        for name, value in overrides:
            if path.parent.name == "values":
                new_text, hits = re.subn(
                    rf'(<string name="{re.escape(name)}"[^>]*>).*?(</string>)',
                    lambda m, v=value: m.group(1) + v + m.group(2),
                    text,
                    flags=re.S,
                )
            else:
                # localized overrides would resurrect the old wording
                new_text, hits = re.subn(
                    rf'\s*<string name="{re.escape(name)}"[^>]*>.*?</string>',
                    "",
                    text,
                    flags=re.S,
                )
            counts["resource string override"] += hits
            text = new_text
        if text != original:
            if not dry_run:
                path.write_text(text, encoding="utf-8")

    if not dry_run:
        for name, _ in overrides:
            for path in sorted((root / "app/src/main/res").glob("values-*/strings.xml")):
                if name not in path.read_text(encoding="utf-8"):
                    continue
                raise ForkError(f"string override {name!r} still present in {path.parent.name}")
    return counts


def obfuscate_literals(root: Path, dry_run: bool) -> dict[str, int]:
    counts = {"hidden literal": 0}
    for rel in OBFUSCATE_FILES:
        path = root / rel
        if not path.is_file():
            continue
        text = path.read_text(encoding="utf-8")

        def hide(match: re.Match[str]) -> str:
            value = match.group(1)
            if "\\u0000" in value or not BANNED_RE.search(value):
                return match.group(0)
            counts["hidden literal"] += 1
            encoded = base64.b64encode(value.encode("utf-8")).decode("ascii")
            return f'unhide("{encoded}")'

        new_text, hits = LITERAL_RE.subn(hide, text)
        if hits and "fun unhide(" not in new_text:
            lines = new_text.splitlines(keepends=True)
            insert_at = 0
            for index, line in enumerate(lines):
                if line.startswith("import "):
                    insert_at = index + 1
                elif line.startswith("package "):
                    insert_at = max(insert_at, index + 1)
            lines.insert(insert_at, OBFUSCATE_HELPER.lstrip("\n"))
            new_text = "".join(lines)
        if new_text != text and not dry_run:
            path.write_text(new_text, encoding="utf-8")
    return counts


def patch_installer_script(root: Path, ident: dict[str, str], dry_run: bool) -> dict[str, int]:
    """Neutralize the module's own installer scripts.

    Only the framework contract survives: $ZYGISK_ENABLED / $ZYGISK_NAME and the
    zygiskd binaries are defined by the loader itself, everything this fork says
    is rewritten.
    """
    counts: dict[str, int] = {}
    rules = list(INSTALLER_SUBSTITUTIONS) + [
        (UPSTREAM_PROJECT_NAME, ident["PROJECT_NAME"], "installer brand"),
        ("HideMyApplist", ident["PROJECT_NAME"], "installer brand"),
        ("hide_my_applist", ident["STATE_PREFIX"], "installer state dir"),
    ]
    # comment only references to third party projects whose name contains a
    # framework word: drop the link, keep the note
    comment_rules = (
        (re.compile(r"(?m)^\s*#\s*ref:\s*https?://\S*[Rr]e[Zz]ygisk\S*\s*$"),
         "# adapted from a third party loader helper script", "installer comment"),
    )
    for path in sorted((root / "zygote/src/main/assets").rglob("*.sh")):
        text = path.read_text(encoding="utf-8")
        original = text
        for pattern, new, label in comment_rules:
            text, hits = pattern.subn(new, text)
            counts[label] = counts.get(label, 0) + hits
        for old, new, label in rules:
            hits = text.count(old)
            if hits:
                text = text.replace(old, new)
                counts[label] = counts.get(label, 0) + hits
        if text != original and not dry_run:
            path.write_text(text, encoding="utf-8")
    return counts


def move_sources(root: Path, ident: dict[str, str], dry_run: bool) -> list[str]:
    log: list[str] = []
    for rel, destination in DIR_MOVES:
        src = root / rel
        if not src.is_dir():
            continue
        dst = root / fill(destination, ident | {"app": ident["APP_ID_PATH"], "legacy": ident["LEGACY_NS_PATH"]})
        if dst.exists():
            raise ForkError(f"cannot move {rel}: {dst.relative_to(root)} already exists")
        log.append(f"{rel} -> {dst.relative_to(root)}")
        if not dry_run:
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.move(str(src), str(dst))
            prune_empty(src.parent, root)

    for rel, destination in FILE_RENAMES:
        src = root / rel
        if not src.exists():
            continue
        dst = root / fill(destination, ident)
        if dst.exists():
            raise ForkError(f"cannot rename {rel}: {dst.relative_to(root)} already exists")
        log.append(f"{rel} -> {dst.relative_to(root)}")
        if not dry_run:
            src.rename(dst)
    return log


CLASS_FILE_RENAMES = (
    ("common/src/main/aidl/{legacy}/common/IHMAService.aidl", "IBridgeService.aidl"),
    ("zygote/src/main/java/{app}/zygote/service/HMAService.kt", "BridgeService.kt"),
    ("zygote/src/main/java/{app}/zygote/service/HMAServiceDataHolder.kt", "BridgeServiceDataHolder.kt"),
)


def rename_class_files(root: Path, ident: dict[str, str], dry_run: bool) -> list[str]:
    """AIDL requires file name == interface name, and Kotlin keeps the source
    file name in the dex, so renamed classes need renamed files too."""
    log: list[str] = []
    for rel, new_name in CLASS_FILE_RENAMES:
        src = root / fill(rel, ident | {"app": ident["APP_ID_PATH"], "legacy": ident["LEGACY_NS_PATH"]})
        if not src.exists():
            continue
        dst = src.with_name(new_name)
        log.append(f"{src.relative_to(root)} -> {dst.relative_to(root)}")
        if not dry_run:
            src.rename(dst)
    return log


def prune_empty(directory: Path, stop: Path) -> None:
    while directory != stop and directory.is_dir() and not any(directory.iterdir()):
        directory.rmdir()
        directory = directory.parent


def check_anchors(root: Path) -> None:
    failures: list[str] = []
    for rel, anchor in ANCHORS:
        sample = next(iter(root.glob(rel)), None)
        if sample is None:
            failures.append(f"{rel}: file not found (expected to contain {anchor!r})")
            continue
        if anchor not in sample.read_text(encoding="utf-8"):
            failures.append(f"{rel}: anchor not found -> {anchor!r}")
    if failures:
        raise ForkError("upstream anchors changed:\n  " + "\n  ".join(failures))


def allowed_residue(ident: dict[str, str]) -> dict[str, str]:
    """Files that may legitimately still mention a framework.

    These are all *third party* contracts: the loader API the framework
    provides, the installer environment variables it exports and the Gradle DSL
    block of its build plugin.  Nothing here identifies this fork.
    """
    return {
        f"zygote/src/main/java/{ident['APP_ID_PATH']}/zygote/ZygoteEntry.java":
            "com.v7878.zygisk loader API (framework provided, cannot be renamed)",
        "zygote/src/main/assets/customize.d/22-check-framework.sh":
            "$ZYGISK_ENABLED / $ZYGISK_NAME / zygiskd are defined by the framework",
        "zygote/build.gradle.kts":
            "the `zygisk { }` block belongs to the loader Gradle plugin (not shipped)",
    }


def strip_comments(text: str, suffix: str) -> str:
    """Remove comments before scanning.

    Comments never reach an APK, and upstream's licence headers (which mention
    the projects the code was derived from) must stay in the source.
    """
    if suffix == ".xml":
        return re.sub(r"<!--.*?-->", "", text, flags=re.S)
    if suffix in {".kt", ".java", ".kts", ".gradle", ".pro"}:
        text = re.sub(r"/\*.*?\*/", "", text, flags=re.S)
        return re.sub(r"(?m)//.*$", "", text)
    if suffix in {".sh", ".properties", ".toml", ".md"}:
        return re.sub(r"(?m)^\s*#.*$", "", text)
    return text


def verify_tree(root: Path, ident: dict[str, str]) -> tuple[list[str], list[str]]:
    forbidden = {
        UPSTREAM_PACKAGE: "upstream applicationId",
        UPSTREAM_LEGACY: "upstream legacy namespace",
        UPSTREAM_STUB_NS: "upstream stub namespace",
        UPSTREAM_MODULE_ID: "upstream module id",
        UPSTREAM_STATE_PREFIX: "upstream state dir",
        UPSTREAM_BOOT_SCRIPT: "upstream boot script",
        UPSTREAM_FRAMEWORK_CHECK: "upstream installer script name",
        "furkank.net": "upstream update json host",
        "api.github.com/repos/frknkrc44": "upstream release api",
    }
    upstream_repo_url = re.compile(r"https://github\.com/frknkrc44/HMA-OSS(?![-\w/])")
    # this fork's own repo slug carries the upstream project name on purpose
    # (the repo is named after upstream), so mask it before scanning
    own_slug = f"{ident['FORK_OWNER']}/{ident['FORK_REPO']}"
    offenders: list[str] = []
    residue: list[str] = []
    allowed = allowed_residue(ident)

    for path in iter_scope_files(root):
        if path.suffix not in TEXT_SUFFIXES:
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            continue
        rel = str(path.relative_to(root))
        for needle, label in forbidden.items():
            if needle in text:
                offenders.append(f"{rel}: {label} ({needle!r})")
        if upstream_repo_url.search(text):
            offenders.append(f"{rel}: upstream repo url (bare {UPSTREAM_REPO_URL})")
        for stale in (UPSTREAM_PACKAGE_PATH, UPSTREAM_LEGACY_PATH):
            if stale in text:
                offenders.append(f"{rel}: stale package path ({stale})")
        code = strip_comments(text, path.suffix).replace(own_slug, "FORK")
        for term in BANNED_TERMS:
            if re.search(term, code, re.I):
                if rel in allowed:
                    residue.append(f"{rel}: {term!r} kept ({allowed[rel]})")
                else:
                    offenders.append(f"{rel}: banned term {term!r} still present")
        for term in BANNED_CASE_SENSITIVE:
            if term in code:
                offenders.append(f"{rel}: banned identifier {term!r} still present")

    must_have = {
        "build.gradle.kts": f'val appPackageName by extra("{ident["APP_ID"]}")',
        "settings.gradle.kts": f'rootProject.name = "{ident["PROJECT_NAME"]}"',
        "zygote/build.gradle.kts": f'id = "{ident["MODULE_ID"]}"',
    }
    for rel, needle in must_have.items():
        path = root / rel
        if not path.is_file() or needle not in path.read_text(encoding="utf-8"):
            offenders.append(f"{rel}: expected {needle!r} after patching")

    for rel, _ in DIR_MOVES:
        if (root / rel).exists():
            offenders.append(f"{rel}: upstream source directory still present")
    for rel, _ in FILE_RENAMES:
        if (root / rel).exists():
            offenders.append(f"{rel}: upstream file still present")
    for rel, _ in CLASS_FILE_RENAMES:
        candidate = root / fill(rel, ident | {"app": ident["APP_ID_PATH"], "legacy": ident["LEGACY_NS_PATH"]})
        if candidate.exists():
            offenders.append(f"{candidate.relative_to(root)}: upstream file still present")

    return offenders, sorted(set(residue))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("action", choices=("apply", "verify"))
    parser.add_argument("--root", default=str(REPO_ROOT), help="worktree root (default: repo root)")
    parser.add_argument("--config", default=None, help="path to fork.env (default: <root>/fork/fork.env)")
    parser.add_argument("--dry-run", action="store_true", help="report changes without writing")
    parser.add_argument("--check-anchors", action="store_true",
                        help="fail unless every known upstream anchor is present before patching")
    args = parser.parse_args()

    root = Path(args.root).resolve()
    config_path = Path(args.config) if args.config else root / "fork" / "fork.env"
    if not config_path.is_file():
        raise ForkError(f"config not found: {config_path}")

    ident = build_identity(load_config(config_path))

    if args.action == "verify":
        offenders, residue = verify_tree(root, ident)
        for line in residue:
            print(f"note: framework residue kept on purpose -> {line}")
        if offenders:
            print("FAIL: upstream identity survived patching:", file=sys.stderr)
            for item in offenders:
                print(f"  - {item}", file=sys.stderr)
            return 1
        print(f"OK: worktree matches fork identity {ident['APP_ID']}")
        return 0

    if args.check_anchors:
        check_anchors(root)

    counts, touched = patch_text_files(root, ident, args.dry_run)
    counts.update(sanitize_res_strings(root, ident, args.dry_run))
    counts.update(obfuscate_literals(root, args.dry_run))
    counts.update(patch_installer_script(root, ident, args.dry_run))
    moves = move_sources(root, ident, args.dry_run)
    moves += rename_class_files(root, ident, args.dry_run)

    print(f"identity   : {ident['APP_ID']}  (legacy: {ident['LEGACY_NS']})")
    print(f"app name   : {ident['APP_NAME']}   project: {ident['PROJECT_NAME']}")
    print(f"module     : {ident['MODULE_ID']} / {ident['MODULE_NAME']} / {ident['BOOT_SCRIPT']}")
    print(f"update json: {ident['UPDATE_JSON_URL']}")
    print(f"update api : {ident['RELEASE_API_URL']}")
    print("-- replacements --")
    for label, count in sorted(counts.items()):
        if count:
            print(f"  {count:6d}  {label}")
    print(f"-- files rewritten: {len(touched)} --")
    print("-- moves --")
    for item in moves:
        print(f"  {item}")

    if args.dry_run:
        print("(dry run: nothing written)")
        return 0

    offenders, residue = verify_tree(root, ident)
    if offenders:
        print("FAIL: patch left upstream identity behind:", file=sys.stderr)
        for item in offenders:
            print(f"  - {item}", file=sys.stderr)
        return 1

    if residue:
        print("-- framework residues kept on purpose --")
        for item in residue:
            print(f"  {item}")

    print("OK: fork identity applied and verified")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except ForkError as error:
        print(f"ERROR: {error}", file=sys.stderr)
        sys.exit(2)
