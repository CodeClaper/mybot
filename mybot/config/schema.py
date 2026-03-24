from dataclasses import field
from openai.types.responses.tool_param import WebSearchTool
from pydantic import BaseModel, ConfigDict, Field
from pydantic.alias_generators import to_camel
from pydantic_settings import BaseSettings

class Base(BaseModel):
    """Base model"""
    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True)

class AgentDefaults(Base):
    """Agent default configuration."""
    model: str = "deepseek/deepseek-chat"
    provider: str = "auto"  # Provider name (e.g. "anthropic", "openrouter") or "auto" for auto-detection
    max_tokens: int = 8192
    temperature: float = 0.1
    max_tool_iterations: int = 40
    memory_window: int = 100
    reasoning_effort: str | None = None  # low / medium / high — enables LLM thinking mode


class AgentsConfig(Base):
    """Agent configuration."""
    defaults: AgentDefaults = Field(default_factory=AgentDefaults)

class ChannelsConfig(Base):
    """Channels configuration."""
    
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
    

class Config(BaseSettings):
    """Root configuration."""
    
    agents: AgentsConfig = Field(default_factory=AgentsConfig)
    channels: ChannelsConfig = Field(default_factory=ChannelsConfig)
    providers: ProvidersConfig = Field(default_factory=ProvidersConfig)
    tools: ToolConfig = Field(default_factory=ToolConfig)
