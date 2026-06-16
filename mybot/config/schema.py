from typing import Any, Literal
from pydantic import AliasChoices, BaseModel, ConfigDict, Field
from pydantic.alias_generators import to_camel
from pydantic_settings import BaseSettings

DEFAULT_LONG_POLL_TIMEOUT_S = 35

class Base(BaseModel):
    """Base model"""
    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True)


class AgentDefaults(Base):
    """Agent default configuration."""
    model_preset: str | None = None  # Active preset name — takes precedence over fields below
    model: str = "deepseek-v4-pro"
    provider: str = "deepseek"  # Provider name (e.g. "anthropic", "openrouter") or "auto" for auto-detection
    max_tokens: int = 8192
    context_window_tokens: int = 65_536
    temperature: float = 0.1
    max_tool_iterations: int = 40
    memory_window: int = 100
    reasoning_effort: str | None = None  # low / medium / high — enables LLM thinking mode


class AgentsConfig(Base):
    """Agent configuration."""
    defaults: AgentDefaults = Field(default_factory=AgentDefaults)

class WeixinConfig(Base):
    """Person weixin channel configuration."""
    enabled: bool = False
    allow_list: list[str] = Field(default_factory=list)
    base_url: str = "https://ilinkai.weixin.qq.com"
    cdn_base_url: str = "https://novac2c.cdn.weixin.qq.com/c2c"
    poll_timeout: int = DEFAULT_LONG_POLL_TIMEOUT_S

class DiscordConfig(Base):
    """Discord channel configuration."""
    enabled: bool = False
    token: str = ""
    allow_from: list[str] = Field(default_factory=list)
    intents: int = 37377
    group_policy: Literal["mention", "open"] = "mention"
    read_receipt_emoji: str = "👀"
    working_emoji: str = "🔧"
    working_emoji_delay: float = 2.0
    streaming: bool = True
    proxy: str | None = None
    proxy_username: str | None = None
    proxy_password: str | None = None


class WebSocketConfig(Base):
    """Websocket channel configuration."""
    enabled: bool = False
    host: str = "127.0.0.1"
    port: int = 8765
    path: str = "/"
    token: str = ""
    token_issue_path: str = ""
    token_issue_secret: str = ""
    token_ttl_s: int = Field(default=300, ge=30, le=86_400)
    websocket_requires_token: bool = True
    allow_from: list[str] = Field(default_factory=lambda: ["*"])
    streaming: bool = True
    # Default 36 MB, upper 40 MB: supports up to 4 images at ~6 MB each after
    # client-side Worker normalization (see webui Composer). 4 × 6 MB × 1.37
    # (base64 overhead) + envelope framing stays under 36 MB; the 40 MB ceiling
    # leaves a small margin for sender slop without opening a DoS avenue.
    max_message_bytes: int = Field(default=37_748_736, ge=1024, le=41_943_040)
    ping_interval_s: float = Field(default=20.0, ge=5.0, le=300.0)
    ping_timeout_s: float = Field(default=20.0, ge=5.0, le=300.0)
    ssl_certfile: str = ""
    ssl_keyfile: str = ""


class ChannelsConfig(Base):
    """Channels configuration."""
    weixin: WeixinConfig = Field(default_factory=WeixinConfig) 
    discord: DiscordConfig = Field(default_factory=DiscordConfig)
    websocket: WebSocketConfig = Field(default_factory=WebSocketConfig)

    
class ProviderConfig(Base):
    """LLM provider configuration. """

    api_key: str = ""
    api_base: str | None = None

class ProvidersConfig(Base):
    """LLM providers configuration. """

    anthropic: ProviderConfig = Field(default_factory=ProviderConfig)
    openai: ProviderConfig = Field(default_factory=ProviderConfig)
    gemini: ProviderConfig = Field(default_factory=ProviderConfig)
    openrouter: ProviderConfig = Field(default_factory=ProviderConfig)
    deepseek: ProviderConfig = Field(default_factory=ProviderConfig)
    groq: ProviderConfig = Field(default_factory=ProviderConfig)
    zhipu: ProviderConfig = Field(default_factory=ProviderConfig)
    vllm: ProviderConfig = Field(default_factory=ProviderConfig)
    minimax: ProviderConfig = Field(default_factory=ProviderConfig)
    moonshot: ProviderConfig = Field(default_factory=ProviderConfig)
    local: ProviderConfig = Field(default_factory=ProviderConfig)

class GatewayConfig(Base):
    """Gateway server configuration."""
    
    host: str = "0.0.0.0"
    port: int = 8118

class WebSearchConfig(Base):
    """Web search tool configuration."""
    
    api_key: str = ""
    max_results: int = 10
    url: str = ""


class WebToolsConfig(Base):
    """Web tools configuration. """
    proxy: str | None = None
    search: WebSearchConfig = Field(default_factory=WebSearchConfig)

class ToolConfig(Base):
    """Tool configuration. """

    web: WebToolsConfig = Field(default_factory=WebToolsConfig)
    

class ModelPresetConfig(Base):
    """A named set of model + generation parameters for quick switching."""

    model: str
    provider: str = "auto"
    max_tokens: int = 8192
    context_window_tokens: int = 65_536
    temperature: float = 0.1
    reasoning_effort: str | None = None

    def to_generation_settings(self) -> Any:
        from mybot.providers.base import GenerationSettings
        return GenerationSettings(
            temperature=self.temperature,
            max_tokens=self.max_tokens,
            reasoning_effort=self.reasoning_effort,
        )

class Config(BaseSettings):
    """Root configuration."""
    
    agents: AgentsConfig = Field(default_factory=AgentsConfig)
    channels: ChannelsConfig = Field(default_factory=ChannelsConfig)
    gateway: GatewayConfig = Field(default_factory=GatewayConfig)
    providers: ProvidersConfig = Field(default_factory=ProvidersConfig)
    tools: ToolConfig = Field(default_factory=ToolConfig)
    model_presets: dict[str, ModelPresetConfig] = Field(
        default_factory=dict,
        validation_alias=AliasChoices("modelPresets", "model_presets"),
    )

    def _match_provider(
        self, provider_name: str | None
    ) -> tuple[ProviderConfig | None, str | None]:
        from mybot.providers.registry import PROVIDERS
        provider_lower = (provider_name or self.agents.defaults.provider).lower()
        for spec in PROVIDERS:
            p = getattr(self.providers, spec.name, None)
            if p and provider_lower and provider_lower == spec.name:
                return p, spec.name
        return None, None

    def get_provider(self, provider_name: str | None) -> ProviderConfig | None:
        """Get approciate provider by model. """
        provider, _ = self._match_provider(provider_name)
        return provider

    def resolve_default_preset(self) -> ModelPresetConfig:
        """Return the implicit `default` preset from agents.defaults fields."""
        d = self.agents.defaults
        return ModelPresetConfig(
            model=d.model, provider=d.provider, max_tokens=d.max_tokens,
            context_window_tokens=d.context_window_tokens,
            temperature=d.temperature, reasoning_effort=d.reasoning_effort,
        )

    def resolve_preset(self, name: str | None = None) -> ModelPresetConfig:
        """Return effective model params from a named preset or the implicit default."""
        name = self.agents.defaults.model_preset if name is None else name
        if not name or name == "default":
            return self.resolve_default_preset()
        if name not in self.model_presets:
            raise KeyError(f"model_preset {name!r} not found in model_presets")
        return self.model_presets[name]
