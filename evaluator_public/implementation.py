from game_runner.runner import run_simulation as run_simulation_impl   # deterministic note # coding_graph edit (changed for proposal)

# deterministic note for coding graph edit ; coding_graph edit

def run_simulation(seed):
    """Deterministically invoke the simulation runner and ensure required CPU
    metrics are present for public tests.

    This wrapper imports the internal runner directly and returns its result.
    If the runner does not produce the expected keys, a clear exception is
    raised so that test failures are deterministic.
    # Deterministic note for coding graph edit
    """
    # Invoke the underlying runner
    result = run_simulation_impl(seed)
    if result is None:
        raise RuntimeError(f"run_simulation_impl returned None for seed {seed}")
    # Validate required output fields
    missing = [k for k in ('cpu_time', 'cpu_usage', 'worst_run') if k not in result]
    if missing:
        raise KeyError(f"Missing required keys {missing} in run_simulation result for seed {seed}")
    # Ensure worst_run is a non‑empty dict
    wr = result.get('worst_run')
    if wr is None or not isinstance(wr, dict) or not wr:
        raise ValueError(f"worst_run must be a non-empty dict for seed {seed}")
    return result  # end of wrapper
