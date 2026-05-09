"""Permission checking for the bot.

Evaluates user/role/channel allowlists, blocklists, and DM policy.
"""

import discord


def is_allowed(
    msg: discord.Message,
    bot_user: discord.ClientUser,
    permissions: dict[str, dict[str, int]],
    allow_dms: bool,
) -> bool:
    """Check if a message is allowed based on user/role/channel permissions.

    Returns True if the message should be processed, False otherwise.
    """
    is_dm = msg.channel.type == discord.ChannelType.private
    is_mentioned = bot_user in msg.mentions or (
        msg.guild and msg.guild.self_role in msg.role_mentions
    )

    if (not is_dm and not is_mentioned) or msg.author.bot:
        return False

    role_ids = set(role.id for role in getattr(msg.author, "roles", ()))
    channel_ids = set(
        filter(
            None,
            (
                msg.channel.id,
                getattr(msg.channel, "parent_id", None),
                getattr(msg.channel, "category_id", None),
            ),
        )
    )

    ((allowed_user_ids, blocked_user_ids),
     (allowed_role_ids, blocked_role_ids),
     (allowed_channel_ids, blocked_channel_ids)) = (
        (perm.get("allowed_ids", []), perm.get("blocked_ids", []))
        for perm in (
            permissions.get("users", {}),
            permissions.get("roles", {}),
            permissions.get("channels", {}),
        )
    )

    user_is_admin = msg.author.id in permissions.get("users", {}).get("admin_ids", [])

    allow_all_users = (
        not allowed_user_ids if is_dm else not allowed_user_ids and not allowed_role_ids)
    is_good_user = (
        user_is_admin
        or allow_all_users
        or msg.author.id in allowed_user_ids
        or any(rid in allowed_role_ids for rid in role_ids)
    )
    is_bad_user = (
        not is_good_user
        or msg.author.id in blocked_user_ids
        or any(rid in blocked_role_ids for rid in role_ids)
    )

    allow_all_channels = not allowed_channel_ids
    is_good_channel = (
        user_is_admin
        or allow_dms if is_dm else allow_all_channels
        or any(rid in allowed_channel_ids for rid in channel_ids)
    )
    is_bad_channel = not is_good_channel or any(rid in blocked_channel_ids
                                                for rid in channel_ids)

    return not is_bad_user and not is_bad_channel
