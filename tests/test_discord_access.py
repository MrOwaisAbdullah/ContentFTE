"""Plan SEC-07 / SEC-18: the Discord bot's authorization policy."""
from __future__ import annotations

from discord_bot import access

OWNER, MEMBER, STRANGER = 111, 222, 333


def test_parse_ids_ignores_junk_and_accepts_both_separators():
    assert access.parse_ids("111, 222 ,abc,,") == frozenset({111, 222})
    assert access.parse_ids("111;222") == frozenset({111, 222})
    assert access.parse_ids("") == access.parse_ids(None) == frozenset()
    assert access.parse_ids("-5, 1.5, 0x10") == frozenset()          # nothing that isn't a plain integer


def test_without_an_allow_list_only_the_application_owner_may_act():
    owners = {OWNER}
    assert access.is_authorized(OWNER, frozenset(), owners) is True
    assert access.is_authorized(STRANGER, frozenset(), owners) is False
    assert access.is_authorized(MEMBER, frozenset(), owners) is False


def test_team_owners_are_all_authorized():
    assert access.is_authorized(MEMBER, frozenset(), {OWNER, MEMBER}) is True


def test_an_explicit_allow_list_is_exclusive():
    allowed = frozenset({MEMBER})
    assert access.is_authorized(MEMBER, allowed, {OWNER}) is True
    # setting the list replaces the owner default: the owner must list themself
    assert access.is_authorized(OWNER, allowed, {OWNER}) is False
    assert access.is_authorized(STRANGER, allowed, {OWNER}) is False


def test_empty_owner_set_fails_closed():
    assert access.is_authorized(OWNER, frozenset(), set()) is False


def test_only_pipeline_messages_count_as_drafts():
    assert access.is_pipeline_message(True, None) is True            # posted by the bot
    assert access.is_pipeline_message(False, 987654321) is True      # posted through a webhook
    assert access.is_pipeline_message(False, None) is False          # a person typed it
