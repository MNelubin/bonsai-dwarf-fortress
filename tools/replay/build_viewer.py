#!/usr/bin/env python3
"""Build the single-file replay viewer.

    python build_viewer.py [sprites_dir]

Inlines everything the viewer needs into one file that opens from disk with no server,
no build tooling and no network:

    enums_compact.json   tiletype -> shape/material/special, professions, job types
    sprites.json         token -> atlas cell, from the game's own graphics raws
    atlas.png            the packed sprite sheet, as a data URI
    tilemap.json         tiletype -> sprite family + kind

The atlas is inlined rather than shipped alongside on purpose: a canvas that draws a
file:// image becomes tainted, and tinting sprites by material colour needs to read
pixels back. A data URI is same-origin, so it stays readable.

Regenerate the inputs whenever the DF/DFHack build changes — tiletype, profession and
job ids are renumbered between versions, which is why regime_key already pins
df_version:

    dfhack-run bonsai-dump-enums                              # /tmp/bonsai_enums.json
    python extract_sprites.py <raws> <images> <out>           # atlas.png + sprites.json
    python build_tilemap.py enums_compact.json <out>/sprites.json <out>/tilemap.json
"""
import base64
import gzip
import json
import pathlib
import sys

HERE = pathlib.Path(__file__).parent


def load(path: pathlib.Path, what: str) -> str:
    if not path.exists():
        print(f"  note: no {what} at {path} — viewer will fall back to glyph rendering")
        return "null"
    return path.read_text(encoding="utf-8")


def main() -> int:
    # Default to build/ rather than this directory. Both hold a full set of atlas.png +
    # sprites.json + tilemap.json and they DIVERGE (the ones here are an earlier
    # extraction, from before grass and the floor blend set were fixed). Everything else
    # in the pipeline takes build/, so a bare `python build_viewer.py` used to silently
    # produce a viewer from the stale set.
    if len(sys.argv) > 1:
        sprites_dir = pathlib.Path(sys.argv[1])
    else:
        sprites_dir = HERE / "build" if (HERE / "build" / "sprites.json").is_file() else HERE
    stale = [p.name for p in (HERE / "atlas.png", HERE / "sprites.json", HERE / "tilemap.json")
             if p.is_file() and sprites_dir != HERE]
    if stale:
        print(f"  note: ignoring an older extraction in {HERE}: {', '.join(stale)}")
    out_path = HERE / "viewer.html"
    template = (HERE / "viewer.template.html").read_text(encoding="utf-8")

    enums = json.loads((HERE / "enums_compact.json").read_text(encoding="utf-8"))
    for key in ("tt", "prof", "job"):
        if key not in enums:
            print(f"error: enum table is missing '{key}'", file=sys.stderr)
            return 1

    sprites_raw = load(sprites_dir / "sprites.json", "sprites.json")
    tilemap_raw = load(sprites_dir / "tilemap.json", "tilemap.json")

    atlas_path = sprites_dir / "atlas.png"
    n_sprites = 0
    if sprites_raw != "null" and atlas_path.exists():
        sprites = json.loads(sprites_raw)
        n_sprites = len(sprites.get("tokens", {}))
        b64 = base64.b64encode(atlas_path.read_bytes()).decode("ascii")
        sprites["atlas"] = "data:image/png;base64," + b64
        sprites_raw = json.dumps(sprites, separators=(",", ":"))

    # The palette table and the save's geology are what turn grey key art into rock and
    # soil. Geology goes in already expanded from RLE: the browser would otherwise repeat
    # the expansion on every load, and the JSON is only ~340 KB against a 2.5 MB viewer.
    palette_raw = load(sprites_dir / "palette.json", "palette.json")
    geology_raw = "null"
    for name in ("geology.json.gz", "geology.json"):
        gp = sprites_dir / name
        if not gp.exists():
            continue
        opener = gzip.open if name.endswith(".gz") else open
        with opener(gp, "rt", encoding="utf-8") as fh:
            geology_raw = json.dumps(json.load(fh), separators=(",", ":"))
        break
    if geology_raw == "null":
        print("  note: no geology dump — rock and soil will render in the grey key art")

    subs = {
        "__ENUMS__": json.dumps(enums, separators=(",", ":")),
        "__SPRITES__": sprites_raw,
        "__TILEMAP__": tilemap_raw,
        "__PALETTE__": palette_raw,
        "__GEOLOGY__": geology_raw,
    }
    html = template
    for placeholder, blob in subs.items():
        if placeholder not in html:
            print(f"error: template has no {placeholder} placeholder", file=sys.stderr)
            return 1
        # each blob sits inside <script type="application/json">; only "</script" ends it
        html = html.replace(placeholder, blob.replace("</", "<\\/"))

    out_path.write_text(html, encoding="utf-8")
    n_mapped = len(json.loads(tilemap_raw).get("tiles", {})) if tilemap_raw != "null" else 0
    print(f"wrote {out_path} ({out_path.stat().st_size:,} bytes)")
    print(f"  {len(enums['tt']):,} tiletypes, {len(enums['prof'])} professions, "
          f"{len(enums['job'])} job types")
    print(f"  {n_sprites:,} sprites inlined, {n_mapped:,} tiletypes mapped to them")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
