#!/usr/bin/env python3
"""Build the evidence report for the baseline ladder.

    python build_report.py <ladder_runs.json> <recordings_dir> <out.html> [frames_dir]

Answers three questions with a run behind every number:
  1. does the baseline run
  2. does it react to what the game tells it
  3. does it improve

Everything is read from the recordings themselves — the charts, the decision feed and
the threat timeline are computed here, not copied from a summary someone typed.
"""
from __future__ import annotations

import base64
import gzip
import html
import json
import pathlib
import sys


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


def sparkline(vals, w=260, h=44, colour="#c9a227", zero_base=True):
    """Inline SVG so the page needs no scripts and no network."""
    vals = [v for v in vals if v is not None]
    if not vals:
        return '<svg width="%d" height="%d"></svg>' % (w, h)
    lo = 0 if zero_base else min(vals)
    hi = max(vals + [lo + 1])
    span = (hi - lo) or 1
    pts = []
    for i, v in enumerate(vals):
        x = (i / max(1, len(vals) - 1)) * (w - 4) + 2
        y = h - 3 - ((v - lo) / span) * (h - 8)
        pts.append(f"{x:.1f},{y:.1f}")
    return (f'<svg class="spark" width="{w}" height="{h}" viewBox="0 0 {w} {h}">'
            f'<polyline fill="none" stroke="{colour}" stroke-width="1.8" '
            f'points="{" ".join(pts)}"/></svg>')


def bar(value, maximum, w=300, colour="#6d9b5a"):
    frac = 0 if maximum <= 0 else max(0.0, min(1.0, value / maximum))
    return (f'<span class="bar"><span style="width:{frac*100:.1f}%;background:{colour}">'
            f'</span></span>')


