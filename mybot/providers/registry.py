from dataclasses import dataclass


@dataclass()
class ProviderSpec:
    """LLM provider's metadata. """
    
    name: str
    keywords: tuple[str, ...]
    env_key: str
    display_name: str = ""
    litellm_prefix: str = ""


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
        name="moonshot",
        keywords=("deepseek", "kimi"),
        env_key="MOONSHOT_API_KEY",
        display_name="MoonShot",
        litellm_prefix="moonshot",  # kimi-k2.5 -> moonshot/kimi-k2
    )
)

