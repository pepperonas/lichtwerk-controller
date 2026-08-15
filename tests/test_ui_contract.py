"""UI-Vertrag der Weboberflaeche (2026-08-15).

`static/js/app.js` findet seine Elemente ausschliesslich ueber IDs — ein
Markup-Umbau kann sie lautlos entfernen, und die Seite sieht dann heil
aus, waehrend Regler und Anzeigen tot sind. Genau das haetten diese Pins
beim Kompakt-Pass gefangen. Dazu die Layout-Invarianten, die den
Desktop-Pass ausmachen (gestreckte Karten, fixe Farbfelder).
"""

from __future__ import annotations

import pathlib
import re

_ROOT = pathlib.Path(__file__).parent.parent
HTML = (_ROOT / "templates" / "index.html").read_text(encoding="utf-8")
CSS = (_ROOT / "static" / "css" / "style.css").read_text(encoding="utf-8")
JS = (_ROOT / "static" / "js" / "app.js").read_text(encoding="utf-8")


# ── Verdrahtung: jede ID, die das JS sucht, muss es auch geben ───────────


def test_every_id_the_js_looks_up_exists_in_the_template():
    wanted = set(re.findall(r"getElementById\(['\"]([\w-]+)['\"]\)", JS))
    assert wanted, "keine IDs im JS gefunden — Test waere wertlos"
    have = set(re.findall(r'id="([\w-]+)"', HTML))
    missing = sorted(wanted - have)
    assert not missing, f"JS sucht IDs, die das Markup nicht (mehr) hat: {missing}"


def test_sliders_and_readouts_survive_the_merged_card():
    for i in ("brightness-slider", "brightness-value", "speed-slider", "speed-value"):
        assert f'id="{i}"' in HTML, i


def test_device_facts_keep_the_old_system_info_ids():
    # Die System-Karte ist in die Power-Karte gewandert — die IDs bleiben,
    # sonst schreibt das JS ins Leere.
    for i in ("led-count", "gpio-pin", "current-effect"):
        assert f'id="{i}"' in HTML, i


def test_rgb_channels_are_complete():
    for ch in ("red", "green", "blue"):
        assert f'id="{ch}-slider"' in HTML and f'id="{ch}-value"' in HTML


def test_every_effect_button_carries_a_data_effect():
    btns = re.findall(r'<button[^>]*class="[^"]*effect-btn[^"]*"[^>]*>', HTML)
    assert len(btns) >= 10, f"nur {len(btns)} Effekt-Buttons gefunden"
    assert all("data-effect" in b for b in btns), "Button ohne data-effect"


def test_color_presets_all_carry_a_parsable_rgb_triplet():
    vals = re.findall(r'data-color="([^"]+)"', HTML)
    assert len(vals) >= 12
    for v in vals:
        parts = v.split(",")
        assert len(parts) == 3, v
        assert all(0 <= int(p) <= 255 for p in parts), v


# ── Layout-Invarianten des Kompakt-Passes ────────────────────────────────


def test_cards_do_not_stretch_to_row_height():
    """Die Wurzel der Leerflaeche unter dem Power-Knopf: Grid-Kinder
    strecken sich per Default auf die Zeilenhoehe."""
    assert re.search(r"main\s*\{[^}]*align-items:\s*start", CSS), \
        "align-items:start fehlt — die Power-Karte waechst wieder mit"


def test_mobile_color_swatches_are_fluid_not_fixed():
    """Feste 40 px in `repeat(6,1fr)`-Spuren liefen aus der Karte."""
    mobile = CSS[CSS.rindex("@media (max-width: 767px)"):]
    assert "aspect-ratio: 1" in mobile
    assert re.search(r"\.color-preset\s*\{[^}]*width:\s*auto", mobile), \
        "Farbfelder wieder auf feste Breite gesetzt"


def test_desktop_densification_is_scoped_to_wide_viewports():
    """Die kleinen Groessen duerfen mobil NICHT gelten (Touch-Ziele)."""
    block = CSS[CSS.index("@media (min-width: 768px)"):]
    assert re.search(r"\.power-button\s*\{[^}]*width:\s*72px", block)
    assert re.search(r"\.color-preset\s*\{[^}]*width:\s*34px", block)


def test_assets_are_versioned_so_a_deploy_can_reach_the_browser():
    """Unversionierte CSS/JS wurden vom Dashboard-SW dauerhaft festgehalten."""
    assert re.search(r'style\.css\?v=\d+', HTML), "style.css ohne ?v="
    assert re.search(r'app\.js\?v=\d+', HTML), "app.js ohne ?v="


def test_power_button_is_keyboard_operable():
    m = re.search(r'<div class="power-button"[^>]*>', HTML)
    assert m, "power-button nicht gefunden"
    assert 'role="button"' in m.group(0) and "tabindex" in m.group(0)


def test_shared_nav_and_icons_are_embedded_with_a_version():
    assert re.search(r'nav\.js\?v=\d+', HTML)
    assert re.search(r'icons\.js\?v=\d+', HTML)


# --- Abstand Kopf -> Inhalt (Haus-Norm 16 px, Audit 2026-08-15) -------------

def _header_rule():
    m = re.search(r"\nheader\s*\{[^}]*\}", CSS)
    assert m, "header-Regel nicht gefunden"
    return m.group(0)


def test_header_sets_no_spacing_of_its_own():
    """⚠️ `.container` ist ein GRID mit `gap`, und ein Gap ADDIERT sich zu den
    Raendern der Kinder. Mit eigenem Unterpolster ODER Unterrand am Kopf waren
    es 32 statt der gemessenen Haus-Norm von 16 px. Den Abstand setzt allein
    das Gap — beide Wege am Kopf muessen zu bleiben."""
    regel = _header_rule()
    assert not re.search(r"padding:\s*0\s+0\s+var\(--sh-gap-lg\)", regel), \
        "der Kopf bringt wieder ein Unterpolster mit"
    assert not re.search(r"margin-bottom:\s*var\(--sh-gap-lg\)", regel), \
        "der Kopf bringt wieder einen Unterrand mit"


def test_container_gap_carries_the_spacing():
    m = re.search(r"\.container\s*\{[^}]*\}", CSS)
    assert m, ".container-Regel nicht gefunden"
    assert "display: grid" in m.group(0)
    assert re.search(r"gap:\s*var\(--sh-gap-lg\)", m.group(0)), \
        "ohne Gap gaebe es gar keinen Abstand mehr"


def test_cards_do_not_stretch_to_the_row_height():
    """Ohne `align-items:start` waren die Karten so hoch wie die hoechste der
    Zeile — unter dem Power-Knopf standen dadurch ~300 px Nichts."""
    assert re.search(r"main\s*\{\s*align-items:\s*start", CSS)
