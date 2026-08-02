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
# Kill ONLY the DF on our own port. Killing every non-supervised dwarfort means
# booting a second episode murders the first, which is what made parallel K-runs
# impossible and forced everything to run one at a time.
kill_mine(){ local P; P=$(ss -ltnp 2>/dev/null | grep "127.0.0.1:$PORT" | grep -oE 'pid=[0-9]+' | cut -d= -f2 | head -1); [ -n "$P" ] && kill -9 "$P" 2>/dev/null; return 0; }

case "$CMD" in
kill)
  rm -f /srv/df-bonsai/episode.lease.$PORT
  kill_mine; sleep 1
  echo "KILLED supervised_still=$(sup)"
  ;;

boot)
  WD=${2:-1800}                 # hard backstop; session.py also kills in a finally block
  SAVE=${3:-bonsaifort2}
  echo "SUPERVISED_PID=$(sup)"
  kill_mine; sleep 1

  # Claim the reaper lease BEFORE booting. Writing a PID only after the port opens
  # leaves ~20s in which DF is alive but unlabelled, and the lab-agent reaper fires
  # on a loop — observed killing a fort mid-load. The lease is an EXPIRY, so a
  # crashed session cannot protect strays forever: once it lapses the reaper resumes.
  echo $(( $(date +%s) + WD )) > /srv/df-bonsai/episode.lease.$PORT

  # Detached watchdog. It must OUTLIVE this script (the session stays up afterwards),
  # so setsid it — but it is armed AFTER the boot below, against that one PID.
  #
  # It used to kill "any dwarfort that is not the supervised one", which meant a
  # watchdog left over from an EARLIER session would murder a later, unrelated run when
  # its timer expired. That is what killed both full-year episodes: a 30-minute
  # watchdog armed during a short ladder run fired half an hour later, in the middle of
  # a year-long episode it knew nothing about. Any long run was a lottery against every
  # timer still ticking from every boot before it.

  setsid env DFHACK_PORT=$PORT DF_PRELOAD=$PWD/detshim2.so LD_PRELOAD=$PWD/detshim2.so \
    HOME=$PWD/spike-home XDG_RUNTIME_DIR=$PWD/spike-home DFHACK_HEADLESS=1 \
    DFHACK_DISABLE_CONSOLE=1 SDL_AUDIODRIVER=dummy TERM=dumb \
    ./dfhack --exec > boot_session.log 2>&1 </dev/null &
  disown

  for i in $(seq 1 50); do ss -ltn 2>/dev/null | grep -q 127.0.0.1:$PORT && break; sleep 2; done
  ss -ltn 2>/dev/null | grep -q 127.0.0.1:$PORT || { echo "BOOTFAIL:noport"; exit 1; }

  # Arm the watchdog on THIS DF only, and let it stand down quietly if the session
  # already ended cleanly.
  MYPID=$(ss -ltnp 2>/dev/null | grep 127.0.0.1:$PORT | grep -oE 'pid=[0-9]+' | cut -d= -f2 | head -1)
  # Declare this DF as a legitimate scored episode. The lab-agent reaper kills every
  # dwarfort that is not in the supervised cgroup, and an episode started by the
  # evaluator sits in the EVALUATOR's cgroup — so without this it is indistinguishable
  # from a leaked probe and gets shot mid-episode. That killed three year-long runs and
  # would surface in production as a spurious episode_failed the agent gets blamed for.
  # A stale lease is harmless: the reaper checks the PID is still a live dwarfort.
  if [ -n "$MYPID" ]; then
    setsid bash -c "sleep $WD; kill -9 $MYPID 2>/dev/null" >/dev/null 2>&1 &
    disown 2>/dev/null || true
  fi
  sleep 3

  # Menu navigation goes through a SHARED click_target.txt, so parallel boots click
  # each other's targets — three simultaneous boots produced two LOADFAIL:savelist.
  # Serialise only this phase: it is ~40s, while the part worth parallelising is the
  # multi-minute advance that follows. Three year-long episodes then cost one boot
  # queue plus one year, not three years.
  exec 9>/srv/df-bonsai/boot.lock
  flock 9
  click_until "Continue active game" "Planets of Dawning" 10 || { echo "LOADFAIL:worldlist"; exit 1; }
  click_until "The Planets of Dawning" "$SAVE" 10             || { echo "LOADFAIL:savelist"; exit 1; }
  click "$SAVE"
  for i in $(seq 1 40); do sleep 2; [ "$(getnum 'df.global.cur_year_tick')" != "0" ] && break; done
  [ "$(getnum 'df.global.cur_year_tick')" != "0" ] || { echo "LOADFAIL:notick"; exit 1; }

  flock -u 9                      # menus done; the rest is per-port and safe in parallel
  run bonsai-headless-init >/dev/null
  run lua "df.global.world.status.popups:resize(0); df.global.pause_state=true" >/dev/null
  echo "READY port=$PORT tick=$(getnum 'df.global.cur_year_tick') frame=$(getnum 'df.global.world.frame_counter')"
  ;;

*)
  echo "usage: bonsai_session.sh {boot [watchdog_s] [save]|kill}" >&2; exit 2 ;;
esac
