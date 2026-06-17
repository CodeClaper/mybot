import sys
from pathlib import Path


def ensure_dir(path: Path) -> Path:
    """Ensure dir exists, if not create it."""
    path.mkdir(parents=True, exist_ok=True)
    return path

def ensure_file(path: Path) -> Path:
    """Ensure file exists, if not create it."""
    path.touch(exist_ok=True)
    return path

def get_home_path() -> Path:
    """Get mybot home path."""
    return Path.home() / ".mybot" 

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
    """Get data path."""
    return Path.home() / ".mybot" / "data"

def get_runtime_subdir(name: str) -> Path:
    """Return a named rutime sub directory under the data dir. """
    return ensure_dir(get_data_path() / name)

def get_media_dir(channel: str | None = None) -> Path:
    """Return the media directory, optionally namespaced per channel."""
    base = get_runtime_subdir("media")
    return ensure_dir(base / channel) if channel else base


def get_package_dir() -> Path:
    """Return the mybot package directory.

    Works in dev mode (from source) and PyInstaller frozen mode.
    """
    if getattr(sys, 'frozen', False):
        return Path(sys._MEIPASS) / "mybot"
    return Path(__file__).parent.parent


def get_web_dist_path() -> Path | None:
    """Return the web dist directory if it exists, else None."""
    dist = get_package_dir() / "web" / "dist"
    return dist if dist.is_dir() else None
