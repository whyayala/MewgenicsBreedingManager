"""Diagnose stat-total and ability-name discrepancies for a single cat.

Post-1.1 field check helper. Run on the machine that has the game installed:

    python tools/diagnose_cat.py "%LOCALAPPDATA%\\Glaiel Games\\Mewgenics\\<slot>.sav" "Cat Name"
    python tools/diagnose_cat.py <save.sav> "Cat Name" --gpak "C:\\...\\Mewgenics\\resources.gpak"

Prints, for the named cat:
  1. The stat breakdown the app uses (base / mod / sec / mutation bonus / total)
     so it can be compared line-by-line against the in-game character sheet.
  2. Every visual mutation entry with its raw GON stat text, localized detail
     text, and the stat delta the app parsed from them.
  3. The raw ability/passive tokens stored in the save, and (when the gpak is
     available) the display-name field from each ability's GON block plus any
     localization strings whose key references the token — to reveal where the
     game's current display names live when they diverge from the save tokens.
"""

import argparse
import os
import re
import struct
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "src"))

from save_parser import (  # noqa: E402
    GameData, STAT_NAMES, parse_save, set_class_stat_mods, set_visual_mut_data,
    _load_gpak_text_strings, _parse_mutation_stat_delta, _resolve_game_string,
)

_DEFAULT_GPAK_CANDIDATES = [
    r"C:\Program Files (x86)\Steam\steamapps\common\Mewgenics\resources.gpak",
    r"C:\Program Files\Steam\steamapps\common\Mewgenics\resources.gpak",
    os.path.expanduser(r"~\scoop\apps\steam\current\steamapps\common\Mewgenics\resources.gpak"),
]


def _find_gpak(explicit: str | None) -> str | None:
    if explicit:
        return explicit if os.path.exists(explicit) else None
    for p in _DEFAULT_GPAK_CANDIDATES:
        if os.path.exists(p):
            return p
    return None


def _read_gpak_directory(f) -> dict[str, tuple[int, int]]:
    """Return {entry_name: (offset, size)} for a resources.gpak file object."""
    count = struct.unpack("<I", f.read(4))[0]
    entries = []
    for _ in range(count):
        name_len = struct.unpack("<H", f.read(2))[0]
        name = f.read(name_len).decode("utf-8", errors="replace")
        size = struct.unpack("<I", f.read(4))[0]
        entries.append((name, size))
    offset = f.tell()
    file_offsets: dict[str, tuple[int, int]] = {}
    for name, size in entries:
        file_offsets[name] = (offset, size)
        offset += size
    return file_offsets


_BLOCK_RE = re.compile(r"^([A-Za-z]\w*)\s*\{", re.MULTILINE)


def _gon_block(content: str, token: str) -> str | None:
    """Return the body of the top-level GON block whose id equals token."""
    for bm in _BLOCK_RE.finditer(content):
        if bm.group(1).lower() != token.lower():
            continue
        depth, idx = 1, bm.end()
        while idx < len(content) and depth > 0:
            if content[idx] == "{":
                depth += 1
            elif content[idx] == "}":
                depth -= 1
            idx += 1
        return content[bm.end():idx - 1]
    return None


