#!/usr/bin/env bash
# Persistent DF session for the STEPPED episode driver (interaction model B).
#
# Splits the proven one-shot bonsai_episode.sh into phases so a Python driver can
# run a real loop: observe -> controller decides -> apply intents -> advance a chunk
# -> observe -> ... The fragile boot/load/prep sequence is kept here verbatim
# (battle-tested); everything after READY is issued by session.py over dfhack-run.
#
# Subcommands:
#   boot [watchdog_s] [save]  boot DF on 5001, load the pinned save, prep, print READY
#   kill                      kill every dwarfort EXCEPT the supervised one on 5000
#
# INVARIANT: the supervised df-runtime DF on port 5000 is NEVER killed - it provides
# the shared init environment without which our own boot hangs.
set -u
CMD=${1:-boot}
PORT=${BONSAI_EPISODE_PORT:-5001}
cd /srv/df-bonsai/current || exit 1

sup(){ ss -ltnp 2>/dev/null | grep 127.0.0.1:5000 | grep -oE 'pid=[0-9]+' | cut -d= -f2 | head -1; }
run(){ DFHACK_PORT=$PORT timeout 25 ./hack/dfhack-run "$@" 2>/dev/null | sed 's/\x1b\[[0-9;]*m//g'; }
scr(){ run screen-dump 2>/dev/null | grep -aE '\|'; }
click(){ printf '%s\n' "$1" > click_target.txt; run click-text >/dev/null 2>&1; }
getnum(){ run lua "print(($1))" | grep -aoE '[-]?[0-9]+' | head -1; }
click_until(){ for t in $(seq 1 ${3:-10}); do scr | grep -qiE "$2" && return 0; click "$1"; sleep 3; done; scr | grep -qiE "$2"; }
kill_mine(){ local S; S=$(sup); for p in $(pgrep -x dwarfort); do [ "$p" != "$S" ] && kill -9 "$p" 2>/dev/null; done; }

case "$CMD" in
kill)
  kill_mine; sleep 1
  echo "KILLED supervised_still=$(sup)"
  ;;

boot)
  WD=${2:-1800}                 # hard backstop; session.py also kills in a finally block
  SAVE=${3:-bonsaifort2}
  echo "SUPERVISED_PID=$(sup)"
  kill_mine; sleep 1

  # Detached watchdog: must OUTLIVE this script (the session stays up afterwards),
  # so setsid it. Never kills the supervised DF - it re-reads port 5000 at fire time.
  setsid bash -c "sleep $WD; SS=\$(ss -ltnp 2>/dev/null|grep 127.0.0.1:5000|grep -oE 'pid=[0-9]+'|cut -d= -f2|head -1); \
    for p in \$(pgrep -x dwarfort); do [ \"\$p\" != \"\$SS\" ] && kill -9 \$p 2>/dev/null; done" >/dev/null 2>&1 &
  disown 2>/dev/null || true

  setsid env DFHACK_PORT=$PORT DF_PRELOAD=$PWD/detshim2.so LD_PRELOAD=$PWD/detshim2.so \
    HOME=$PWD/spike-home XDG_RUNTIME_DIR=$PWD/spike-home DFHACK_HEADLESS=1 \
    DFHACK_DISABLE_CONSOLE=1 SDL_AUDIODRIVER=dummy TERM=dumb \
    ./dfhack --exec > boot_session.log 2>&1 </dev/null &
  disown

  for i in $(seq 1 50); do ss -ltn 2>/dev/null | grep -q 127.0.0.1:$PORT && break; sleep 2; done
  ss -ltn 2>/dev/null | grep -q 127.0.0.1:$PORT || { echo "BOOTFAIL:noport"; exit 1; }
  sleep 3

  click_until "Continue active game" "Planets of Dawning" 10 || { echo "LOADFAIL:worldlist"; exit 1; }
  click_until "The Planets of Dawning" "$SAVE" 10             || { echo "LOADFAIL:savelist"; exit 1; }
  click "$SAVE"
  for i in $(seq 1 40); do sleep 2; [ "$(getnum 'df.global.cur_year_tick')" != "0" ] && break; done
  [ "$(getnum 'df.global.cur_year_tick')" != "0" ] || { echo "LOADFAIL:notick"; exit 1; }

  run bonsai-headless-init >/dev/null
  run lua "df.global.world.status.popups:resize(0); df.global.pause_state=true" >/dev/null
  echo "READY port=$PORT tick=$(getnum 'df.global.cur_year_tick') frame=$(getnum 'df.global.world.frame_counter')"
  ;;

*)
  echo "usage: bonsai_session.sh {boot [watchdog_s] [save]|kill}" >&2; exit 2 ;;
esac
