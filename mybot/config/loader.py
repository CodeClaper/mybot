from pathlib import Path


def get_config_path() -> Path:
    """Get the default configuration file path."""
    return Path.home() / ".mybot" / "config.json"
