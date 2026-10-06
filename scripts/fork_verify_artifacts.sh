#!/usr/bin/env bash
# Verify that built artifacts really carry this fork's identity and that no
# upstream / framework signature survived in them.
#
# Usage:
#   scripts/fork_verify_artifacts.sh --apk FILE [--expected-version oss-N] [--module FILE]...
#
# The APK and the module zips are extracted first and scanned as a tree, so
# compressed payloads (classes*.dex, resources.arsc, the bundled manager APK,
# the module scripts) are really inspected instead of only the archive's own
# (largely uncompressed) string table.
#
# Marker policy
#   hard markers - must not appear at all
#   soft markers - reported, allowed only where the loader framework itself
#                  mandates the spelling (module payload), never in the APK
set -uo pipefail
# C locale keeps [:print:] deterministic while scanning binaries
export LC_ALL=C

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
APK=""
EXPECTED_VERSION=""
MODULES=()

while [ $# -gt 0 ]; do
    case "$1" in
        --apk) APK="$2"; shift ;;
        --expected-version) EXPECTED_VERSION="$2"; shift ;;
        --module) MODULES+=("$2"); shift ;;
        *) echo "unknown argument: $1" >&2; exit 2 ;;
    esac
    shift
done

eval "$(python3 - "$ROOT/fork/fork.env" <<'PY'
import sys
cfg = {}
for line in open(sys.argv[1], encoding="utf-8"):
    line = line.strip()
    if line and not line.startswith("#") and "=" in line:
        key, value = line.split("=", 1)
        cfg[key.strip()] = value.strip()
for key in ("APP_ID", "MODULE_ID", "PROJECT_NAME", "FORK_OWNER", "FORK_REPO"):
    print(f'{key}="{cfg[key]}"')
PY
)" || { echo "cannot read fork/fork.env" >&2; exit 2; }

UPDATE_JSON_URL="https://github.com/$FORK_OWNER/$FORK_REPO/releases/latest/download/update.json"
FAILED=0

fail() { echo "  FAIL: $*" >&2; FAILED=1; }
ok() { echo "  ok:   $*"; }
info() { echo "  info: $*"; }

# case insensitive hard markers: <marker>|<allowed literal, kept on purpose>
HARD_MARKERS_I=(
    "hidemyapplist"
    "frknkrc44"
    "hmal"
    "lsposed"
    "furkank.net"
)
# case sensitive hard markers: a case insensitive "hma" would also match HashMap
HARD_MARKERS_C=(
    "hma_"
    "hmaApp"
    "hmaoss"
)
# regular expressions, for marks that need a word boundary or an exact casing
# ("HMA" alone is this fork's own product name, so it is not a marker)
HARD_MARKERS_RE=(
    "HMAService"
    "IHMAService"
)
# framework mandated spellings: forbidden in the APK, reported in the module
SOFT_MARKERS_I=(
    "magisk"
    "zygisk"
)

