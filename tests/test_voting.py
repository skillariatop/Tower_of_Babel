"""Smoke tests for voting logic (no Discord connection needed)."""

from datetime import datetime, timezone, timedelta

import pytest

from bot.cogs.voting import ActiveVote, VoteLevel, LEVEL_THRESHOLD


def make_vote(**kwargs) -> ActiveVote:
    defaults = dict(
        id=1,
        title="Test vote",
        level=VoteLevel.ROUTINE,
        started_by=123,
        ends_at=datetime.now(timezone.utc) + timedelta(hours=24),
        message_id=999,
    )
    defaults.update(kwargs)
    return ActiveVote(**defaults)


def test_result_accepted_simple_majority():
    v = make_vote()
    v.votes_for = {1, 2, 3}
    v.votes_against = {4}
    assert v.result is True


def test_result_rejected_below_threshold():
    v = make_vote(level=VoteLevel.SIGNIFICANT)
    v.votes_for = {1}
    v.votes_against = {2, 3}
    assert v.result is False


def test_result_none_when_no_votes():
    v = make_vote()
    assert v.result is None


def test_significant_threshold_exactly_two_thirds():
    v = make_vote(level=VoteLevel.SIGNIFICANT)
    # exactly 2/3 is NOT strictly > threshold
    v.votes_for = {1, 2}
    v.votes_against = {3}
    assert v.result is False  # 2/3 == threshold, need > threshold


def test_total_counts_all_buckets():
    v = make_vote()
    v.votes_for = {1}
    v.votes_against = {2}
    v.votes_abstain = {3}
    assert v.total == 3