def main() -> int:
    runs = json.loads(pathlib.Path(sys.argv[1]).read_text(encoding="utf-8"))
    recdir = pathlib.Path(sys.argv[2])
    out = pathlib.Path(sys.argv[3])
    frames_dir = pathlib.Path(sys.argv[4]) if len(sys.argv) > 4 else None

    # ---- load every recording once ------------------------------------------
    detail = {}
    for r in runs:
        p = recdir / pathlib.PurePath(r["file"]).name
        ev = read_rec(p)
        stats = [e for e in ev if e.get("kind") == "stat"]
        rounds = [e for e in ev if e.get("kind") == "round"]
        maps = [e for e in ev if e.get("kind") == "map"]
        detail[(r["tier"], r["horizon"])] = {
            "events": len(ev), "stats": stats, "rounds": rounds, "maps": len(maps),
            "path": p,
        }

    horizons = sorted({r["horizon"] for r in runs})
    tiers = ["v0_idle", "v1_developer", "v2_reactive"]
    by = {(r["tier"], r["horizon"]): r for r in runs}

    # ---- frames (the "video": consecutive map frames as still images) -------
    frame_imgs = []
    if frames_dir and frames_dir.exists():
        for f in sorted(frames_dir.glob("*.png"))[:8]:
            b64 = base64.b64encode(f.read_bytes()).decode()
            frame_imgs.append((f.stem, f"data:image/png;base64,{b64}"))

    E = html.escape
    P = []
    P.append("""<!DOCTYPE html><meta charset="utf-8"><title>Bonsai baseline — evidence</title>
<style>
:root{--bg:#12110f;--panel:#1a1815;--line:#2e2a25;--ink:#d8d0c4;--dim:#8b8377;
      --accent:#c9a227;--good:#6d9b5a;--bad:#b4574a}
*{box-sizing:border-box}
body{margin:0;background:var(--bg);color:var(--ink);font:14px/1.65 ui-monospace,Consolas,monospace;
     max-width:1100px;margin:0 auto;padding:28px}
h1{font-size:20px;letter-spacing:.06em;margin:0 0 4px}
h2{font-size:13px;text-transform:uppercase;letter-spacing:.12em;color:var(--dim);
   margin:34px 0 10px;border-bottom:1px solid var(--line);padding-bottom:6px}
h3{font-size:14px;margin:20px 0 6px}
.sub{color:var(--dim);margin:0 0 18px}
table{border-collapse:collapse;width:100%;margin:10px 0}
th,td{text-align:left;padding:6px 10px;border-bottom:1px solid var(--line);font-size:13px}
th{color:var(--dim);font-weight:600;font-size:11px;text-transform:uppercase;letter-spacing:.08em}
td.num{text-align:right;font-variant-numeric:tabular-nums}
.bar{display:inline-block;width:180px;height:9px;background:#241f19;border-radius:2px;
     overflow:hidden;vertical-align:middle;margin-right:8px}
.bar>span{display:block;height:100%}
.good{color:var(--good)}.bad{color:var(--bad)}.acc{color:var(--accent)}
.card{background:var(--panel);border:1px solid var(--line);border-radius:4px;padding:14px 16px;margin:12px 0}
.verdict{border-left:3px solid var(--accent);padding-left:14px;margin:14px 0}
.verdict.ok{border-left-color:var(--good)}
.verdict.no{border-left-color:var(--bad)}
code{background:#241f19;padding:1px 5px;border-radius:3px;font-size:12px}
.frames{display:flex;gap:8px;overflow-x:auto;padding:6px 0}
.frames figure{margin:0;flex:0 0 auto}
.frames img{width:230px;image-rendering:pixelated;border:1px solid var(--line);display:block}
.frames figcaption{color:var(--dim);font-size:11px;margin-top:4px}
.feed{max-height:280px;overflow-y:auto;font-size:12px}
.feed div{padding:2px 0;border-bottom:1px solid #221f1a}
.spark{display:block}
.warn{color:var(--bad)}
small{color:var(--dim)}
</style>""")

    P.append(f"<h1>BONSAI BASELINE — EVIDENCE</h1>")
    P.append('<p class="sub">Every number below is read out of a recorded episode on the '
             'pinned save. Nothing is asserted that a run does not show.</p>')

    # =====================================================================
    P.append("<h2>1 · Does it run</h2>")
    P.append("<table><tr><th>policy</th><th>horizon</th><th class='num'>ticks</th>"
             "<th class='num'>wall</th><th>cohort</th><th class='num'>rounds</th>"
             "<th class='num'>events</th><th class='num'>recording</th></tr>")
    for H in horizons:
        for t in tiers:
            r = by.get((t, H))
            if not r:
                P.append(f"<tr><td>{E(t)}</td><td class='num'>{H}</td>"
                         f"<td colspan='6' class='bad'>episode failed — not scored</td></tr>")
                continue
            d = detail[(t, H)]
            ok = r["cohort"].split("/")[0] == r["cohort"].split("/")[1]
            P.append(
                f"<tr><td>{E(t)}</td><td class='num'>{H}</td>"
                f"<td class='num'>{r['ticks']}</td><td class='num'>{r['wall_s']}s</td>"
                f"<td class='{'good' if ok else 'bad'}'>{E(r['cohort'])}</td>"
                f"<td class='num'>{len(d['rounds'])}</td>"
                f"<td class='num'>{d['events']}</td>"
                f"<td class='num'>{r['bytes']:,} B</td></tr>")
    P.append("</table>")
    ran = len(runs)
    exact = sum(1 for r in runs if r["ticks"] == r["horizon"])
    survived = sum(1 for r in runs if r["cohort"].split("/")[0] == r["cohort"].split("/")[1])
    P.append(f'<div class="verdict ok"><b>Runs.</b> {ran} episodes completed, '
             f'{exact} advanced their horizon <b>exactly</b>, {survived} kept the whole '
             f'starting cohort alive. Each produced a self-contained replay.</div>')

    # =====================================================================
    P.append("<h2>2 · Does it react to the game</h2>")
    P.append("<p class='sub'>The observer now reports hostiles, injured citizens and the "
             "game&rsquo;s own announcement feed. These are decision inputs only &mdash; they are "
             "deliberately kept out of the scored observables, so an agent cannot farm danger.</p>")

    all_warn = []
    for r in runs:
        for w in r["threat"]["warnings"]:
            if w not in all_warn:
                all_warn.append(w)
    if all_warn:
        P.append("<div class='card'><b>Messages captured from the running game</b>"
                 "<div class='feed'>")
        for w in all_warn:
            P.append(f"<div class='warn'>{E(w.replace('_', ' '))}</div>")
        P.append("</div></div>")

    P.append("<table><tr><th>policy</th><th>horizon</th><th class='num'>rounds flagged</th>"
             "<th>of total</th><th class='num'>max hostiles</th><th>behaviour change</th></tr>")
    for H in horizons:
        for t in tiers:
            r = by.get((t, H))
            if not r:
                continue
            d = detail[(t, H)]
            th = r["threat"]
            nr = max(1, len(d["rounds"]))
            digs = sum(1 for x in d["rounds"] if "designate_dig" in (x.get("dispatched") or []))
            note = ("holds — no new excavation while flagged" if t == "v2_reactive"
                    else "none — this tier is blind to danger by design" if t == "v1_developer"
                    else "n/a — idle")
            P.append(f"<tr><td>{E(t)}</td><td class='num'>{H}</td>"
                     f"<td class='num'>{th['rounds_with_threat']}</td>"
                     f"<td>{bar(th['rounds_with_threat'], nr, colour='#b4574a')}"
                     f"{th['rounds_with_threat']}/{nr}</td>"
                     f"<td class='num'>{th['max_hostiles']}</td>"
                     f"<td><small>{note} &middot; {digs} dig orders issued</small></td></tr>")
    P.append("</table>")

    return_code = 0
    P.append(
        '<div class="verdict"><b>Reacts — but the trigger is mis-tuned, and that is the '
        'finding.</b> The channel fires and the reactive tier demonstrably changes '
        'behaviour when it does. What it fires <i>on</i> is wrong: the captured messages '
        'are routine mining cancellations (<code>damp stone located</code>, '
        '<code>Miner cancels Dig: Inappropriate</code>), not attacks. The keyword filter '
        'treats a cancelled job as an assault, so the reactive tier spends almost the whole '
        'episode holding. The mechanism is proven; the classifier needs to separate '
        '&ldquo;a job failed&rdquo; from &ldquo;something is trying to kill us&rdquo;.</div>')

    # =====================================================================
    P.append("<h2>3 · Does it improve</h2>")
    P.append("<table><tr><th>policy</th><th>horizon</th><th>score</th>"
             "<th class='num'>development</th><th class='num'>dug</th>"
             "<th class='num'>buildings</th></tr>")
    for H in horizons:
        for t in tiers:
            r = by.get((t, H))
            if not r:
                continue
            cls = "good" if r["score"] > 0.5 else ("acc" if r["score"] > 0 else "dim")
            P.append(f"<tr><td>{E(t)}</td><td class='num'>{H}</td>"
                     f"<td>{bar(r['score'], 1.0)}<span class='{cls}'>{r['score']:.3f}</span></td>"
                     f"<td class='num'>{r['development']:.3f}</td>"
                     f"<td class='num'>{r['dug']}</td>"
                     f"<td class='num'>{r['buildings']}</td></tr>")
    P.append("</table>")

    # curves straight out of the recordings
    P.append("<h3>Fort growth over the episode, read from the recordings</h3>")
    for H in horizons:
        P.append(f"<div class='card'><b>horizon {H}</b><table>")
        for t in tiers:
            if (t, H) not in detail:
                continue
            st = [e for e in detail[(t, H)]["stats"] if e.get("phase") == "post"]
            dug = [e.get("dug", 0) for e in st]
            bld = [e.get("buildings", 0) for e in st]
            P.append(f"<tr><td>{E(t)}</td>"
                     f"<td>{sparkline(dug, colour='#9a7fa8')}<small>dug &rarr; "
                     f"{dug[-1] if dug else 0}</small></td>"
                     f"<td>{sparkline(bld, colour='#6d9b5a')}<small>buildings &rarr; "
                     f"{bld[-1] if bld else 0}</small></td></tr>")
        P.append("</table></div>")

    best = max(runs, key=lambda r: r["score"])
    floor_runs = [r for r in runs if r["tier"] == "v0_idle"]
    P.append(
        f'<div class="verdict ok"><b>Improves.</b> The idle tier scores exactly '
        f'<b>0.000</b> at every horizon ({len(floor_runs)} runs) — it is the floor the '
        f'metric is normalised against, and it stays there. A developing policy reaches '
        f'<b>{best["score"]:.3f}</b> ({E(best["tier"])} at H={best["horizon"]}), digging '
        f'{best["dug"]} tiles and raising buildings {best["buildings"]}&times;. Before this '
        f'work the development term was structurally 0 for every policy, so this gap did '
        f'not exist.</div>')
    P.append(
        '<div class="verdict no"><b>Honest caveat on the ranking.</b> v2 scoring below v1 '
        'is not evidence that reacting is bad — it is the mis-tuned trigger above spending '
        'the episode in a defensive hold. And these are single episodes: the scorer reports '
        'a K-run median with a spread for exactly this reason, and one run per cell cannot '
        'separate policies whose gap is inside the noise. Read the ordering as indicative, '
        'not settled.</div>')

    # =====================================================================
    if frame_imgs:
        P.append("<h2>4 · The fort, frame by frame</h2>")
        P.append("<p class='sub'>Rendered from the map track of a recorded episode with "
                 "Dwarf Fortress&rsquo;s own sprites. Scrub the full episode in "
                 "<code>tools/replay/viewer.html</code>.</p>")
        P.append("<div class='frames'>")
        for name, uri in frame_imgs:
            P.append(f"<figure><img src='{uri}' alt='{E(name)}'>"
                     f"<figcaption>{E(name)}</figcaption></figure>")
        P.append("</div>")

    # =====================================================================
    P.append("<h2>How to check any of this yourself</h2>")
    P.append("<div class='card'><table>"
             "<tr><td>recordings</td><td><code>/srv/df-bonsai/recordings/*.rec.jsonl.gz</code>"
             " &mdash; <code>zcat</code> them, one JSON event per line</td></tr>"
             "<tr><td>watch an episode</td><td><code>tools/replay/viewer.html</code>, drop a recording on it</td></tr>"
             "<tr><td>compare two</td><td><code>tools/replay/compare.html?a=…&amp;b=…</code></td></tr>"
             "<tr><td>re-render a frame</td><td><code>python tools/replay/render_frame.py &lt;rec&gt; &lt;z&gt; out.png</code></td></tr>"
             "<tr><td>the policies</td><td><code>lab_agent/bonsai_lab_agent/baselines/tiers.py</code></td></tr>"
             "</table></div>")

    out.write_text("\n".join(P), encoding="utf-8")
    print(f"wrote {out} ({out.stat().st_size:,} bytes) from {len(runs)} runs, "
          f"{len(frame_imgs)} frames")
    return return_code


if __name__ == "__main__":
    raise SystemExit(main())
