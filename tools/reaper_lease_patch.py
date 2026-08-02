"""Lease is an expiry timestamp, not a PID — closes the boot-window race."""
import pathlib, sys
p = pathlib.Path("/opt/bonsai-lab-agent/venv/lib/python3.13/site-packages/bonsai_lab_agent/worker.py")
s = p.read_text(encoding="utf-8")
if "lease_is_active" in s:
    print("REAPER already on the expiry lease"); sys.exit(0)

old_start = s.index("def leased_episode_process_ids(")
old_end = s.index("def reap_df_probe_processes(")
new = '''def lease_is_active(now: float | None = None) -> bool:
    """True while a scored episode has claimed the host.

    An episode DF started by the evaluator lives in the EVALUATOR's cgroup, so the
    supervised-cgroup check cannot tell it from a leaked probe, and reaping it kills a
    scored run mid-flight — which reaches the agent as a spurious episode_failed it did
    not cause.

    The lease is an EXPIRY, not a PID. A PID can only be written once the port is open,
    which leaves ~20 seconds in which DF is alive but unlabelled; the reaper runs on a
    loop and was observed killing a fort mid-load in exactly that window. An expiry is
    claimed before the process exists and cannot protect strays forever: once it lapses
    the reaper resumes on its own.
    """
    try:
        raw = EPISODE_LEASE.read_text(encoding="utf-8", errors="replace").strip()
    except (FileNotFoundError, OSError, PermissionError):
        return False
    try:
        expiry = float(raw.split()[0])
    except (ValueError, IndexError):
        return False
    return (now if now is not None else time.time()) < expiry


'''
s = s[:old_start] + new + s[old_end:]
s = s.replace(
    "    protected = supervised_df_runtime_process_ids() | leased_episode_process_ids()",
    "    if lease_is_active():\n"
    "        return {\"targets\": [], \"sigkill\": [], \"protected\": [],\n"
    "                \"skipped\": \"scored episode holds the lease\"}\n"
    "    protected = supervised_df_runtime_process_ids()")
p.write_text(s, encoding="utf-8")
print("REAPER: honours an expiry lease")
