# -*- coding: utf-8 -*-
"""
test_priority
~~~~~~~~~~~~~

Tests for the Priority trees
"""
from __future__ import division

import collections
import itertools

import pytest

from hypothesis import given
from hypothesis.strategies import (
    integers, lists, tuples, sampled_from
)

import priority


STREAMS_AND_WEIGHTS = lists(
    elements=tuples(
        integers(min_value=1), integers(min_value=1, max_value=255)
    ),
    unique_by=lambda x: x[0],
)

BLOCKED_AND_ACTIVE = lists(
    elements=sampled_from([1, 3, 5, 7, 9, 11]),
    unique=True,
).map(
    lambda blocked: (blocked, active_readme_streams_from_filter(blocked))
)

UNBLOCKED_AND_ACTIVE = lists(
    elements=sampled_from([1, 3, 5, 7, 9, 11]),
    unique=True,
).map(
    lambda unblocked: (unblocked, active_readme_streams_from_filter(
        unblocked, blocked=False
    ))
)


def readme_tree():
    """
    Provide a tree configured as the one in the readme.
    """
    p = priority.PriorityTree()
    p.insert_stream(stream_id=1)
    p.insert_stream(stream_id=3)
    p.insert_stream(stream_id=5, depends_on=1)
    p.insert_stream(stream_id=7, weight=32)
    p.insert_stream(stream_id=9, depends_on=7, weight=8)
    p.insert_stream(stream_id=11, depends_on=7, exclusive=True)
    return p


def active_readme_streams_from_filter(filtered, blocked=True):
    """
    Given a collection of filtered streams, determine which ones are active.
    This applies only to the readme tree at this time, though in future it
    should be possible to apply this to an arbitrary tree.

    If ``blocked`` is ``True``, the filter is a set of blocked streams. If
    ``False``, it's a collection of unblocked streams.
    """
    tree = {
        1: {
            5: {},
        },
        3: {},
        7: {
            11: {
                9: {},
            },
        },
    }
    filtered = set(filtered)

    def get_expected(tree):
        expected = []

        for stream_id in tree:
            if stream_id not in filtered and blocked:
                expected.append(stream_id)
            elif stream_id in filtered and not blocked:
                expected.append(stream_id)
            else:
                expected.extend(get_expected(tree[stream_id]))

        return expected

    return get_expected(tree)


def active_streams_from_unblocked(unblocked):
    """
    Given a collection of unblocked streams, determine which ones are active.
    This applies only to the readme tree at this time, though in future it
    should be possible to apply this to an arbitrary tree.
    """


class TestStream(object):
    def test_stream_repr(self):
        """
        The stream representation renders according to the README.
        """
        s = priority.Stream(stream_id=80, weight=16)
        assert repr(s) == "Stream<id=80, weight=16>"

    @given(STREAMS_AND_WEIGHTS)
    def test_streams_are_well_ordered(self, streams_and_weights):
        """
        Streams are ordered by their stream ID.
        """
        stream_list = [
            priority.Stream(stream_id=s, weight=w)
            for s, w in streams_and_weights
        ]
        stream_list = sorted(stream_list)
        streams_by_id = [stream.stream_id for stream in stream_list]
        assert sorted(streams_by_id) == streams_by_id

    @given(
        integers(min_value=1, max_value=2**24),
        integers(min_value=1, max_value=2**24)
    )
    def test_stream_ordering(self, a, b):
        """
        Two streams are well ordered based on their stream ID.
        """
        s1 = priority.Stream(stream_id=a, weight=16)
        s2 = priority.Stream(stream_id=b, weight=32)

        assert (s1 < s2) == (a < b)
        assert (s1 <= s2) == (a <= b)
        assert (s1 > s2) == (a > b)
        assert (s1 >= s2) == (a >= b)
        assert (s1 == s2) == (a == b)
        assert (s1 != s2) == (a != b)


