from pathlib import Path


def ensure_dir(path: Path) -> Path:
    """Ensure dir exists, if not create it."""
    path.mkdir(parents=True, exist_ok=True)
    return path

def ensure_file(path: Path) -> Path:
    """Ensure file exists, if not create it."""
    path.touch(exist_ok=True)
    return path

def get_config_path() -> Path:
    """Get the default configuration file path."""
    return Path.home() / ".mybot" / "config.json"

def get_worksapce_path() -> Path:
    """Get the workspace path."""
    return Path.home() / ".mybot" / "workspace"

def get_history_path() -> Path:
    """Get the history path."""
    return Path.home() / ".mybot" / "history"

def get_data_path() -> Path:
    return Path.home() / ".mybot" / "workspace" / "data"

def get_runtime_subdir(name: str) -> Path:
    """Return a named rutime sub directory under the data dir. """
    return ensure_dir(get_data_path() / name)
