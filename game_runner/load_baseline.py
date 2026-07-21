def load_baseline(name: str):
    """Load a named baseline configuration.

    Baselines are stored as JSON files under the project's "baselines/" directory.
    This function loads the file, parses JSON, and returns the resulting object.
    If the baseline does not exist or contains invalid data a RuntimeError is raised.
    """
    import json
    import pathlib
    baselines_dir = pathlib.Path(__file__).parent / "baselines"
    file_path = baselines_dir / f"{name}.json"
    if not file_path.is_file():
        raise RuntimeError(f"Baseline '{name}' not found at {file_path}")
    with file_path.open('r', encoding='utf-8') as f:
        data = json.load(f)
    return data
