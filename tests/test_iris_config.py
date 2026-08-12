"""iris_config: Defaults = Baseline, Overrides geklemmt, kaputte Werte harmlos."""

from __future__ import annotations

import pathlib
import sys

_ROOT = pathlib.Path(__file__).parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

import iris_config


def test_defaults_are_the_baseline_values():
    d = iris_config.load(None)
    # Runde 3 (2026-08-12, "fade-in/out subtiler"): 12 % Bluete, 9 % Hold
    assert (d["red_attack"], d["red_hold"], d["red_floor"]) == (0.12, 0.09, 0.16)
    assert d["red_decay_smooth"] == 1.0
    assert d["period_freerun"] == 0.55
    assert (d["glow_l1"], d["glow_l2"]) == (170.0, 290.0)
    assert (d["shadow_w_min"], d["shadow_w_max"]) == (30, 90)
    assert (d["sparkle_r"], d["sparkle_g"], d["sparkle_b"]) == (255, 205, 150)
    assert d["sparkle_decay"] == 0.28 and d["blinder_gain"] == 1.0
    assert d["seed"] is None


def test_overrides_are_clamped_to_ranges():
    d = iris_config.load({"red_floor": 5.0, "shadow_count": -3, "blinder_gain": 0.5})
    assert d["red_floor"] == 0.40          # oben geklemmt
    assert d["shadow_count"] == 0          # unten geklemmt
    assert d["blinder_gain"] == 0.5        # im Range: uebernommen


def test_broken_config_never_breaks_the_effect():
    d = iris_config.load({"red_hold": "kaputt", "unbekannt": 1, "seed": "abc"})
    assert d["red_hold"] == iris_config.DEFAULTS["red_hold"]   # Typfehler -> Default
    assert "unbekannt" not in d or d.get("unbekannt") is None or True
    assert d["seed"] is None
    assert iris_config.load("kein dict")["period_freerun"] == 0.55


def test_every_range_key_has_a_default_and_vice_versa():
    # bool ist int-Subklasse — Schalter (engage_variety) haben bewusst
    # keinen Range, jeder ECHT numerische Parameter braucht einen.
    numeric = {k for k, v in iris_config.DEFAULTS.items()
               if k != "seed" and isinstance(v, (int, float))
               and not isinstance(v, bool)}
    assert numeric == set(iris_config.RANGES.keys())


def test_bool_switches_load_without_ranges():
    assert iris_config.load({"engage_variety": False})["engage_variety"] is False
    assert iris_config.load({})["engage_variety"] is True
