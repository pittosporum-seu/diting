#!/usr/bin/env python3
"""Add pinyin initials field to stock-list.json.

Downloads the public-domain pinyin mapping from mozillazg/pinyin-data,
parses it, and adds a 'pinyin' field (initials only) to every stock entry.

Usage:
    uv run python scripts/add_pinyin.py
"""
from __future__ import annotations

import json
import re
import unicodedata
import urllib.request
from pathlib import Path

PINYIN_URL = "https://raw.githubusercontent.com/mozillazg/pinyin-data/master/pinyin.txt"
STOCK_LIST = Path(__file__).parent.parent / "frontend" / "data" / "stock-list.json"


def download_pinyin_map() -> dict[str, str]:
    """Download and parse the public pinyin mapping file.
    Returns {char: pinyin_syllable}.
    """
    print(f"Downloading pinyin data from {PINYIN_URL}...")
    data = urllib.request.urlopen(PINYIN_URL).read().decode("utf-8")

    pinyin_map: dict[str, str] = {}
    for line in data.splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        m = re.match(r"U\+([0-9A-Fa-f]+):\s+(\S+)", line)
        if m:
            codepoint = int(m.group(1), 16)
            pinyin = m.group(2).split(",")[0].strip()
            pinyin_map[chr(codepoint)] = pinyin

    print(f"  Loaded {len(pinyin_map)} pinyin mappings")
    return pinyin_map


def strip_tone(char: str) -> str:
    """Strip combining tone marks from a pinyin character, e.g. 'ā' → 'a'."""
    decomposed = unicodedata.normalize("NFD", char)
    return "".join(ch for ch in decomposed if not unicodedata.combining(ch))


def to_pinyin_initials(name: str, pinyin_map: dict[str, str]) -> str:
    """Convert a Chinese stock name to pinyin initials.
    Example: '平安银行' → 'payx'.
    """
    clean = name.replace(" ", "").replace("*", "").replace("-", "")
    result: list[str] = []
    for c in clean:
        py = pinyin_map.get(c, "")
        if py:
            result.append(strip_tone(py)[0].lower())
        elif c.isascii() and c.isalpha():
            result.append(c.lower())
    return "".join(result)


def main() -> None:
    pinyin_map = download_pinyin_map()

    if not STOCK_LIST.exists():
        print(f"ERROR: {STOCK_LIST} not found")
        return

    with open(STOCK_LIST) as f:
        stocks = json.load(f)

    updated = 0
    for s in stocks:
        name = s.get("name", "")
        py = to_pinyin_initials(name, pinyin_map)
        s["pinyin"] = py
        updated += 1

    with open(STOCK_LIST, "w") as f:
        json.dump(stocks, f, ensure_ascii=False)

    print(f"Updated {updated} stocks with pinyin initials in {STOCK_LIST}")
    print("Examples:")
    for s in stocks[:5]:
        print(f"  {s['code']} {s['name']} → {s['pinyin']}")


if __name__ == "__main__":
    main()
