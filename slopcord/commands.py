"""Slash commands for the slopcord bot.

Registers /model, /set, and /system-prompt commands with autocompletes.
"""

import glob
import logging

import discord
from discord.app_commands import Choice

from . import globals

log = logging.getLogger(__name__)


def register_commands(
    ctx: globals.BotContext,
    curr_model_holder: list[str],  # mutable container for current model
) -> None:
    """Register all slash commands with the bot."""

    @ctx.bot.tree.command(name="model", description="View or switch the current model")
    async def model_command(interaction: discord.Interaction, model: str) -> None:
        if model == curr_model_holder[0]:
            output = f"Current model: `{curr_model_holder[0]}`"
        else:
            if interaction.user.id in ctx.config.data.get("permissions", {}).get("users", {}).get("admin_ids", []):
                curr_model_holder[0] = model
                output = f"Model switched to: `{model}`"
                log.info(output)
            else:
                output = "You don't have permission to change the model."

        await interaction.response.send_message(
            output, ephemeral=interaction.channel.type == discord.ChannelType.private
        )

    @model_command.autocomplete("model")
    async def model_autocomplete(interaction: discord.Interaction, curr_str: str) -> list[Choice[str]]:
        if curr_str == "":
            ctx.config.reload()

        choices: list[Choice[str]] = []
        current = curr_model_holder[0]
        models = ctx.config.data.get("models", {})

        if curr_str.lower() in current.lower():
            choices.append(Choice(name=f"◉ {current} (current)", value=current))

        for model in models:
            if model != current and curr_str.lower() in model.lower():
                choices.append(Choice(name=f"○ {model}", value=model))

        return choices[:25]

    @ctx.bot.tree.command(name="set", description="Change settings for the model")
    async def set_command(
        interaction: discord.Interaction, name: str, value: str
    ) -> None:
        admin_ids = ctx.config.data.get("permissions", {}).get("users", {}).get("admin_ids", [])
        if interaction.user.id in admin_ids:
            if name in ctx.config.model_settings:
                ctx.config.model_settings[name] = float(value)
                output = f"Model setting `{name}` updated to: `{value}`"
                log.info(output)
            else:
                valid = ", ".join(ctx.config.model_settings.keys())
                output = f"Unknown model setting: `{name}`. Valid settings are: `{valid}`"
        else:
            output = "You don't have permission to set model settings."

        await interaction.response.send_message(
            output, ephemeral=interaction.channel.type == discord.ChannelType.private
        )

    @set_command.autocomplete("name")
    async def set_name_autocomplete(
        interaction: discord.Interaction, curr_str: str
    ) -> list[Choice[str]]:
        return [
            Choice(name=f"{setting} (currently {value})", value=setting)
            for setting, value in ctx.config.model_settings.items()
            if curr_str.lower() in setting.lower()
        ]

    @ctx.bot.tree.command(name="system-prompt", description="Switch the current system prompt")
    async def system_prompt_command(interaction: discord.Interaction, name: str) -> None:
        admin_ids = ctx.config.data.get("permissions", {}).get("users", {}).get("admin_ids", [])
        if interaction.user.id not in admin_ids:
            output = "You don't have permission to change the system prompt."
        else:
            clean_name = name.replace("/", "").replace(".", "").lower().strip()
            prompt_path = f"prompts/{clean_name}.md"
            if not glob.glob(prompt_path):
                output = f"Prompt file not found: `{prompt_path}`"
            else:
                ctx.config.system_prompt_name = clean_name
                output = f"System prompt changed to: `{clean_name}`"

        log.info(output)
        await interaction.response.send_message(
            output, ephemeral=interaction.channel.type == discord.ChannelType.private
        )

    @system_prompt_command.autocomplete("name")
    async def system_prompt_name_autocomplete(
        interaction: discord.Interaction, curr_str: str
    ) -> list[Choice[str]]:
        prompt_files = ctx.config.get_prompt_files()
        choices: list[Choice[str]] = []
        current = ctx.config.system_prompt_name
        for base in prompt_files:
            if curr_str.lower() in base.lower():
                marker = "◉" if base == current else "○"
                choices.append(Choice(name=f"{marker} {base}", value=base))
        return choices[:25]
