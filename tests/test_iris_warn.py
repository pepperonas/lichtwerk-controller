"""Strip-Warn gate contract — the LED twin of the page's `body.over-iris`.

These drive the real Flask app through its test client. Without /dev/leds0 the
controller falls into demo mode (strip=None), which is fine: what matters here
is the state machine around the gate, not the pixels. The pixel maths is
covered by test_iris_wash.py.
"""
from __future__ import annotations

import os
import pathlib
import sys
import time

import pytest

_ROOT = pathlib.Path(__file__).parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))
os.chdir(_ROOT)                      # web_controller loads ./config.json

# The Flask runtime deps live in the Pi's venv, not necessarily on a dev box.
# Skipping keeps `pytest tests/` green everywhere while staying complete where
# it counts — test_iris_wash.py covers the colour maths with no deps at all.
pytest.importorskip("flask", reason="lichtwerk runtime deps not installed")
pytest.importorskip("flask_cors", reason="lichtwerk runtime deps not installed")

import iris_wash                     # noqa: E402
import web_controller as wc          # noqa: E402


@pytest.fixture
def client():
    wc.app.config["TESTING"] = True
    c = wc.controller
    c.strip_warn_mode = False
    c.strip_warn_over = False
    c.power = False
    c._wash_t0 = None
    c._wash_fade_t0 = None
    c.current_effect = "solid"
    with wc.app.test_client() as cl:
        yield cl


def _gate(client, over):
    return client.post("/api/warn_gate", json={"over": over})


def test_arming_leaves_the_strip_dark(client):
    r = client.post("/api/effect", json={"effect": "iris_warn", "over": False})
    assert r.status_code == 200
    c = wc.controller
    assert c.strip_warn_mode is True
    assert c.strip_warn_over is False
    assert c.power is False
    assert c._wash_t0 is None, "armed but under threshold must not start the breathe"


def test_gate_on_starts_the_breathe_at_its_peak(client):
    before = time.monotonic()
    r = _gate(client, True)
    assert r.status_code == 200
    body = r.get_json()
    assert body["over"] is True
    assert body["power"] is True
    assert body["effect"] == "iris_warn"

    c = wc.controller
    assert c.strip_warn_over is True
    # t0 is back-dated one full period so the first frame lands on the maximum
    age = before - c._wash_t0
    assert age == pytest.approx(iris_wash.BREATHE_PERIOD_S, abs=0.25)
    assert iris_wash.frame_index(time.monotonic() - c._wash_t0, 64) > 55


def test_gate_off_fades_instead_of_cutting_to_black(client):
    _gate(client, True)
    _gate(client, False)

    c = wc.controller
    assert c.strip_warn_over is False
    assert c.power is False
    assert c._wash_fade_t0 is not None, "release must ramp down like the page"
    assert c._wash_t0 is None


def test_fade_runs_even_though_power_is_off(client):
    """run_effect() checks the ramp before the power gate, or it would freeze."""
    _gate(client, True)
    _gate(client, False)
    c = wc.controller
    assert c.power is False
    assert c._wash_fade_t0 is not None
    c.run_effect()
    assert c._wash_fade_t0 is not None, "ramp aborted early"


def test_fade_finishes_and_clears(client):
    _gate(client, True)
    _gate(client, False)
    c = wc.controller
    c._wash_fade_t0 = time.monotonic() - (iris_wash.RELEASE_FADE_S + 0.05)
    c.run_effect()
    assert c._wash_fade_t0 is None
    assert c._cleared is True


def test_gate_off_is_idempotent(client):
    _gate(client, True)
    _gate(client, False)
    first = wc.controller._wash_fade_t0
    _gate(client, False)
    assert wc.controller._wash_fade_t0 == first, "re-releasing must not restart the ramp"


def test_warn_mode_off_aborts_hard(client):
    """Disarming is not a release — it drops the strip immediately."""
    _gate(client, True)
    r = client.post("/api/warn_mode", json={"on": False})
    assert r.status_code == 200
    c = wc.controller
    assert c.strip_warn_mode is False
    assert c._wash_t0 is None
    assert c._wash_fade_t0 is None, "disarm must not leave a ramp running"


def test_other_effects_are_blocked_while_armed(client):
    _gate(client, True)
    r = client.post("/api/effect", json={"effect": "rainbow"})
    assert r.get_json()["status"] == "blocked"
    assert wc.controller.current_effect == "iris_warn"


def test_iris_warn_is_a_valid_effect(client):
    r = client.post("/api/effect", json={"effect": "iris_warn", "over": False})
    assert r.get_json()["status"] == "ok"


def test_pacing_targets_the_shift_out_budget():
    """600 LEDs need 18 ms per frame; the wash must stay under the ceiling."""
    assert wc.WASH_FRAME_S > 0.018, "frame budget below the WS2812 shift-out time"
    assert wc.WASH_FPS <= 55.6
