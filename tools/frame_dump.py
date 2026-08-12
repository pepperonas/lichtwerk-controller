#!/usr/bin/env python3
"""Offline-Sichtpruefung der Iris-Effekte — ohne Hardware, ohne Audio.

Treibt effect_iris_warn mit FakeStrip + Fake-Uhr und gibt jeden Frame als
ASCII-Zeile aus (Helligkeitsrampe, 100 Zeichen fuer 600 px) — Bewegung und
Schweifprofil sind direkt im Terminal beurteilbar. Optional ein PPM-Bild
(eine Frame-Zeile pro Pixelreihe) fuer die genaue Betrachtung.

Beispiele:
  python3 tools/frame_dump.py --kind meteor --v 1200 --frames 80
  python3 tools/frame_dump.py --kind meteor --v 2400 --dir -1 --ppm /tmp/meteor.ppm
  python3 tools/frame_dump.py --kind stardust --dur-ms 800 --frames 60
  python3 tools/frame_dump.py --kind sweep --dur-ms 700 --origin 0.2
"""

import argparse
import pathlib
import sys
import types

_ROOT = pathlib.Path(__file__).parent.parent
for _p in (str(_ROOT), str(_ROOT / "tests")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

try:
    import flask_cors  # noqa: F401
except ImportError:
    sys.modules['flask_cors'] = types.SimpleNamespace(CORS=lambda app: None)

import web_controller as wc                          # noqa: E402
from test_iris_warn_smoke import FakeStrip, fresh    # noqa: E402

RAMP = " .:-=+*#%@"


def luma(px):
    r, g, b = (px >> 16) & 255, (px >> 8) & 255, px & 255
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def ascii_row(pxs, width=100):
    n = len(pxs)
    cells = []
    for c in range(width):
        lo, hi = c * n // width, max(c * n // width + 1, (c + 1) * n // width)
        v = max(luma(pxs[i]) for i in range(lo, hi))
        cells.append(RAMP[min(len(RAMP) - 1, int(v / 255.0 * (len(RAMP) - 1) + 0.5))])
    return "".join(cells)


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--kind", default="meteor")
    ap.add_argument("--v", type=float, default=0.0, help="Meteor-Tempo LED/s (0 = wuerfeln)")
    ap.add_argument("--dir", type=int, default=1, dest="direction")
    ap.add_argument("--n", type=int, default=1)
    ap.add_argument("--dur-ms", type=float, default=0.0)
    ap.add_argument("--origin", type=float, default=0.5)
    ap.add_argument("--intensity", type=float, default=1.0)
    ap.add_argument("--density", type=float, default=1.0)
    ap.add_argument("--frames", type=int, default=80)
    ap.add_argument("--warmup", type=int, default=16)
    ap.add_argument("--dt", type=float, default=0.02)
    ap.add_argument("--seed", type=int, default=11)
    ap.add_argument("--leds", type=int, default=600)
    ap.add_argument("--ppm", help="zusaetzlich als PPM-Bild speichern")
    args = ap.parse_args()

    state = {"t": 100.0}
    c = fresh(FakeStrip(args.leds))
    c.iris_clock = lambda: state["t"]
    wc.apply_iris_config({"seed": args.seed})
    rows = []
    try:
        for _ in range(args.warmup):
            state["t"] += args.dt
            c.effect_iris_warn()
        c.effect_params.setdefault("iris_events", []).append({
            "kind": args.kind, "gap": 0.16, "n": args.n,
            "dur": args.dur_ms / 1000.0, "v": args.v,
            "intensity": args.intensity, "density": args.density,
            "origin": args.origin, "dir": args.direction})
        import time as _time
        comp = 0.0
        for f in range(args.frames):
            state["t"] += args.dt
            w0 = _time.perf_counter()
            c.effect_iris_warn()
            comp += _time.perf_counter() - w0
            rows.append(list(c.strip._px))
            bri = c.strip.getBrightness()
            print(f"{f:3d} |{ascii_row(rows[-1])}| lut={bri}")
        print(f"\nFrame-Zeit: {comp / args.frames * 1000:.2f} ms/Frame "
              f"({args.leds} px, Fake-Strip)")
        if args.ppm:
            with open(args.ppm, "wb") as fh:
                fh.write(f"P6 {args.leds} {len(rows)} 255\n".encode())
                for row in rows:
                    fh.write(bytes(v for px in row
                                   for v in ((px >> 16) & 255, (px >> 8) & 255, px & 255)))
            print(f"PPM: {args.ppm} ({args.leds}x{len(rows)}, eine Zeile je Frame)")
    finally:
        wc.apply_iris_config(None)
        del c.iris_clock


if __name__ == "__main__":
    main()
