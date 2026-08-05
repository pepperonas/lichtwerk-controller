"""StripGroup — several PIO chains presented as one logical strip.

The contract worth protecting: effects address one flat pixel space and the
split happens at write time. If that ever leaks, thirteen effects start needing
to know about chains, and the frame a chain receives is the thing to assert on.
"""
from __future__ import annotations

import pathlib
import sys

import pytest

_ROOT = pathlib.Path(__file__).parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from pio_strip import Color, PixelStrip, StripGroup  # noqa: E402


class FakeChain(PixelStrip):
    """A chain that records what was written instead of touching a device."""

    def __init__(self, num, **kw):
        super().__init__(num, **kw)
        self.writes = []
        self._begun = True

    def _write(self, payload: bytes) -> bool:
        self.writes.append(bytes(payload))
        return True


def group(*lengths):
    chains = [FakeChain(n, device=f"/dev/null{i}") for i, n in enumerate(lengths)]
    return StripGroup(chains), chains


def test_shape_is_the_sum():
    g, _ = group(600, 600)
    assert g.numPixels() == 1200
    assert g.lengths == (600, 600)
    assert g.count == 2


def test_uneven_chains_are_allowed():
    """A neon run has a different pixel count — the group must not assume equal."""
    g, _ = group(600, 90)
    assert g.numPixels() == 690
    assert g.lengths == (600, 90)


def test_pixels_address_one_flat_space():
    g, _ = group(4, 4)
    g.setPixelColor(0, Color(1, 2, 3))
    g.setPixelColor(7, Color(9, 8, 7))
    assert g.getPixelColor(0) == Color(1, 2, 3)
    assert g.getPixelColor(7) == Color(9, 8, 7)
    assert g.getPixelColor(8) == 0, "out of range must not wrap onto chain 0"


def test_show_splits_the_buffer_in_chain_order():
    """Pixel 4 belongs to chain 1, and must arrive at its local index 0."""
    g, chains = group(4, 4)
    g.setPixelColor(3, Color(11, 0, 0))   # last of chain 0
    g.setPixelColor(4, Color(22, 0, 0))   # first of chain 1
    g.show()
    assert len(chains[0].writes) == 1 and len(chains[1].writes) == 1
    assert chains[0].writes[0][3 * 4] == 11
    assert chains[1].writes[0][0] == 22
    assert all(len(c.writes[0]) == 16 for c in chains)


def test_extend_spreads_one_payload():
    g, chains = group(2, 3)
    payload = bytes(range(20))            # 5 LEDs x 4 bytes
    g.show_payload(payload)
    assert chains[0].writes[0] == payload[:8]
    assert chains[1].writes[0] == payload[8:]


def test_mirror_gives_each_chain_its_own_frame():
    """The point of mirroring: same wash, private highlights."""
    g, chains = group(2, 2)
    a, b = bytes([1] * 8), bytes([2] * 8)
    g.show_mirrored([a, b])
    assert chains[0].writes[0] == a
    assert chains[1].writes[0] == b


def test_every_chain_is_written_each_frame():
    """A silent chain is the failure that looks like a wiring fault."""
    g, chains = group(4, 4, 4)
    for _ in range(3):
        g.show()
    assert [len(c.writes) for c in chains] == [3, 3, 3]


def test_brightness_reaches_the_chains():
    g, chains = group(4, 4)
    g.setBrightness(128)
    assert g.getBrightness() == 128
    assert all(c.getBrightness() == 128 for c in chains)


def test_gain_is_applied_per_chain():
    g, chains = group(1, 1)
    g.show_payload(bytes([200, 200, 200, 0, 200, 200, 200, 0]), gain=128)
    for c in chains:
        assert c.writes[0][0] == (200 * 128) // 255


def test_dropped_frames_are_summed():
    g, chains = group(4, 4)
    chains[0]._dropped = 2
    chains[1]._dropped = 5
    assert g.dropped_frames == 7


def test_fill_covers_every_chain():
    g, chains = group(3, 3)
    g.fill(Color(7, 7, 7))
    g.show()
    assert all(c.writes[0] == bytes([7, 7, 7, 0] * 3) for c in chains)


def test_empty_group_is_rejected():
    with pytest.raises(ValueError):
        StripGroup([])


def test_single_chain_group_behaves_like_one_strip():
    """Degenerate case matters: it is what a config with one entry produces."""
    g, chains = group(600)
    assert g.numPixels() == 600
    assert g.lengths == (600,)
    g.show()
    assert len(chains[0].writes[0]) == 600 * 4
