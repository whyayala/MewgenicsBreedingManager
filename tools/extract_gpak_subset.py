"""Extract the data entries this app reads from resources.gpak into a mini gpak.

The output is a valid gpak (same binary format) containing only the text/GON
entries the parser consumes, so it drops in anywhere a full resources.gpak is
accepted (the app's gpak path setting, diagnose_cat.py --gpak, GameData.from_gpak).
Typically a few MB instead of the full archive.

    python tools/extract_gpak_subset.py "C:\\...\\Mewgenics\\resources.gpak" mini_resources.gpak
    python tools/extract_gpak_subset.py <in.gpak> <out.gpak> --no-swf   # text/GON only
"""

import argparse
import os
import struct

# Entries whose name merely *contains* a tag token are matched loosely by the
# app; cap their size so a large binary that happens to contain "tag" in its
# path doesn't balloon the subset.
_TAG_TOKENS = ("tag", "badge", "name_tag", "name-tag")
_TAG_MAX_BYTES = 2 * 1024 * 1024


def _wanted(name: str, size: int, include_swf: bool) -> bool:
    lowered = name.lower()
    if lowered.endswith(".csv"):
        return True
    if name.startswith("data/mutations/") and name.endswith(".gon"):
        return True
    if (name.startswith("data/abilities/") or name.startswith("data/passives/")) and name.endswith(".gon"):
        return True
    if name in ("data/furniture_effects.gon", "data/classes/classes.gon", "data/classes/advanced_classes.gon"):
        return True
    if any(t in lowered for t in _TAG_TOKENS) and size <= _TAG_MAX_BYTES and not lowered.endswith(".swf"):
        return True
    if include_swf and lowered.endswith(".swf") and any(t in lowered for t in ("icon", "portrait")):
        return True
    return False


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("src", help="path to the full resources.gpak")
    ap.add_argument("dst", help="path for the mini gpak to write")
    ap.add_argument("--no-swf", action="store_true",
                    help="skip icon/portrait SWFs (text and GON data only)")
    args = ap.parse_args()

    with open(args.src, "rb") as f:
        count = struct.unpack("<I", f.read(4))[0]
        entries = []
        for _ in range(count):
            name_len = struct.unpack("<H", f.read(2))[0]
            name = f.read(name_len).decode("utf-8", errors="replace")
            size = struct.unpack("<I", f.read(4))[0]
            entries.append((name, size))
        data_start = f.tell()

        keep: list[tuple[str, int, int]] = []  # (name, offset, size)
        offset = data_start
        for name, size in entries:
            if _wanted(name, size, include_swf=not args.no_swf):
                keep.append((name, offset, size))
            offset += size

        if not keep:
            print("no matching entries found — is this a resources.gpak?")
            return 1

        with open(args.dst, "wb") as out:
            out.write(struct.pack("<I", len(keep)))
            for name, _, size in keep:
                encoded = name.encode("utf-8")
                out.write(struct.pack("<H", len(encoded)))
                out.write(encoded)
                out.write(struct.pack("<I", size))
            for _, foff, size in keep:
                f.seek(foff)
                remaining = size
                while remaining > 0:
                    chunk = f.read(min(remaining, 1 << 20))
                    if not chunk:
                        raise IOError(f"unexpected EOF copying entry data")
                    out.write(chunk)
                    remaining -= len(chunk)

    total = sum(s for _, _, s in keep)
    print(f"wrote {args.dst}: {len(keep)} of {count} entries, {total / 1_048_576:.1f} MB")
    by_prefix: dict[str, int] = {}
    for name, _, _ in keep:
        prefix = name.rsplit("/", 1)[0] if "/" in name else "(root)"
        by_prefix[prefix] = by_prefix.get(prefix, 0) + 1
    for prefix in sorted(by_prefix):
        print(f"  {prefix}/: {by_prefix[prefix]}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
