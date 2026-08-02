"""Teach the lab-agent reaper about scored episodes.

Applied to the DEPLOYED worker.py in the venv, not to the repo copy: worker.py is the
untrusted agent's own worker and carries another workstream's changes, so the evaluator
does not edit it in-tree. Running this twice is a no-op — it always rewrites the same
block between two stable markers.

Two things it fixes, both observed live killing real runs:

1. The lease is an EXPIRY, not a PID. A PID can only be written once DF's port is open,
   leaving ~20 s in which the fort is alive but unlabelled; the reaper runs on a loop and
   was caught killing a fort mid-load in exactly that window.

2. The lease is PER PORT. Parallel episodes each claim episode.lease.<port>, and a reaper
   that only looked at the single episode.lease saw no claim at all — it killed all three
   forts of the first parallel run about a minute after they finished booting.

Protection stays all-or-nothing: any live lease disables reaping entirely, so a leaked
probe can outlive its welcome while a year-long episode runs. That was already true of
the single-file lease, and an expiry bounds it.
"""
import pathlib
import sys

TARGET = pathlib.Path(
    "/opt/bonsai-lab-agent/venv/lib/python3.13/site-packages/bonsai_lab_agent/worker.py")

END = "def reap_df_probe_processes("

NEW = '''EPISODE_LEASE = DF_RUNTIME_ROOT / "episode.lease"
EPISODE_LEASE_GLOB = "episode.lease.*"          # one per episode port


def lease_is_active(now: float | None = None) -> bool:
    """True while ANY scored episode has claimed the host.

    An episode DF started by the evaluator lives in the EVALUATOR's cgroup, so the
    supervised-cgroup check cannot tell it from a leaked probe, and reaping it kills a
    scored run mid-flight — which reaches the agent as a spurious episode_failed it did
    not cause.

    The lease is an EXPIRY, not a PID: it is claimed before the process exists, so the
    boot window is covered, and it cannot protect strays forever — once it lapses the
    reaper resumes on its own.

    Every episode port writes its own lease file. Reading only the unsuffixed name meant
    three parallel forts held three leases the reaper could not see, and it shot all of
    them.
    """
    moment = now if now is not None else time.time()
    candidates = [EPISODE_LEASE]
    try:
        candidates.extend(sorted(DF_RUNTIME_ROOT.glob(EPISODE_LEASE_GLOB)))
    except OSError:
        pass
    for path in candidates:
        try:
            raw = path.read_text(encoding="utf-8", errors="replace").strip()
        except (FileNotFoundError, OSError, PermissionError):
            continue
        try:
            expiry = float(raw.split()[0])
        except (ValueError, IndexError):
            continue
        if moment < expiry:
            return True
    return False


'''

GUARD = ('    if lease_is_active():\n'
         '        return {"targets": [], "sigkill": [], "protected": [],\n'
         '                "skipped": "scored episode holds the lease"}\n'
         '    protected = supervised_df_runtime_process_ids()')


def main() -> int:
    s = TARGET.read_text(encoding="utf-8")
    for marker in ("def leased_episode_process_ids(", 'EPISODE_LEASE = '):
        if marker in s:
            start = s.index(marker)
            break
    else:
        print("REAPER: no lease block to replace — worker.py layout changed", file=sys.stderr)
        return 1
    if END not in s:
        print(f"REAPER: {END!r} not found — worker.py layout changed", file=sys.stderr)
        return 1
    s = s[:start] + NEW + s[s.index(END):]
    s = s.replace(
        "    protected = supervised_df_runtime_process_ids() | leased_episode_process_ids()",
        GUARD)
    if GUARD not in s:
        print("REAPER: reap_df_probe_processes has no lease guard", file=sys.stderr)
        return 1
    TARGET.write_text(s, encoding="utf-8")
    print("REAPER: honours a per-port expiry lease")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
