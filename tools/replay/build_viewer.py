#!/usr/bin/env python3
"""Build the single-file replay viewer.

    python build_viewer.py enums_compact.json viewer.html

Inlines the DF enum table into viewer.template.html so the result is one file that
opens from disk with no server, no build tooling and no network. The template stays
readable; the built artifact is what you actually open.

Regenerate the enum table whenever the DF/DFHack build changes — tile type, profession
and job ids are renumbered between versions, which is why regime_key already pins
df_version. Produce it with:

    dfhack-run bonsai-dump-enums     # writes /tmp/bonsai_enums.json
    python compact_enums.py /tmp/bonsai_enums.json enums_compact.json
"""
import json
import pathlib
import sys

HERE = pathlib.Path(__file__).parent
PLACEHOLDER = "__ENUMS__"


def main() -> int:
    enums_path = pathlib.Path(sys.argv[1] if len(sys.argv) > 1 else HERE / "enums_compact.json")
    out_path = pathlib.Path(sys.argv[2] if len(sys.argv) > 2 else HERE / "viewer.html")
    template = (HERE / "viewer.template.html").read_text(encoding="utf-8")

    enums = json.loads(enums_path.read_text(encoding="utf-8"))
    for key in ("tt", "prof", "job"):
        if key not in enums:
            print(f"error: enum table is missing '{key}'", file=sys.stderr)
            return 1
    blob = json.dumps(enums, separators=(",", ":"))
    # The blob sits inside <script type="application/json">; only "</script" can end it.
    blob = blob.replace("</", "<\\/")

    if PLACEHOLDER not in template:
        print(f"error: template has no {PLACEHOLDER} placeholder", file=sys.stderr)
        return 1
    out_path.write_text(template.replace(PLACEHOLDER, blob), encoding="utf-8")
    print(f"wrote {out_path} ({out_path.stat().st_size:,} bytes; "
          f"{len(enums['tt']):,} tiletypes, {len(enums['prof'])} professions, "
          f"{len(enums['job'])} job types)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
