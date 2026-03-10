import json
from pathlib import Path

from mybot.config.schema import Config

def get_config_path() -> Path:
    """Get the default configuration file path."""
    return Path.home() / ".mybot" / "config.json"

def get_worksapce_path() -> Path:
    """Get the workspace path."""
    return Path.home() / ".mybot" / "workspace"


def load_config() -> Config:
    """
    Load configuration fro file or create a default.
    """

    path = get_config_path()
    
    if path.exists():
        try:
            with open(path, encoding="utf-8") as f:
                data = json.load(f)
            return Config.model_validate(data)
        except (json.JSONDecodeError, ValueError) as e:
            print(f"Warning: Fail to load config from {path}: {e}")
            print("Using defaul configuration.")

    return Config()


def save_config(config: Config) -> None:
    """
    Save configuration to file.
    """

    path = get_config_path()
    path.parent.mkdir(parents=True, exist_ok=True)

    data = config.model_dump(by_alias=True)

    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)

