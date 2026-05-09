"""Prompt and response formatting for Discord and the LLM API.

Handles embeds, TextDisplay, message splitting, and reply logic.
"""

from datetime import datetime
import logging
from typing import Any

import discord

from . import constants

log = logging.getLogger(__name__)


def format_embed(
        text: str,
        finish_reason: str | None = None,
        usage: tuple[int, int] | None = None,
        elapsed_sec: float | None = None) -> discord.Embed:
    """Format an LLM response into a Discord embed."""
    embed = discord.Embed(
        description=(
            text.replace(constants.EMPTY_THOUGHT, "")
            + (constants.STREAMING_INDICATOR if not finish_reason else "")),
        color=(
            constants.EMBED_COLOR_COMPLETE
            if (finish_reason
                and finish_reason.lower() in constants.GOOD_FINISHES)
            else constants.EMBED_COLOR_INCOMPLETE
        ),
    )

    footer_parts = []
    if finish_reason and finish_reason not in constants.GOOD_FINISHES:
        footer_parts.append(f"unknown finish reason \"{finish_reason}\"")
    if usage:
        input_tokens, output_tokens = usage
        footer_parts.append(f"{input_tokens} input / {output_tokens} output tokens")
    if elapsed_sec:
        footer_parts.append(f"took {elapsed_sec:.2f}s")
    if footer_parts:
        embed.set_footer(text=", ".join(footer_parts))

    return embed


def format_system_prompt(system_prompt: str, bot_user: discord.User, human_model_name: str, temperature: float, top_p: float) -> dict[str, Any]:
    """Format a system prompt by replacing placeholders."""
    now = datetime.now().astimezone()
    replacements = {
        "{date}": now.strftime("%B %d %Y"),
        "{time}": now.strftime("%H:%M:%S %Z%z"),
        "{name}": bot_user.name,
        "{model_name}": human_model_name,
        "{model_temperature}": str(temperature),
        "{model_top_p}": str(top_p),
    }
    for key, value in replacements.items():
        system_prompt = system_prompt.replace(key, value)
    system_prompt = system_prompt.strip()
    return dict(role="system", content=system_prompt)