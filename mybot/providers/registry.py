from dataclasses import dataclass
from pydantic.alias_generators import to_snake

@dataclass()
class ProviderSpec:
    """LLM provider's metadata. """
    
    name: str
    keywords: tuple[str, ...]
    env_key: str
    display_name: str = ""
    litellm_prefix: str = ""

    @property
    def label(self) -> str:
        return self.display_name or self.name.title()


PROVIDERS: tuple[ProviderSpec, ...] = (
    ProviderSpec(
        name="local",
        keywords=("local", "custom"),
        env_key="",
        display_name="Custom",
    ),
    ProviderSpec(
        name="deepseek",
        keywords=("deepseek",),
        env_key="DEEPSEEK_API_KEY",
        display_name="DeepSeek",
        litellm_prefix="deepseek",  # deepseek-chat -> deepseek/deepseek-chat
    ),
    ProviderSpec(
        name="minimax",
        keywords=("minimax", "m3", "m2"),
        env_key="MINIMAX_API_KEY",
        display_name="MiniMax",
        litellm_prefix="minimax",
    ),
    ProviderSpec(
        name="moonshot",
        keywords=("deepseek", "kimi"),
        env_key="MOONSHOT_API_KEY",
        display_name="MoonShot",
        litellm_prefix="moonshot",  # kimi-k2.5 -> moonshot/kimi-k2
    )
)




# ---------------------------------------------------------------------------
# Lookup helpers
# ---------------------------------------------------------------------------

def find_by_name(name: str) -> ProviderSpec | None:
    """Find a provider spec by config field name, e.g. "dashscope"."""
    normalized = to_snake(name.replace("-", "_"))
    for spec in PROVIDERS:
        if spec.name == normalized:
            return spec
    return None
