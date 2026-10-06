#!/usr/bin/env python3
"""Translate upstream release notes into Chinese, best effort and key free.

    scripts/translate_notes.py [FILE]      # stdin when FILE is omitted
    scripts/translate_notes.py --provider google|mymemory [FILE]

Exit status 0 with the Chinese text on stdout, non-zero when nothing could be
translated - the caller then keeps the original English text instead of failing
the release.

Both providers are public and need no key, which keeps the pipeline free of extra
secrets, at the cost of possible rate limiting.  A curated translation under
fork/upstream-notes-zh/<tag>.md always takes precedence over this script.

"Co-authored-by:" trailers are turned into a single Chinese "共同作者：" line,
because machine translators mangle names and mail addresses.
"""

from __future__ import annotations

import json
import re
import sys
import urllib.parse
import urllib.request

UA = {"User-Agent": "curl/8.5.0"}
GOOGLE_MAX = 1200  # characters per request
MYMEMORY_MAX = 450  # characters per request (the service rejects long queries)
COAUTHOR_RE = re.compile(r"(?im)^\s*co-authored-by:\s*(.+?)\s*<[^>]*>\s*$")
SEPARATOR_RE = re.compile(r"(?m)^\s*-{3,}\s*$")


class TranslateError(RuntimeError):
    pass


def http_get(url: str, timeout: int = 25) -> str:
    request = urllib.request.Request(url, headers=UA)
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return response.read().decode("utf-8", "replace")


def chunk_text(text: str, limit: int) -> list[str]:
    chunks: list[str] = []
    current = ""
    for line in text.splitlines(keepends=True):
        if len(current) + len(line) > limit and current:
            chunks.append(current)
            current = ""
        while len(line) > limit:  # a single very long line
            chunks.append(line[:limit])
            line = line[limit:]
        current += line
    if current.strip():
        chunks.append(current)
    return chunks


def translate_google(text: str) -> str:
    query = urllib.parse.quote(text)
    raw = http_get(
        "https://translate.googleapis.com/translate_a/single"
        f"?client=gtx&sl=en&tl=zh-CN&dt=t&q={query}"
    )
    data = json.loads(raw)
    if not data or not data[0]:
        raise TranslateError("google: empty response")
    return "".join(segment[0] for segment in data[0] if segment and segment[0])


def translate_mymemory(text: str) -> str:
    query = urllib.parse.quote(text)
    raw = http_get(f"https://api.mymemory.translated.net/get?q={query}&langpair=en|zh-CN")
    data = json.loads(raw)
    translated = (data.get("responseData") or {}).get("translatedText") or ""
    if not translated:
        raise TranslateError("mymemory: empty response")
    return translated


PROVIDERS = {"google": translate_google, "mymemory": translate_mymemory}
LIMITS = {"google": GOOGLE_MAX, "mymemory": MYMEMORY_MAX}


def split_trailers(text: str) -> tuple[str, str]:
    authors: list[str] = []

    def collect(match: re.Match[str]) -> str:
        name = match.group(1).strip()
        if name and name not in authors:
            authors.append(name)
        return ""

    body = COAUTHOR_RE.sub(collect, text)
    body = SEPARATOR_RE.sub("", body)
    body = re.sub(r"\n{3,}", "\n\n", body).strip()
    return body, "、".join(authors)


def translate(text: str, provider: str) -> str:
    translator = PROVIDERS[provider]
    limit = LIMITS[provider]
    parts = [translator(part) for part in chunk_text(text, limit)]
    return "\n".join(part.strip() for part in parts if part.strip())


def main() -> int:
    args = sys.argv[1:]
    provider = "auto"
    if args and args[0] == "--provider":
        provider = args[1]
        args = args[2:]
    if args and args[0] not in ("-", ""):
        text = open(args[0], encoding="utf-8").read()
    else:
        text = sys.stdin.read()

    text = text.strip()
    if not text:
        print("（上游本次发行没有填写更新说明）")
        return 0

    body, authors = split_trailers(text)
    if not body:
        body = text

    order = [provider] if provider in PROVIDERS else ["google", "mymemory"]
    translated = ""
    errors: list[str] = []
    for name in order:
        try:
            translated = translate(body, name)
            print(f"translated with {name}", file=sys.stderr)
            break
        except Exception as error:  # noqa: BLE001 - report and try the next one
            errors.append(f"{name}: {error}")
    if not translated:
        print("translation failed: " + "; ".join(errors), file=sys.stderr)
        return 1

    sys.stdout.write(translated.strip() + "\n")
    if authors:
        sys.stdout.write(f"\n本次发行的共同作者：{authors}\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
