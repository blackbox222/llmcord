"""Shared state and global context for the bot."""

from dataclasses import dataclass, field
from typing import Any

from discord.ext import commands
import fs.base
import httpx

from . import agent, configs

@dataclass
class BotContext:
    """Shared context for the bot, passed to various components."""

    bot: commands.Bot
    config: configs.Config
    httpx_client: httpx.AsyncClient
    model_name: str = ""
    tools_config: list[Any] = field(default_factory=list)
    top_level_agent: agent.Agent | None = None
    vfs: fs.base.FS | None = None
