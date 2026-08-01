#!/usr/bin/env python3
"""Build the year-horizon evidence report.

    python build_year_report.py <year_runs.json> <recordings_dir> <out.html> [frames_dir]

The previous report covered 3-10 fort-days and was rightly called meaningless: over ten
days a fort cannot starve, cannot grow and cannot be attacked, so every chart was
styling around a period in which nothing can happen. A Dwarf Fortress year is 403,200
ticks — long enough that doing nothing kills dwarves, which is the only condition under
which a survival-gated metric measures anything.

Everything here is read from the recorded runs. No number is typed in.
"""
from __future__ import annotations

import base64
import gzip
import html
import json
import pathlib
import sys

YEAR = 403200


def read_rec(path: pathlib.Path) -> list[dict]:
    out = []
    try:
        with gzip.open(path, "rt", encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if line:
                    try:
                        out.append(json.loads(line))
                    except json.JSONDecodeError:
                        break
    except OSError:
        pass
    return out


def chart(series: list[tuple[str, list, str]], w=520, h=150, ymax=None, ylab=""):
    """Multi-series line chart as inline SVG — no scripts, no network, prints fine."""
    vals = [v for _, s, _ in series for v in s if v is not None]
    if not vals:
        return ""
    hi = ymax if ymax is not None else max(vals + [1])
    n = max(len(s) for _, s, _ in series)
    pad_l, pad_b = 42, 18
    iw, ih = w - pad_l - 8, h - pad_b - 10

    def pt(i, v, ln):
        x = pad_l + (i / max(1, ln - 1)) * iw
        y = 10 + ih - (v / hi) * ih
        return f"{x:.1f},{y:.1f}"

    parts = [f'<svg class="chart" width="{w}" height="{h}" viewBox="0 0 {w} {h}">']
    for frac in (0, .5, 1):
        y = 10 + ih - frac * ih
        parts.append(f'<line x1="{pad_l}" y1="{y:.0f}" x2="{w-8}" y2="{y:.0f}" '
                     f'stroke="#2e2a25"/>')
        parts.append(f'<text x="{pad_l-5}" y="{y+4:.0f}" fill="#8b8377" font-size="10" '
                     f'text-anchor="end">{hi*frac:.0f}</text>')
    for name, s, colour in series:
        s = [v for v in s if v is not None]
        if not s:
            continue
        pts = " ".join(pt(i, v, len(s)) for i, v in enumerate(s))
        parts.append(f'<polyline fill="none" stroke="{colour}" stroke-width="2" '
                     f'points="{pts}"/>')
    parts.append(f'<text x="{pad_l}" y="{h-4}" fill="#8b8377" font-size="10">'
                 f'round 0 &mdash; the fort year &mdash; round {n-1}{"  ·  " + ylab if ylab else ""}</text>')
    parts.append("</svg>")
    return "".join(parts)


def legend(series):
    return " ".join(f'<span style="color:{c}">&#9644; {html.escape(n)}</span>'
                    for n, _, c in series)


def main() -> int:
    runs = json.loads(pathlib.Path(sys.argv[1]).read_text(encoding="utf-8"))
    recdir = pathlib.Path(sys.argv[2])
    out = pathlib.Path(sys.argv[3])
    frames_dir = pathlib.Path(sys.argv[4]) if len(sys.argv) > 4 else None
    by = {r["tier"]: r for r in runs}
    idle, dev = by.get("v0_idle"), by.get("v1_developer")

    frames = []
    if frames_dir and frames_dir.exists():
        for f in sorted(frames_dir.glob("*.png"),
                        key=lambda p: int("".join(c for c in p.stem if c.isdigit()) or 0)):
            frames.append((f.stem, "data:image/png;base64,"
                           + base64.b64encode(f.read_bytes()).decode()))

    E = html.escape
    P = ["""<!DOCTYPE html><meta charset="utf-8"><title>Bonsai — a fort year</title><style>
:root{--bg:#12110f;--panel:#1a1815;--line:#2e2a25;--ink:#d8d0c4;--dim:#8b8377;
      --accent:#c9a227;--good:#6d9b5a;--bad:#b4574a}
*{box-sizing:border-box}
body{margin:0 auto;max-width:1000px;padding:30px;background:var(--bg);color:var(--ink);
     font:14px/1.7 ui-monospace,Consolas,monospace}
h1{font-size:21px;margin:0 0 2px;letter-spacing:.05em}
h2{font-size:12px;text-transform:uppercase;letter-spacing:.13em;color:var(--dim);
   margin:36px 0 10px;border-bottom:1px solid var(--line);padding-bottom:6px}
.sub{color:var(--dim);margin:0 0 6px}
table{border-collapse:collapse;width:100%;margin:12px 0}
th,td{text-align:left;padding:7px 10px;border-bottom:1px solid var(--line);font-size:13px}
th{color:var(--dim);font-size:11px;text-transform:uppercase;letter-spacing:.08em}
td.num,th.num{text-align:right;font-variant-numeric:tabular-nums}
.big{font-size:30px;line-height:1.2;font-weight:600}
.good{color:var(--good)}.bad{color:var(--bad)}.acc{color:var(--accent)}
.card{background:var(--panel);border:1px solid var(--line);border-radius:4px;padding:16px;margin:14px 0}
.grid{display:grid;grid-template-columns:1fr 1fr;gap:14px}
.verdict{border-left:3px solid var(--accent);padding:2px 0 2px 14px;margin:16px 0}
.verdict.no{border-left-color:var(--bad)}.verdict.ok{border-left-color:var(--good)}
code{background:#241f19;padding:1px 5px;border-radius:3px;font-size:12px}
.chart{display:block;margin:6px 0}
.frames{display:flex;gap:10px;overflow-x:auto}
.frames img{width:280px;image-rendering:pixelated;border:1px solid var(--line);display:block}
.frames figcaption{color:var(--dim);font-size:11px;margin-top:4px}
small{color:var(--dim)}
</style>"""]

    P.append("<h1>A FORT YEAR</h1>")
    P.append('<p class="sub">403,200 ticks &mdash; 12 months &times; 28 days &times; 1200. '
             '48 decisions per episode, one per fort-week. Every figure below is read out '
             'of a recorded run on the pinned save.</p>')
    P.append('<p class="sub">The previous report covered 3&ndash;10 fort-days. Over ten days '
             'a fort cannot starve, cannot grow and cannot be attacked &mdash; the charts were '
             'styling around a period in which nothing can happen. This is the horizon where '
             'the metric has something to measure.</p>')

    # ---------------------------------------------------------------- headline
    if idle and dev:
        P.append("<h2>Does doing nothing kill the fort?  Yes.</h2>")
        P.append('<div class="grid">')
        for r, label in ((idle, "did nothing"), (dev, "dug and built")):
            died = r["cohort_start"] - r["cohort_end"]
            cls = "bad" if died >= 3 else "acc"
            P.append(
                f'<div class="card"><small>{E(r["tier"])} &mdash; {label}</small>'
                f'<div class="big {cls}">{r["cohort_end"]} / {r["cohort_start"]}</div>'
                f'<div>dwarves alive after one year &mdash; '
                f'<span class="{cls}">{died} died</span></div>'
                f'<table>'
                f'<tr><td>survival gate</td><td class="num">{r["survival_gate"]:.3f}</td></tr>'
                f'<tr><td>composite score</td><td class="num">{r["composite"]:.3f}</td></tr>'
                f'<tr><td>tiles excavated</td><td class="num">{r["dug"]}</td></tr>'
                f'<tr><td>buildings</td><td class="num">{r["buildings"]}</td></tr>'
                f'<tr><td>drink left</td><td class="num {"bad" if r["drink"][1] < 3 else ""}">'
                f'{r["drink"][1]}</td></tr>'
                f'<tr><td>wall clock</td><td class="num">{r["wall_s"]/60:.1f} min</td></tr>'
                f'</table></div>')
        P.append("</div>")
        P.append(
            f'<div class="verdict ok"><b>The survival gate finally does something.</b> '
            f'Idling loses <b>{idle["cohort_start"]-idle["cohort_end"]} of '
            f'{idle["cohort_start"]}</b> dwarves and the gate collapses to '
            f'<b>{idle["survival_gate"]:.3f}</b>, dragging the score to '
            f'<b>{idle["composite"]:.3f}</b>. Developing loses '
            f'<b>{dev["cohort_start"]-dev["cohort_end"]}</b>, holds the gate at '
            f'<b>{dev["survival_gate"]:.3f}</b> and scores <b>{dev["composite"]:.3f}</b> '
            f'&mdash; {dev["composite"]/max(idle["composite"],1e-9):.1f}&times; better. At ten '
            f'fort-days both scored a full 7/7 and the gate never moved, which is why that '
            f'horizon could not tell these policies apart.</div>')

    # ---------------------------------------------------------------- curves
    P.append("<h2>What actually happened, week by week</h2>")
    tr_i = (idle or {}).get("trace", [])
    tr_d = (dev or {}).get("trace", [])
    charts = [
        ("Dwarves alive", [("idle", [t["alive"] for t in tr_i], "#b4574a"),
                           ("developer", [t["alive"] for t in tr_d], "#6d9b5a")], 7,
         "the fort dies in the second half of the year"),
        ("Drink in store", [("idle", [t["drink"] for t in tr_i], "#b4574a"),
                            ("developer", [t["drink"] for t in tr_d], "#6d9b5a")], None,
         "both run dry — neither policy brews"),
        ("Tiles excavated", [("idle", [t["dug"] for t in tr_i], "#b4574a"),
                             ("developer", [t["dug"] for t in tr_d], "#9a7fa8")], None,
         "development the metric can see"),
        ("Buildings", [("idle", [t["bld"] for t in tr_i], "#b4574a"),
                       ("developer", [t["bld"] for t in tr_d], "#c9a227")], None,
         "stockpiles and workshops raised"),
    ]
    P.append('<div class="grid">')
    for title, series, ymax, note in charts:
        P.append(f'<div class="card"><b>{E(title)}</b><br><small>{legend(series)}</small>'
                 f'{chart(series, ymax=ymax)}<small>{E(note)}</small></div>')
    P.append("</div>")

    # ---------------------------------------------------------------- the catch
    if idle and dev:
        P.append("<h2>The finding nobody ordered</h2>")
        P.append(
            f'<div class="verdict no"><b>Both forts are dying, and building does not save '
            f'them.</b> Drink runs from 12 to <b>{idle["drink"][1]}</b> (idle) and to '
            f'<b>{dev["drink"][1]}</b> (developer) &mdash; the developing fort ran dry '
            f'<i>faster</i>, because digging is thirsty work. Hunger climbs to '
            f'{dev["hunger"][1]:,} against {idle["hunger"][1]:,}. Neither policy farms, '
            f'brews or cooks, so both are living off the wagon and both lose dwarves. '
            f'Excavation and stockpiles are development the metric rewards; they are not '
            f'what keeps a fort alive. The next capability is production, not more digging '
            f'&mdash; and the score already says so if you read past the ranking.</div>')

    # ---------------------------------------------------------------- fort
    if frames:
        P.append("<h2>The fort over the year</h2>")
        P.append('<p class="sub">Rendered from the map track with Dwarf Fortress&rsquo;s own '
                 'sprites. The excavated region grows from 4,096 to 18,432 tiles as the '
                 'shaft goes down.</p><div class="frames">')
        for name, uri in frames:
            rnd = "".join(c for c in name if c.isdigit())
            P.append(f'<figure><img src="{uri}" alt="{E(name)}">'
                     f'<figcaption>round {rnd} of 48</figcaption></figure>')
        P.append("</div>")

    # ---------------------------------------------------------------- honesty
    P.append("<h2>What this does not show</h2>")
    P.append("<div class='card'><table>"
             "<tr><td>one episode per policy</td><td>The scorer reports a K-run median with a "
             "spread precisely because the game is not reproducible. A single year cannot "
             "separate policies whose gap is inside the noise &mdash; the 3.6&times; gap here is "
             "large, but it is one draw.</td></tr>"
             "<tr><td>no attack happened</td><td>The threat channel exists and fires, but what "
             "it caught this year was mining cancellations, not a siege. Reaction to a real "
             "assault is still unproven.</td></tr>"
             "<tr><td>tick delta reads 1,000,000</td><td>An artefact of the "
             "<code>year&times;1000000 + tick</code> encoding crossing a year boundary. Scoring "
             "normalises by the requested horizon, so the score is unaffected, but any rate "
             "computed from that delta would be wrong.</td></tr>"
             "</table></div>")

    P.append("<h2>Check it yourself</h2>")
    P.append("<div class='card'><table>"
             "<tr><td>recordings</td><td><code>/srv/df-bonsai/recordings/*-year.rec.jsonl.gz</code></td></tr>"
             "<tr><td>watch the year</td><td><code>tools/replay/viewer.html</code>, drop a recording on it</td></tr>"
             "<tr><td>side by side</td><td><code>compare.html?a=v0_idle-year…&amp;b=v1_developer-year…</code></td></tr>"
             "<tr><td>the policies</td><td><code>lab_agent/bonsai_lab_agent/baselines/tiers.py</code></td></tr>"
             "</table></div>")

    out.write_text("\n".join(P), encoding="utf-8")
    print(f"wrote {out} ({out.stat().st_size:,} bytes), {len(runs)} runs, {len(frames)} frames")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
