"""Utility functions."""

import re

def split_message(content: str, max_len: int = 2000) -> list[str]:
    """
    Split content into chunks within max_len.

    Args:
        content: The text content to split.
        max_len: Maxinum length per chunk.

    Returns:
        List of message chunks.
    """

    if not content:
        return []
    if len(content) < max_len:
        return [content]

    chunks: list[str] = []
    while content:
        if len(content) <= max_len:
            chunks.append(content)
            break
        cut = content[:max_len]
        pos = cut.rfind('\n')
        if pos <= 0:
            pos = cut.rfind(' ')
        if pos <= 0:
            pos = max_len
        chunks.append(content[:pos])
        content = content[pos:].lstrip()

    return chunks

def strip_think(text: str) -> str:
    """Remoive <think></think> blocks."""
    text = re.sub(r"<think>[\s\S]*?</think>", "", text)
    text = re.sub(r"<think>[\s\S]*$", "", text)
    return text.strip()
