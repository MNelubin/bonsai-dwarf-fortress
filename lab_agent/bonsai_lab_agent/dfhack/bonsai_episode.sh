#!/usr/bin/env bash
# Canonical single DF episode on port 5001 (keeps supervised df-runtime DF on 5000 alive).
# Usage: bonsai_episode.sh <horizon_ticks> <suppress_wildlife:0|1>
HORIZON=${1:-3600}; SUPPRESS=${2:-0}; SETUP=${3:-}; PORT=5001
cd /srv/df-bonsai/current
sup(){ ss -ltnp 2>/dev/null | grep 127.0.0.1:5000 | grep -oE 'pid=[0-9]+' | cut -d= -f2 | head -1; }
run(){ DFHACK_PORT=$PORT timeout 25 ./hack/dfhack-run "$@" 2>/dev/null | sed 's/\x1b\[[0-9;]*m//g'; }
scr(){ run screen-dump 2>/dev/null | grep -aE '\|'; }
click(){ printf '%s\n' "$1" > click_target.txt; run click-text >/dev/null 2>&1; }
getnum(){ run lua "print(($1))" | grep -aoE '[-]?[0-9]+' | head -1; }
click_until(){ for t in $(seq 1 ${3:-10}); do scr | grep -qiE "$2" && return 0; click "$1"; sleep 3; done; scr | grep -qiE "$2"; }
S=$(sup); for p in $(pgrep -x dwarfort); do [ "$p" != "$S" ] && kill -9 $p 2>/dev/null; done; sleep 1
( sleep 260; SS=$(ss -ltnp 2>/dev/null|grep 127.0.0.1:5000|grep -oE 'pid=[0-9]+'|cut -d= -f2|head -1); for p in $(pgrep -x dwarfort); do [ "$p" != "$SS" ] && kill -9 $p 2>/dev/null; done ) >/dev/null 2>&1 &
setsid env DFHACK_PORT=$PORT DF_PRELOAD=$PWD/detshim2.so LD_PRELOAD=$PWD/detshim2.so HOME=$PWD/spike-home XDG_RUNTIME_DIR=$PWD/spike-home DFHACK_HEADLESS=1 DFHACK_DISABLE_CONSOLE=1 SDL_AUDIODRIVER=dummy TERM=dumb ./dfhack --exec > boot_mine.log 2>&1 </dev/null &
disown
for i in $(seq 1 50); do ss -ltn 2>/dev/null | grep -q 127.0.0.1:$PORT && break; sleep 2; done; sleep 3
click_until "Continue active game" "Planets of Dawning" 10 || { echo "LOADFAIL:worldlist"; exit 1; }
click_until "The Planets of Dawning" "bonsaifort2" 10 || { echo "LOADFAIL:savelist"; exit 1; }
click "bonsaifort2"
for i in $(seq 1 40); do sleep 2; [ "$(getnum 'df.global.cur_year_tick')" != "0" ] && break; done
run bonsai-headless-init >/dev/null
[ "$SUPPRESS" = "1" ] && run bonsai-nowild >/dev/null
run lua "df.global.world.status.popups:resize(0); df.global.pause_state=true" >/dev/null
obs(){ run bonsai-observe | grep -a OBS; }
echo "OBS_T0 $(obs)"
[ -n "$SETUP" ] && echo "SETUP $(run $SETUP)"
printf '%s\n' "$HORIZON" > advance_n.txt
sf=$(getnum 'df.global.world.frame_counter'); tgt=$((sf+HORIZON))
run bonsai-advance2 >/dev/null
for i in $(seq 1 130); do fc=$(getnum 'df.global.world.frame_counter'); { [ "${fc:-0}" -ge "$tgt" ] && [ "$(run lua "print(df.global.pause_state)"|grep -c true)" = "1" ]; } && break; sleep 1; done
echo "OBS_H $(obs)"
S=$(sup); for p in $(pgrep -x dwarfort); do [ "$p" != "$S" ] && kill -9 $p 2>/dev/null; done
echo "EPISODE_DONE"