class TestPriorityTreeManual(object):
    """
    These tests manually confirm that the PriorityTree output is correct. They
    use the PriorityTree given in the README and confirm that it outputs data
    as expected.

    If possible, I'd like to eventally replace these tests with
    Hypothesis-based ones for the same data, but getting Hypothesis to generate
    useful data in this case is going to be quite tricky.
    """
    @given(BLOCKED_AND_ACTIVE)
    def test_priority_tree_initially_outputs_all_stream_ids(self,
                                                            blocked_expected):
        """
        The first iterations of the priority tree initially output the active
        streams, in order of stream ID, regardless of weight.
        """
        tree = readme_tree()
        blocked = blocked_expected[0]
        expected = blocked_expected[1]

        for stream_id in blocked:
            tree.block(stream_id)

        result = [next(tree) for _ in range(len(expected))]
        assert expected == result

    @given(UNBLOCKED_AND_ACTIVE)
    def test_priority_tree_blocking_is_isomorphic(self,
                                                  allowed_expected):
        """
        Blocking everything and then unblocking certain ones has the same
        effect as blocking specific streams.
        """
        tree = readme_tree()
        allowed = allowed_expected[0]
        expected = allowed_expected[1]

        for stream_id in range(1, 12, 2):
            tree.block(stream_id)

        for stream_id in allowed:
            tree.unblock(stream_id)

        result = [next(tree) for _ in range(len(expected))]
        assert expected == result

    @given(BLOCKED_AND_ACTIVE)
    def test_removing_items_behaves_similarly_to_blocking(self,
                                                          blocked_expected):
        """
        From the perspective of iterating over items, removing streams should
        have the same effect as blocking them, except that the ordering
        changes. Because the ordering is not important, don't test for it.
        """
        tree = readme_tree()
        blocked = blocked_expected[0]
        expected = set(blocked_expected[1])

        for stream_id in blocked:
            tree.remove_stream(stream_id)

        result = set(next(tree) for _ in range(len(expected)))
        assert expected == result

    def test_priority_tree_raises_deadlock_error_if_all_blocked(self):
        """
        Assuming all streams are blocked and none can progress, asking for the
        one with the next highest priority fires a DeadlockError.
        """
        tree = readme_tree()
        for stream_id in range(1, 12, 2):
            tree.block(stream_id)

        with pytest.raises(priority.DeadlockError):
            next(tree)


class TestPriorityTreeOutput(object):
    """
    These tests use Hypothesis to attempt to bound the output of iterating over
    the priority tree. In particular, their goal is to ensure that the output
    of the tree is "good enough": that it meets certain requirements on
    fairness and equidistribution.
    """
    @given(STREAMS_AND_WEIGHTS)
    def test_period_of_repetition(self, streams_and_weights):
        """
        The period of repetition of a priority sequence is given by the sum of
        the weights of the streams. Once that many values have been pulled out
        the sequence repeats identically.
        """
        p = priority.PriorityTree()
        weights = []

        for stream, weight in streams_and_weights:
            p.insert_stream(stream_id=stream, weight=weight)
            weights.append(weight)

        period = sum(weights)

        # Pop off the first n elements, which will always be evenly
        # distributed.
        for _ in weights:
            next(p)

        pattern = [next(p) for _ in range(period)]
        pattern = itertools.cycle(pattern)

        for i in range(period * 20):
            assert next(p) == next(pattern), i

    @given(STREAMS_AND_WEIGHTS)
    def test_priority_tree_distribution(self, streams_and_weights):
        """
        Once a full period of repetition has been observed, each stream has
        been emitted a number of times equal to its weight.
        """
        p = priority.PriorityTree()
        weights = []

        for stream, weight in streams_and_weights:
            p.insert_stream(stream_id=stream, weight=weight)
            weights.append(weight)

        period = sum(weights)

        # Pop off the first n elements, which will always be evenly
        # distributed.
        for _ in weights:
            next(p)

        count = collections.Counter(next(p) for _ in range(period))

        assert len(count) == len(streams_and_weights)
        for stream, weight in streams_and_weights:
            count[stream] == weight
