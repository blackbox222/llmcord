"""Message conversation chain building.

Walks parent messages (replies, threads), fetches attachments, and builds
the messages list to pass to the LLM.
"""

import asyncio
from collections import defaultdict
import logging
from base64 import b64encode
from dataclasses import dataclass, field
from typing import Any, Literal, Optional

import discord

from . import constants, globals

log = logging.getLogger(__name__)


@dataclass
class MsgNode:
    """Node in a message chain."""

    role: Literal["user", "assistant"] = "assistant"
    text: Optional[str] = None
    images: list[dict[str, Any]] = field(default_factory=list)
    has_bad_attachments: bool = False
    fetch_parent_failed: bool = False
    parent_msg: Optional[discord.Message] = None
    lock: asyncio.Lock = field(default_factory=asyncio.Lock)

    async def populate(
            self,
            ctx: globals.BotContext,
            msg: discord.Message,
            force: bool = False) -> None:
        """Populate an MsgNode from a Discord message and its attachments."""
        assert self.lock.locked()

        if force or self.text is None:
            cleaned_content = (
                msg.content.removeprefix(ctx.bot.user.mention)
                    .replace(constants.EMPTY_THOUGHT, "")
                    .lstrip())

            good_attachments = [
                att for att in msg.attachments
                if att.content_type and any(
                    att.content_type.startswith(x) for x in ("text", "image"))]

            attachment_responses = await asyncio.gather(*[
                ctx.httpx_client.get(att.url) for att in good_attachments])

            self.role = "assistant" if msg.author == ctx.bot.user else "user"

            self.text = "\n".join(
                ([cleaned_content] if cleaned_content else [])
                + ["\n".join(filter(None, (embed.title, embed.description)))
                for embed in msg.embeds]
                + [component.content for component in msg.components
                if component.type == discord.ComponentType.text_display]
                + [resp.text for att, resp in zip(good_attachments, attachment_responses)
                if att.content_type and att.content_type.startswith("text")]
            )

            self.images = [
                dict(type="image_url",
                     image_url=dict(url=f"data:{att.content_type};base64,{b64encode(resp.content).decode('utf-8')}"))
                for att, resp in zip(good_attachments, attachment_responses)
                if att.content_type and att.content_type.startswith("image")
            ]

            if self.role == "user" and (self.text or self.images):
                self.text = f"<@{msg.author.id}>: {self.text}"

            self.has_bad_attachments = len(msg.attachments) > len(good_attachments)


# Cache of message ID to MsgNode for quick lookup and to avoid refetching messages
msg_nodes: dict[int, MsgNode] = defaultdict(MsgNode)


async def prune_cache():
    """Remove the oldest nodes in the cache if there are more than the maximum."""
    if len(msg_nodes) > constants.MAX_MESSAGE_NODES:
        to_remove = sorted(msg_nodes.keys())[: len(msg_nodes) - constants.MAX_MESSAGE_NODES]
        for msg_id in to_remove:
            async with msg_nodes.setdefault(msg_id, MsgNode()).lock:
                msg_nodes.pop(msg_id, None)


class MessageChain:
    """Helper for building message chains with caching and locking."""

    def __init__(self, ctx: globals.BotContext, msg: discord.Message) -> None:
        self.ctx = ctx
        self.root_msg = msg
        self.messages: list[dict[str, Any]] = []
        self.user_warnings: set[str] = set()

    async def build(self):
        """Build the message chain for a message."""
        max_messages = self.ctx.config.data.get("max_messages", 50)
        max_text = self.ctx.config.data.get("max_text", 100000)
        max_images = self.ctx.config.data.get("max_images", 5)

        curr_msg: Optional[discord.Message] = self.root_msg

        while curr_msg is not None and len(self.messages) < max_messages:
            curr_node = msg_nodes[curr_msg.id]

            async with curr_node.lock:
                if curr_node.text is None:
                    await curr_node.populate(self.ctx, curr_msg)
                assert curr_node.text is not None  # populate() failed if text is None

                # Build content for LLM
                content: str | list[dict[str, Any]] = (
                    [dict(type="text", text=curr_node.text[:max_text])]
                    + curr_node.images[:max_images]
                    if curr_node.images[:max_images]
                    else curr_node.text[:max_text]
                )

                if content != "":
                    self.messages.append(dict(content=content, role=curr_node.role))

                # Fetch parent if this is a reply or in a public thread
                is_chained = (curr_msg.type == discord.MessageType.reply
                    or curr_msg.channel.type == discord.ChannelType.public_thread)

                if (is_chained
                    and curr_node.parent_msg is None
                    and not curr_node.fetch_parent_failed):
                    try:
                        curr_node.parent_msg = await self.get_parent(curr_msg)
                    except (discord.NotFound, discord.HTTPException):
                        log.exception("Error fetching next message in the chain")
                        curr_node.fetch_parent_failed = True

                # Warnings
                if len(curr_node.text or "") > max_text:
                    self.user_warnings.add(f"⚠️ Max {max_text:,} characters per message")
                if len(curr_node.images) > max_images:
                    self.user_warnings.add(
                        f"⚠️ Max {max_images} image{'s' if max_images != 1 else ''} per message"
                        if max_images > 0
                        else "⚠️ Can't see images"
                    )
                if curr_node.has_bad_attachments:
                    self.user_warnings.add("⚠️ Unsupported attachments")
                if curr_node.fetch_parent_failed or (
                    curr_node.parent_msg is not None and len(self.messages) == max_messages):
                    self.user_warnings.add(
                        f"⚠️ Only using last {len(self.messages)} message{'s' if len(self.messages) != 1 else ''}")

                # Walk to parent
                if curr_node.parent_msg is not None and is_chained:
                    curr_msg = curr_node.parent_msg
                else:
                    break

    async def get_parent(self, msg: discord.Message) -> discord.Message | None:
        """Find a suitable parent from the message."""

        is_public_thread = msg.channel.type == discord.ChannelType.public_thread

        if (msg.reference is None
            and self.ctx.bot.user.mention not in msg.content
            and (prev_msg_in_channel := ([
                m async for m in msg.channel.history(before=msg, limit=1)]
                or [None])[0])
            and prev_msg_in_channel.type in (
                discord.MessageType.default, discord.MessageType.reply)
            and prev_msg_in_channel.author == (
                self.ctx.bot.user
                if msg.channel.type == discord.ChannelType.private
                else msg.author)):
            return prev_msg_in_channel
        else:
            parent_is_thread_start = (
                is_public_thread
                and msg.reference is None
                and msg.channel.parent.type == discord.ChannelType.text)

            if (parent_msg_id := msg.channel.id
                if parent_is_thread_start
                else getattr(msg.reference, "message_id", None)):

                if parent_is_thread_start:
                    return (
                        msg.channel.starter_message
                        or await msg.channel.parent.fetch_message(parent_msg_id))
                else:
                    return (
                        msg.reference.cached_message
                        or await msg.channel.fetch_message(parent_msg_id))

        return None
