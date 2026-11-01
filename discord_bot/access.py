"""Who may drive the Discord bot (plan SEC-07 / SEC-18).

The bot's reaction handler, slash commands and free-text agent used to trust the CHANNEL and nothing
else: anyone who could see the approval channel could approve or reject posts by reacting, `/run post`
dispatched the GitHub workflow with the owner's PAT, `/edit` rewrote live posts, and every non-bot
message in any channel or DM reached an agent that holds approval, publish and edit tools.

Policy (kept here, free of any discord import, so it can be unit-tested):
  * `ALLOWED_DISCORD_USER_IDS` (comma-separated user ids) names who may act. If it is unset, ONLY the
    Discord application's owner (or its team members) may — secure by default, no configuration needed
    for a solo operator.
  * A reaction only counts on a message the bot or a webhook posted. A human can post
    `**Title:** X` and react, which previously approved row "X".
"""
from __future__ import annotations

from typing import Iterable, Optional


def parse_ids(raw: Optional[str]) -> frozenset[int]:
    """'123, 456 ,abc,' -> frozenset({123, 456}); junk entries are ignored, never trusted."""
    return frozenset(int(p) for p in (raw or "").replace(";", ",").split(",") if p.strip().isdigit())


def is_authorized(user_id: int, allowed_ids: frozenset[int], owner_ids: Iterable[int]) -> bool:
    """With an explicit allow-list, only those users; otherwise only the application owner(s)."""
    if allowed_ids:
        return user_id in allowed_ids
    return user_id in frozenset(owner_ids)


def is_pipeline_message(author_is_bot: bool, webhook_id: Optional[int]) -> bool:
    """True for a message posted by a bot or through a webhook (the pipeline's drafts and candidates),
    False for anything a human typed."""
    return bool(author_is_bot or webhook_id)
