from pathlib import Path

def get_config_path() -> Path:
    """Get the default configuration file path."""
    return Path.home() / ".mybot" / "config.json"

def get_worksapce_path() -> Path:
    """Get the workspace path."""
    return Path.home() / ".mybot" / "workspace"

def get_history_path() -> Path:
    """Get the history path."""
    return Path.home() / ".mybot" / "history"
