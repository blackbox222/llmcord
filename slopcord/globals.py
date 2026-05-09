"""Shared state and global context for the bot."""

from dataclasses import dataclass

from discord.ext import commands
import httpx

from . import configs

@dataclass
class BotContext:
    """Shared context for the bot, passed to various components."""

    bot: commands.Bot
    config: configs.Config
    httpx_client: httpx.AsyncClient
    model_name: str = ""
