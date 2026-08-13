import pytest

from tuckit.core.services import ratelimit


@pytest.fixture(autouse=True)
def clean_buckets():
    """The bucket dict is module-level and outlives a single test."""
    ratelimit.reset()
    yield
    ratelimit.reset()


def test_the_whole_burst_is_spendable_immediately():
    for _ in range(3):
        assert ratelimit.allow("k", burst=3, per_sec=1.0, now=0.0)


def test_it_blocks_once_the_burst_is_drained():
    for _ in range(3):
        ratelimit.allow("k", burst=3, per_sec=1.0, now=0.0)
    assert not ratelimit.allow("k", burst=3, per_sec=1.0, now=0.0)


def test_it_refills_at_the_configured_rate():
    for _ in range(3):
        ratelimit.allow("k", burst=3, per_sec=1.0, now=0.0)
    assert not ratelimit.allow("k", burst=3, per_sec=1.0, now=0.5)  # half a token
    assert ratelimit.allow("k", burst=3, per_sec=1.0, now=1.0)      # one whole token


def test_refill_never_exceeds_the_burst():
    ratelimit.allow("k", burst=3, per_sec=1.0, now=0.0)
    # 1000 idle seconds credit 1000 tokens; the cap is 3.
    for _ in range(3):
        assert ratelimit.allow("k", burst=3, per_sec=1.0, now=1000.0)
    assert not ratelimit.allow("k", burst=3, per_sec=1.0, now=1000.0)


def test_different_keys_do_not_share_a_bucket():
    for _ in range(3):
        ratelimit.allow("a", burst=3, per_sec=1.0, now=0.0)
    assert not ratelimit.allow("a", burst=3, per_sec=1.0, now=0.0)
    assert ratelimit.allow("b", burst=3, per_sec=1.0, now=0.0)


def test_sustained_load_is_clamped_to_the_refill_rate():
    """The point of the whole design: a caller spending faster than the refill
    rate passes at roughly the refill rate once the burst is gone. 100 calls
    over 10 seconds against burst 10 / 1 per sec should pass ~20, not 100."""
    passed = sum(
        1 for tick in range(100)
        if ratelimit.allow("k", burst=10, per_sec=1.0, now=tick * 0.1)
    )
    assert 17 <= passed <= 22, passed


def test_a_bucket_idle_long_enough_to_be_full_is_dropped():
    ratelimit.allow("k", burst=10, per_sec=1.0, now=0.0)
    assert "k" in ratelimit._buckets
    ratelimit._sweep(now=10.0)  # 10 tokens at 1/sec: full again after 10s
    assert "k" not in ratelimit._buckets


def test_dropping_a_full_bucket_changes_nothing_observable():
    """Eviction is exact, not approximate: a missing key starts full, so a full
    bucket and an absent one are the same state."""
    for _ in range(10):
        ratelimit.allow("k", burst=10, per_sec=1.0, now=0.0)
    ratelimit._sweep(now=10.0)
    assert "k" not in ratelimit._buckets
    for _ in range(10):
        assert ratelimit.allow("k", burst=10, per_sec=1.0, now=10.0)


def test_a_hammered_bucket_is_never_swept():
    for tick in range(50):
        ratelimit.allow("k", burst=10, per_sec=1.0, now=tick * 0.1)
    ratelimit._sweep(now=5.0)
    assert "k" in ratelimit._buckets


def test_two_layers_with_different_horizons_are_swept_independently():
    """Each entry remembers its own refill horizon, so sweeping a short-horizon
    bucket must not take a long-horizon one with it."""
    ratelimit.allow("fast", burst=2, per_sec=1.0, now=0.0)   # full after 2s
    ratelimit.allow("slow", burst=100, per_sec=1.0, now=0.0)  # full after 100s
    ratelimit._sweep(now=5.0)
    assert "fast" not in ratelimit._buckets
    assert "slow" in ratelimit._buckets