find_aapt2() {
    if command -v aapt2 >/dev/null 2>&1; then command -v aapt2; return 0; fi
    local sdk="${ANDROID_HOME:-${ANDROID_SDK_ROOT:-}}"
    [ -n "$sdk" ] || return 1
    ls "$sdk"/build-tools/*/aapt2 2>/dev/null | sort -V | tail -1
}

# this fork's own repository slug carries the upstream project name on purpose,
# so it is masked out before any marker is counted (it is *our* identity)
mask_own_slug() {
    sed -e "s|${FORK_OWNER}/${FORK_REPO}|FORK|g"
}

scan_text() { # $1=dir -> printable text on stdout
    local dir="$1"
    if command -v strings >/dev/null 2>&1; then
        find "$dir" -type f -exec strings -a {} + 2>/dev/null | mask_own_slug
    else
        find "$dir" -type f -exec cat {} + 2>/dev/null | tr -c '[:print:]' '\n' | mask_own_slug
    fi
}

count_marker() { # $1=dir $2=needle $3=i|- -> occurrences in printable text
    local dir="$1" needle="$2" flag="$3" out
    if [ "$flag" = "i" ]; then
        out="$(scan_text "$dir" | grep -F -o -i -- "$needle" | wc -l || true)"
    else
        out="$(scan_text "$dir" | grep -F -o -- "$needle" | wc -l || true)"
    fi
    printf '%s' "${out//[^0-9]/}"
}

apk_badging() { # $1=apk -> first badging line
    [ -n "$AAPT2" ] || return 1
    "$AAPT2" dump badging "$1" 2>/dev/null | head -1 || true
}

apk_package() { # $1=apk
    apk_badging "$1" | grep -o "name='[^']*'" | head -1 | sed "s/name='\(.*\)'/\1/" || true
}

count_regex() { # $1=dir $2=ere
    local out
    out="$(scan_text "$1" | grep -E -o -- "$2" | wc -l || true)"
    printf '%s' "${out//[^0-9]/}"
}

locate_regex() { # $1=dir $2=ere
    local dir="$1" pattern="$2" file hits shown=0
    while IFS= read -r file; do
        hits="$(scan_one "$file" | grep -E -o -- "$pattern" | wc -l || true)"
        hits="${hits//[^0-9]/}"
        if [ "${hits:-0}" != 0 ]; then
            echo "        in ${file#"$dir"/} ($hits)"
            shown=$((shown + 1))
            [ "$shown" -ge 5 ] && break
        fi
    done < <(find "$dir" -type f)
    scan_text "$dir" | grep -E -o ".{0,40}$pattern.{0,40}" | head -3 | sed 's/^/          /'
}

count_in_file() { # $1=file $2=needle $3=i|-
    local out
    if [ "$3" = "i" ]; then
        out="$(scan_one "$1" | grep -F -o -i -- "$2" | wc -l || true)"
    else
        out="$(scan_one "$1" | grep -F -o -- "$2" | wc -l || true)"
    fi
    printf '%s' "${out//[^0-9]/}"
}

scan_one() { # $1=file -> printable text on stdout
    if command -v strings >/dev/null 2>&1; then
        strings -a -- "$1" 2>/dev/null | mask_own_slug
    else
        tr -c '[:print:]' '\n' < "$1" 2>/dev/null | mask_own_slug
    fi
}

locate_marker() { # $1=dir $2=needle $3=i|- : list the files that carry it
    local dir="$1" needle="$2" flag="$3" file raw hits shown=0
    while IFS= read -r file; do
        hits="$(count_in_file "$file" "$needle" "$flag")"
        if [ "$hits" != 0 ]; then
            echo "        in ${file#"$dir"/} ($hits)"
            shown=$((shown + 1))
            [ "$shown" -ge 5 ] && break
        fi
    done < <(find "$dir" -type f)
    # a short raw context so the source of the string is obvious
    raw="$(scan_one_sample "$dir" "$needle" "$flag")"
    [ -n "$raw" ] && echo "        sample: $raw"
}

scan_one_sample() { # $1=dir $2=needle $3=i|- -> one surrounding context
    local dir="$1" needle="$2" flag="$3"
    if [ "$flag" = "i" ]; then
        scan_text "$dir" | grep -o -i ".\{0,40\}$needle.\{0,40\}" | head -3 | sed 's/^/          /'
    else
        scan_text "$dir" | grep -o ".\{0,40\}$needle.\{0,40\}" | head -3 | sed 's/^/          /'
    fi
}

check_hard_markers() { # $1=label $2=dir
    local label="$1" dir="$2" hits
    for marker in "${HARD_MARKERS_I[@]}"; do
        hits="$(count_marker "$dir" "$marker" i)"
        if [ "$hits" = 0 ]; then ok "$label: no '$marker'"
        else fail "$label: '$marker' appears $hits time(s)"; locate_marker "$dir" "$marker" i; fi
    done
    for marker in "${HARD_MARKERS_C[@]}"; do
        hits="$(count_marker "$dir" "$marker" -)"
        if [ "$hits" = 0 ]; then ok "$label: no '$marker'"
        else fail "$label: '$marker' appears $hits time(s)"; locate_marker "$dir" "$marker" -; fi
    done
    for pattern in "${HARD_MARKERS_RE[@]}"; do
        hits="$(count_regex "$dir" "$pattern")"
        if [ "$hits" = 0 ]; then ok "$label: no /$pattern/"
        else fail "$label: /$pattern/ matches $hits time(s)"; locate_regex "$dir" "$pattern"; fi
    done
}

check_soft_markers() { # $1=label $2=dir $3=strict
    local label="$1" dir="$2" strict="$3" hits
    for marker in "${SOFT_MARKERS_I[@]}"; do
        hits="$(count_marker "$dir" "$marker" i)"
        if [ "$hits" = 0 ]; then
            ok "$label: no '$marker'"
        elif [ "$strict" = "strict" ]; then
            fail "$label: '$marker' appears $hits time(s)"
        else
            info "$label: '$marker' appears $hits time(s) - the loader contract mandates this spelling"
        fi
    done
}

SCAN_ROOT="$(mktemp -d)"
trap 'rm -rf "$SCAN_ROOT"' EXIT
AAPT2="$(find_aapt2 || true)"

if [ -n "$APK" ]; then
    echo "== APK $APK =="
    if [ ! -f "$APK" ]; then
        fail "missing file"
    else
        if [ -n "$AAPT2" ]; then
            badging="$(apk_badging "$APK")"
            echo "  $badging"
            case "$badging" in
                *"name='$APP_ID'"*) ok "applicationId = $APP_ID" ;;
                *) fail "applicationId is not $APP_ID" ;;
            esac
            if [ -n "$EXPECTED_VERSION" ]; then
                case "$badging" in
                    *"versionName='$EXPECTED_VERSION'"*) ok "versionName = $EXPECTED_VERSION" ;;
                    *) fail "versionName is not $EXPECTED_VERSION" ;;
                esac
            fi
        else
            fail "aapt2 not found (set ANDROID_HOME) - cannot inspect the manifest"
        fi

        if unzip -q -o "$APK" -d "$SCAN_ROOT/apk"; then
            check_hard_markers "apk" "$SCAN_ROOT/apk"
            check_soft_markers "apk" "$SCAN_ROOT/apk" strict
        else
            fail "cannot extract the apk"
        fi
    fi
fi

for zip in "${MODULES[@]:-}"; do
    [ -n "$zip" ] || continue
    echo "== module $zip =="
    if [ ! -f "$zip" ]; then fail "missing file"; continue; fi
    dest="$SCAN_ROOT/mod-$(basename "$zip")"
    if ! unzip -q -o "$zip" -d "$dest"; then fail "cannot extract the module zip"; continue; fi

    prop="$(cat "$dest/module.prop" 2>/dev/null || true)"
    if [ -z "$prop" ]; then fail "no module.prop inside"; continue; fi
    echo "$prop" | sed 's/^/  | /'

    case "$prop" in
        *"id=$MODULE_ID"*) ok "module id = $MODULE_ID" ;;
        *) fail "module id is not $MODULE_ID" ;;
    esac
    case "$prop" in
        *"$UPDATE_JSON_URL"*) ok "updateJson points at the fork" ;;
        *) fail "updateJson does not point at $UPDATE_JSON_URL" ;;
    esac
    # upstream module identity must be gone; "keweiya/HMA-OSS" in updateJson is
    # this fork's own slug, so mask it before looking
    prop_masked="$(printf '%s' "$prop" | mask_own_slug)"
    case "$prop_masked" in
        *"id=quarry_zygisk"*|*"id=hma_oss_zygisk"*|*"frknkrc44"*|*"furkank.net"*)
            fail "module.prop still carries an upstream marker" ;;
        *) ok "module.prop carries no upstream marker" ;;
    esac

    check_hard_markers "module" "$dest"
    check_soft_markers "module" "$dest" report

    if find "$dest" -name 'hmaoss.sh' | grep -q .; then
        fail "upstream boot script name hmaoss.sh is still inside the module"
    else
        ok "module: no upstream boot script name"
    fi

    manager_count=0
    while IFS= read -r inner; do
        [ -n "$inner" ] || continue
        manager_count=$((manager_count + 1))
        name="$(apk_package "$inner")"
        if [ "$name" = "$APP_ID" ]; then
            ok "bundled $(basename "$inner") is the $APP_ID manager"
        else
            fail "bundled $(basename "$inner") has applicationId '${name:-unknown}', expected $APP_ID"
        fi
    done < <(find "$dest" -name '*.apk')
    [ "$manager_count" -gt 0 ] || fail "no manager apk bundled in the module"

    case "$(basename "$zip")" in
        "${PROJECT_NAME}-"*) ok "artifact name uses the fork project name '$PROJECT_NAME'" ;;
        *) fail "artifact name '$(basename "$zip")' does not start with '$PROJECT_NAME'" ;;
    esac
done

if [ "$FAILED" != 0 ]; then
    echo "artifact verification FAILED" >&2
    exit 1
fi
echo "artifact verification passed"
