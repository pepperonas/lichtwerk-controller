"""Iris across two chains — the mirrored painting path.

Covers the seam between `StripGroup` and the wash: that every chain gets a full
frame of its own length, that they breathe in step, and that the highlights are
drawn independently. The colour maths is test_iris_wash.py's job; this is about
what each chain actually receives.
"""
from __future__ import annotations

import os
import pathlib
import sys

import pytest

_ROOT = pathlib.Path(__file__).parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))
os.chdir(_ROOT)

pytest.importorskip("flask", reason="lichtwerk runtime deps not installed")
pytest.importorskip("flask_cors", reason="lichtwerk runtime deps not installed")

import iris_wash                      # noqa: E402
import web_controller as wc           # noqa: E402
from pio_strip import PixelStrip, StripGroup  # noqa: E402

N = 120  # short chains keep the frame build fast; the maths is length-agnostic


class FakeChain(PixelStrip):
    def __init__(self, num, idx):
        super().__init__(num, device=f"/dev/nulltest{idx}")
        self.writes = []
        self._begun = True

    def _write(self, payload: bytes) -> bool:
        self.writes.append(bytes(payload))
        return True


@pytest.fixture
def rig():
    """Controller wired to two fake chains, iris armed, state restored after."""
    c = wc.controller
    saved = (c.strip, c.power, c.strip_warn_over, c.current_effect,
             c._wash_cache, c._wash_key, c._wash_t0, c._wash_sparks,
             c._wash_mode, c._wash_spark_ts, c._wash_max_current_a)
    chains = [FakeChain(N, 0), FakeChain(N, 1)]
    c.strip = StripGroup(chains)
    c._wash_cache, c._wash_key, c._wash_t0 = (), None, None
    c._wash_sparks, c._wash_spark_ts = [], None
    c._wash_mode = 'mirror'
    c._wash_max_current_a = None
    c.power = True
    c.strip_warn_over = True
    c.current_effect = 'iris_warn'
    yield c, chains
    (c.strip, c.power, c.strip_warn_over, c.current_effect,
     c._wash_cache, c._wash_key, c._wash_t0, c._wash_sparks,
     c._wash_mode, c._wash_spark_ts, c._wash_max_current_a) = saved


def _white_positions(payload):
    """LED indices the overlays lifted well above the red wash."""
    out = set()
    for i in range(len(payload) // 4):
        g = payload[i * 4 + 1]
        if g > 60:            # the wash keeps green near zero; overlays raise it
            out.add(i)
    return out


def test_mirror_builds_one_segment_per_chain(rig):
    c, _ = rig
    segs = c._wash_segments()
    assert segs == (N, N)
    frames = c._wash_frames()
    assert len(frames) == 2
    assert all(len(f[0]) == N * 4 for f in frames)


def test_each_chain_receives_a_full_frame(rig):
    c, chains = rig
    c.effect_iris_warn()
    assert len(chains[0].writes) == 1 and len(chains[1].writes) == 1
    for ch in chains:
        assert len(ch.writes[0]) == N * 4, "chain got a slice, not its own frame"


def test_extend_mode_splits_instead_of_mirroring(rig):
    c, chains = rig
    c._wash_mode = 'extend'
    c._wash_cache, c._wash_key, c._wash_t0 = (), None, None
    assert c._wash_segments() == (2 * N,)
    c.effect_iris_warn()
    # One picture spread across both: each chain gets half of a 240 LED frame.
    for ch in chains:
        assert len(ch.writes[0]) == N * 4


def test_chains_breathe_in_step(rig):
    """Shared rhythm is the point — only the specks are private."""
    c, chains = rig
    c._wash_sparks_on = False
    c._wash_shimmer_on = False
    try:
        c.effect_iris_warn()
        assert chains[0].writes[0] == chains[1].writes[0]
    finally:
        c._wash_sparks_on = True
        c._wash_shimmer_on = True


def test_highlights_are_drawn_per_chain(rig):
    """Identical spark positions on both runs would read as a machine."""
    c, chains = rig
    for _ in range(60):
        c.effect_iris_warn()
    a = set().union(*(_white_positions(p) for p in chains[0].writes))
    b = set().union(*(_white_positions(p) for p in chains[1].writes))
    assert a and b, "no highlights painted at all"
    assert a != b, "both chains lit the same LEDs — overlays are not independent"


def test_sparks_stay_inside_their_chain(rig):
    """The bug this guards: spawning across the group total would index past
    the end of a mirrored frame and silently drop half the highlights."""
    c, chains = rig
    for _ in range(40):
        c.effect_iris_warn()
    for ch in chains:
        for payload in ch.writes:
            assert max(_white_positions(payload), default=0) < N


def test_spark_state_is_sized_per_segment(rig):
    c, _ = rig
    c.effect_iris_warn()
    assert len(c._wash_sparks) == 2


def test_rearming_with_a_warm_cache_keeps_spark_state_valid(rig):
    """_wash_engage used to clear the list without resizing it; with the cache
    already warm nothing rebuilt it and the next frame indexed out of range."""
    c, chains = rig
    c.effect_iris_warn()
    c._wash_t0 = None            # release, then re-arm on a warm cache
    c._wash_engage()
    assert len(c._wash_sparks) == 2
    c.effect_iris_warn()         # must not raise
    assert len(chains[0].writes) >= 2
