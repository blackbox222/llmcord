"""Event handlers for the slopcord bot.

Orchestrates on_ready and on_message, delegating to other modules.
"""

import asyncio
import io
import logging
import time

import discord
import openai

from . import constants, formatters, globals, llm, messages, permissions

log = logging.getLogger(__name__)


async def on_ready(ctx: globals.BotContext) -> None:
    """Handle bot ready event."""
    ctx.config.reload()

    if client_id := ctx.config.data.get("client_id", None):
        log.info(
            "READY: invite URL: https://discord.com/oauth2/authorize?client_id=%s&permissions=412317191168&scope=bot",
            client_id)

    await ctx.bot.tree.sync()


async def on_message(ctx: globals.BotContext, msg: discord.Message) -> None:
    """Handle incoming messages."""
    # Reload config for permissions
    ctx.config.reload()

    # Permission checks (includes mention/DM/author checks)
    perm_data = ctx.config.data.get("permissions", {})
    allow_dms = ctx.config.data.get("allow_dms", True)

    if not permissions.is_allowed(msg, ctx.bot.user, perm_data, allow_dms):
        return

    # Setup model and provider
    provider, model = ctx.model_name.removesuffix(":vision").split("/", 1)

    provider_config = ctx.config.data.get("providers", {}).get(provider, {})
    base_url = provider_config.get("base_url", "")
    api_key = provider_config.get("api_key", "sk-no-key-required")
    openai_client = openai.AsyncOpenAI(base_url=base_url, api_key=api_key)

    model_parameters = ctx.config.data.get("models", {}).get(ctx.model_name, {})

    # TODO
    extra_headers = provider_config.get("extra_headers")
    extra_query = provider_config.get("extra_query")
    accept_images = any(tag in ctx.model_name.lower()
                        for tag in constants.VISION_MODEL_TAGS)

    # Fetch message chain
    msg_chain = messages.MessageChain(ctx, msg)
    await msg_chain.build()
    log.info(
        "handling message (%d attachments, %d chained) <@%d>: %s",
        len(msg.attachments),
        len(msg_chain.messages),
        msg.author.id,
        msg.content)

    system_prompt = ctx.config.get_system_prompt(ctx.config.system_prompt_name)

    try:
        async with msg.channel.typing():
            text = io.StringIO()
            finish_reason: str | None = None
            usage: tuple[int, int] | None = None
            cur_reply: discord.Message | None = None
            start_time = time.time()
            last_update_time = 0.0

            async def _update(embed: discord.Embed) -> None:
                nonlocal cur_reply, last_update_time

                # Avoid updating messages too frequently
                cur_time = time.monotonic()
                if (last_update_time and
                    (wait_time := cur_time - last_update_time) < constants.RATE_LIMIT_SECONDS):
                    log.info("waiting %d ms to update", wait_time * 1000)
                    await asyncio.sleep(wait_time)

                # Reply or edit existing reply, avoid cancelling inflight HTTP requests
                if cur_reply:
                    cur_reply = await asyncio.shield(cur_reply.edit(embed=embed))
                else:
                    cur_reply = await asyncio.shield(msg.reply(embed=embed, silent=True))
                last_update_time = cur_time

            async for response in llm.generate(
                client=openai_client,
                model_name=model,
                model_params=model_parameters,
                system_prompt=system_prompt,
                messages=msg_chain.messages
            ):
                if response.finish_reason:
                    finish_reason = response.finish_reason
                if response.usage:
                    usage = response.usage

                # Accumulate content parts until we run out or hit the message length limit, then send an update
                while response.content:
                    part = response.content.popleft()

                    # If adding this part would exceed Discord's length limit, finish this and start a new one
                    if (text.tell() + len(part)) > constants.MAX_MESSAGE_LENGTH:
                        log.info("Splitting at message limit with response length %d", text.tell())
                        await _update(formatters.format_embed(text.getvalue(), finish_reason, usage))
                        text = io.StringIO()
                    text.write(part)

                cur_time = time.monotonic()
                if not last_update_time or (cur_time - last_update_time) > constants.RATE_LIMIT_SECONDS:
                    # Enqueue an update with the current (partial) response
                    log.info("Updating message with response length %d", text.tell())
                    await _update(formatters.format_embed(text.getvalue(), finish_reason, usage))

            # Trigger a final update to avoid missing any updates that were rate limited
            elapsed = time.time() - start_time
            log.info("LLM completion done in %.2f s, finishing update", elapsed)
            await _update(formatters.format_embed(text.getvalue(), finish_reason, usage, elapsed))

    except Exception:
        log.exception("Error while generating response")

    # Prune old msg_nodes
    await messages.prune_cache()
