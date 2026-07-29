#!/usr/bin/env python3
"""Compact a bonsai-dump-enums dump into the table the viewer inlines.

    python compact_enums.py /tmp/bonsai_enums.json enums_compact.json

Resolves the shape/material/special ids into names so the viewer needs no joins, and
drops the NONE/NORMAL specials that carry no rendering meaning.
"""
import json, pathlib, sys

d = json.loads(pathlib.Path(sys.argv[1]).read_text())
shape = {int(k): v for k, v in d["tiletype_shape"].items()}
mat = {int(k): v for k, v in d["tiletype_material"].items()}
spec = {int(k): v for k, v in d["tiletype_special"].items()}

tt, sp = {}, {}
for k, v in d["tiletype"].items():
    tt[int(k)] = [shape.get(int(v["sh"]), "NONE"), mat.get(int(v["mat"]), "NONE"), v["n"]]
    s = spec.get(int(v["sp"]), "NONE")
    if s not in ("NONE", "NORMAL"):
        sp[int(k)] = s

out = {
    "tt": tt, "special": sp,
    "prof": {int(k): v for k, v in d["profession"].items()},
    "job": {int(k): v for k, v in d["job_type"].items()},
    "bld": {int(k): v for k, v in d["building_type"].items()},
    "item": {int(k): v for k, v in d["item_type"].items()},
    "df": d["df_version"], "dfhack": d["dfhack_version"],
}
blob = json.dumps(out, separators=(",", ":"))
pathlib.Path(sys.argv[2]).write_text(blob, encoding="utf-8")
print(f"wrote {sys.argv[2]}: {len(blob):,} bytes, {len(tt)} tiletypes, {len(sp)} specials")
