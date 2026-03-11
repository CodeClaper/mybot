import questionary
from rich.console import Console

from mybot.config.schema import Config

console = Console()

def question_config(config: Config):
    """
    Config via questionary step by step.
    """
    _question_provider(config)
    _question_agent_default(config)

def _question_provider(config: Config):
    """
    Config for provider.
    """

    console.print("(1) Config the LLM provider.")

    provider = questionary.select("Select your LLM provider: ", choices=[
        "anthropic", "openai", "gemini", "openrouter", "openrouter", 
        "deepseek", "groq", "zhipu", "vllm", "minimax", "moonshot" 
    ]).ask()
    api_key = questionary.text("Input your api key:").ask()
    api_base = questionary.text("Input your api base:").ask()

    match provider:
        case "anthropic":
            config.providers.anthropic.api_key = api_key
            config.providers.anthropic.api_base = api_base
        case "openai":
            config.providers.openai.api_key = api_key
            config.providers.openai.api_base = api_base
        case "gemini":
            config.providers.gemini.api_key = api_key
            config.providers.gemini.api_base = api_base
        case "openrouter":
            config.providers.openrouter.api_key = api_key
            config.providers.openrouter.api_base = api_base
        case "deepseek":
            config.providers.deepseek.api_key = api_key
            config.providers.deepseek.api_base = api_base
        case "groq":
            config.providers.groq.api_key = api_key
            config.providers.groq.api_base = api_base
        case "zhipu":
            config.providers.zhipu.api_key = api_key
            config.providers.zhipu.api_base = api_base
        case "vllm":
            config.providers.vllm.api_key = api_key
            config.providers.vllm.api_base = api_base
        case "minimax":
            config.providers.minimax.api_key = api_key
            config.providers.minimax.api_base = api_base
        case "moonshot":
            config.providers.moonshot.api_key = api_key
            config.providers.moonshot.api_base = api_base
        case _:
            raise Exception("Not support provider")

    console.print(f"[green]✓[/green] Created provider done, provider: {provider}, api_key: {api_key}, api_base: {api_base}")


def _question_agent_default(config: Config):
    """
    Config for agent default.
    """

    console.print("(2) Config the agent default.")

    model = questionary.text("Input your model:").ask()
    maxTokens = questionary.text("Input your maxTokens (default is 8192):", validate=lambda text: True if text.isdigit() else "Please input valid number" ).ask()
    temperature = questionary.text("Input the temperature (0.1 - 1.0):").ask()
    
    config.agents.defaults.model = model
    config.agents.defaults.max_tokens = int(maxTokens)
    config.agents.defaults.temperature = float(maxTokens)
    console.print(f"[green]✓[/green] Created agent default done, model: {model}, maxTokens: {maxTokens}, temperature: {temperature}")

