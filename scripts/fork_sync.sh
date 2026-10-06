#!/usr/bin/env bash
# Sync this fork with upstream.
#
# The fork keeps exactly one commit on top of upstream/master: the "fork layer"
# (scripts/, fork/, FORK.md, .github/workflows/fork-*.yml).  Syncing therefore is
# a rebase of that commit onto upstream/master, so upstream code changes land
# unmodified and the fork never fights upstream over its own files.
#
# Usage: scripts/fork_sync.sh [--no-push] [--upstream-remote upstream] [--branch master]
#
# Conflict policy:
#   .github/workflows/fork-*.yml      -> fork version always wins
#   .github/workflows/*  (upstream)   -> always deleted (upstream CI must not run here)
#   README.md FORK.md scripts/* fork/*-> fork version always wins
#   anything else                     -> abort and report
#
# NOTE for maintainers: inside a rebase git swaps the sides.  "--ours" is the
# upstream base we rebase onto, "--theirs" is our own layer commit.
set -euo pipefail

ROOT="$(git rev-parse --show-toplevel)"
cd "$ROOT"

UPSTREAM_REMOTE=upstream
BRANCH=master
PUSH=1
# workflow files that belong to this fork and must survive every sync
FORK_WORKFLOWS=(
    ".github/workflows/fork-sync.yml"
    ".github/workflows/fork-release.yml"
)
while [ $# -gt 0 ]; do
    case "$1" in
        --no-push) PUSH=0 ;;
        --upstream-remote) UPSTREAM_REMOTE="$2"; shift ;;
        --branch) BRANCH="$2"; shift ;;
        *) echo "unknown argument: $1" >&2; exit 2 ;;
    esac
    shift
done

emit() {
    echo "$1"
    if [ -n "${GITHUB_OUTPUT:-}" ]; then
        echo "$1" >> "$GITHUB_OUTPUT"
    fi
}

git config user.name >/dev/null 2>&1 || git config user.name "fork-sync"
git config user.email >/dev/null 2>&1 || git config user.email "fork-sync@users.noreply.github.com"

current_branch="$(git symbolic-ref --quiet --short HEAD || true)"
if [ "$current_branch" != "$BRANCH" ]; then
    echo "!! HEAD is not on branch $BRANCH (got '${current_branch:-detached}')" >&2
    exit 1
fi

echo "== fetching $UPSTREAM_REMOTE/$BRANCH =="
git fetch --no-tags "$UPSTREAM_REMOTE" "$BRANCH"
UPSTREAM_REF="$UPSTREAM_REMOTE/$BRANCH"
UPSTREAM_SHA="$(git rev-parse "$UPSTREAM_REF")"
emit "upstream_sha=$UPSTREAM_SHA"
echo "upstream tip: $UPSTREAM_SHA"

is_fork_workflow() {
    local candidate="$1" entry
    for entry in "${FORK_WORKFLOWS[@]}"; do
        [ "$candidate" = "$entry" ] && return 0
    done
    return 1
}

resolve_conflicts() {
    local unexpected=()
    local file
    while IFS= read -r file; do
        [ -n "$file" ] || continue
        case "$file" in
            .github/workflows/*)
                if is_fork_workflow "$file"; then
                    git checkout --theirs -- "$file" && git add -- "$file"
                else
                    git rm -q -f --ignore-unmatch -- "$file"
                fi ;;
            README.md|FORK.md|scripts/*|fork/*)
                git checkout --theirs -- "$file" && git add -- "$file" ;;
            *)
                unexpected+=("$file") ;;
        esac
    done < <(git diff --name-only --diff-filter=U)

    if [ "${#unexpected[@]}" -gt 0 ]; then
        echo "!! unexpected conflicts (upstream and fork both changed these):" >&2
        printf '   - %s\n' "${unexpected[@]}" >&2
        echo "!! resolve them by hand, then re-run this script" >&2
        git rebase --abort || true
        exit 1
    fi
}

if git merge-base --is-ancestor "$UPSTREAM_REF" HEAD; then
    echo "already contains $UPSTREAM_REF"
else
    echo "== rebasing fork layer onto $UPSTREAM_REF =="
    git rebase "$UPSTREAM_REF" || true
    attempt=0
    while [ -d .git/rebase-merge ] || [ -d .git/rebase-apply ]; do
        attempt=$((attempt + 1))
        if [ "$attempt" -gt 20 ]; then
            echo "!! rebase did not converge" >&2
            git rebase --abort || true
            exit 1
        fi
        resolve_conflicts
        GIT_EDITOR=true git rebase --continue || true
    done
fi

# Upstream may add or modify its own workflow files; they must never run here.
pruned=0
shopt -s nullglob
for file in .github/workflows/*; do
    is_fork_workflow "$file" && continue
    git rm -q -f --ignore-unmatch -- "$file"
    pruned=1
done
shopt -u nullglob
if [ "$pruned" = 1 ]; then
    echo "== dropping upstream workflow files =="
    git commit -q --amend --no-edit
fi

# Working tree must be clean before we publish the branch.
if [ -n "$(git status --porcelain)" ]; then
    echo "!! working tree is dirty after sync:" >&2
    git status --short >&2
    exit 1
fi

LAYER_SHA="$(git rev-parse HEAD)"
emit "fork_sha=$LAYER_SHA"

if [ "$PUSH" = 1 ]; then
    git fetch --no-tags origin "$BRANCH" || true
    if git rev-parse --verify --quiet "origin/$BRANCH" >/dev/null; then
        echo "== pushing $BRANCH (force-with-lease) =="
        git push --force-with-lease="refs/heads/$BRANCH:refs/remotes/origin/$BRANCH" origin "$BRANCH"
    else
        echo "== pushing $BRANCH (new branch) =="
        git push --force origin "$BRANCH"
    fi
fi

echo "sync done: $LAYER_SHA"