def _ability_name_report(gpak_path: str, tokens: list[str]) -> None:
    with open(gpak_path, "rb") as f:
        file_offsets = _read_gpak_directory(f)
        game_strings = _load_gpak_text_strings(f, file_offsets)

        gon_contents: dict[str, str] = {}
        for fname, (foff, fsz) in file_offsets.items():
            if (fname.startswith("data/abilities/") or fname.startswith("data/passives/")) and fname.endswith(".gon"):
                f.seek(foff)
                gon_contents[fname] = f.read(fsz).decode("utf-8", errors="replace")

    for token in tokens:
        base = re.sub(r"\d+$", "", token)  # strip trailing tier digit
        print(f"\n  token: {token!r}")
        found_block = False
        for fname, content in gon_contents.items():
            block = _gon_block(content, token) or _gon_block(content, base)
            if block is None:
                continue
            found_block = True
            head = block[:400]
            for field in ("name", "displayname", "display_name", "title"):
                fm = re.search(rf'^\s*{field}\s+"([^"]*)"', block, re.MULTILINE)
                if fm:
                    raw = fm.group(1)
                    resolved = _resolve_game_string(game_strings.get(raw, raw), game_strings)
                    print(f"    {fname}: {field} = {raw!r} -> {resolved!r}")
                    break
            else:
                print(f"    {fname}: block found, no name-like field. First 400 chars:")
                print("      " + head.replace("\n", "\n      "))
        if not found_block:
            print("    no GON block found in data/abilities/ or data/passives/")
        key_hits = [k for k in game_strings if base.lower() in k.lower()][:8]
        for k in key_hits:
            print(f"    string key {k!r} = {game_strings[k]!r}")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("save", help="path to the .sav file")
    ap.add_argument("cat", help="cat name (case-insensitive substring match)")
    ap.add_argument("--gpak", help="path to resources.gpak (auto-detected if omitted)")
    args = ap.parse_args()

    gpak = _find_gpak(args.gpak)
    if gpak:
        print(f"gpak: {gpak}")
        gd = GameData.from_gpak(gpak)
        set_visual_mut_data(gd.visual_mutation_data)
        set_class_stat_mods(gd.class_stat_mods)
    else:
        print("gpak: NOT FOUND — mutation names/deltas will use bundled fallbacks; pass --gpak")

    save = parse_save(args.save)
    needle = args.cat.strip().lower()
    matches = [c for c in save.cats if needle in (c.name or "").lower()]
    if not matches:
        print(f"no cat matching {args.cat!r}")
        return 1
    if len(matches) > 1:
        print(f"note: {len(matches)} cats match; using exact/first: "
              + ", ".join((c.name or "?") for c in matches[:6]))
        exact = [c for c in matches if (c.name or "").lower() == needle]
        matches = exact or matches
    cat = matches[0]

    print(f"\n=== {cat.name} (db_key={getattr(cat, 'db_key', '?')}) ===")

    print("\n-- Stat breakdown (compare 'app total' against the in-game sheet) --")
    print(f"{'stat':<5} {'base':>5} {'mod':>5} {'sec':>5} {'mut':>5} {'app total':>10}")
    for i, name in enumerate(STAT_NAMES):
        mut = cat.mutation_stat_bonus.get(name, 0)
        total = cat.total_stats[name]
        print(f"{name:<5} {cat.stat_base[i]:>5} {cat.stat_mod[i]:>5} {cat.stat_sec[i]:>5} {mut:>5} {total:>10}")

    print("\n-- Visual mutation entries --")
    for e in cat.visual_mutation_entries:
        delta_gon = _parse_mutation_stat_delta(str(e.get("gon_stats") or ""))
        delta_det = _parse_mutation_stat_delta(str(e.get("detail") or ""))
        used = delta_gon if delta_gon else delta_det
        print(f"  [{e['slot_key']}] id={e['mutation_id']} name={e['name']!r} defect={e['is_defect']}")
        print(f"      gon_stats={str(e.get('gon_stats') or '')!r} -> {delta_gon}")
        print(f"      detail={str(e.get('detail') or '')[:90]!r} -> {delta_det}")
        print(f"      delta applied to total: {used}")

    print("\n-- Ability/passive tokens stored in the save --")
    actives = list(getattr(cat, "abilities", []) or [])
    passives = list(getattr(cat, "passive_abilities", []) or [])
    print(f"  active:  {actives}")
    print(f"  passive: {passives}")

    if gpak:
        print("\n-- Display-name lookup in gpak (compare against in-game names) --")
        _ability_name_report(gpak, actives + passives)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
