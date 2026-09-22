#!/usr/bin/env python3
"""Rendert brand/icon.svg als PNG - ohne externe Abhaengigkeiten.

Warum nicht einfach ein Konverter: Home Assistant verlangt fuer das
brands-Repository PNGs mit **transparentem** Hintergrund. `qlmanage`, das auf
jedem Mac vorhanden ist, legt die Grafik auf Weiss; `rsvg-convert`, `inkscape`
und ImageMagick sind hier nicht installiert. Statt eine Abhaengigkeit
einzufuehren, die spaeter jemand nachziehen muss, zeichnet dieses Skript die
Form direkt - dieselbe Geometrie wie im SVG, Zahl fuer Zahl.

Kantenglaettung durch Ueberabtastung: gerechnet wird mit dem Faktor SS pro
Achse, danach wird gemittelt.

Aufruf:  python3 brand/erzeuge_png.py
Ergebnis: icon.png (256), icon@2x.png (512), logo.png, logo@2x.png
"""
from __future__ import annotations

import pathlib
import struct
import zlib

HIER = pathlib.Path(__file__).parent
SS = 3                      # Ueberabtastung je Achse

# ── Geometrie, identisch zu icon.svg ────────────────────────────────────────
ECKRADIUS = 56.0
NABE = (128.0, 104.0)
NABENRADIUS = 15.0
PUNKTRADIUS = 6.5

FLUEGEL = [(128, 104), (118, 74), (121, 46), (134, 26),
           (163, 42), (170, 78), (153, 101)]     # Start + zwei Kubiken

WELLE_1 = [(44, 186), (64, 170), (84, 170), (104, 186),
           (124, 202), (144, 202), (164, 186),
           (184, 170), (200, 170), (212, 180)]
WELLE_2 = [(x, y + 36) for x, y in WELLE_1]
WELLENBREITE = 13.0

WEISS = (255, 255, 255)
PUNKTFARBE = (0x2E, 0x8B, 0xD6)
VERLAUF = [(0.00, (0x22, 0xB8, 0xF0)),
           (0.52, (0x2E, 0x8B, 0xD6)),
           (1.00, (0xF2, 0x93, 0x0B))]


# ── Kurven ──────────────────────────────────────────────────────────────────

def kubik(p0, p1, p2, p3, schritte=24):
    """Bezier in Strecken aufloesen."""
    aus = []
    for i in range(1, schritte + 1):
        t = i / schritte
        u = 1 - t
        aus.append((
            u*u*u*p0[0] + 3*u*u*t*p1[0] + 3*u*t*t*p2[0] + t*t*t*p3[0],
            u*u*u*p0[1] + 3*u*u*t*p1[1] + 3*u*t*t*p2[1] + t*t*t*p3[1],
        ))
    return aus


def pfad(punkte):
    """Folge aus Startpunkt und je drei Stuetzpunkten zu einem Polygonzug."""
    aus = [punkte[0]]
    for i in range(1, len(punkte) - 2, 3):
        aus += kubik(aus[-1], punkte[i], punkte[i+1], punkte[i+2])
    return aus


def drehe(punkte, winkel_grad, mitte):
    import math
    w = math.radians(winkel_grad)
    c, s = math.cos(w), math.sin(w)
    mx, my = mitte
    return [((x-mx)*c - (y-my)*s + mx, (x-mx)*s + (y-my)*c + my)
            for x, y in punkte]


# ── Rasterung ───────────────────────────────────────────────────────────────

def fuelle_polygon(maske, breite, hoehe, punkte, skala):
    """Scanline-Fuellung nach der Ungerade-Regel, in Geraetekoordinaten."""
    p = [(x*skala, y*skala) for x, y in punkte]
    ymin = max(0, int(min(y for _, y in p)))
    ymax = min(hoehe - 1, int(max(y for _, y in p)) + 1)
    n = len(p)
    for y in range(ymin, ymax + 1):
        yc = y + 0.5
        schnitte = []
        for i in range(n):
            x1, y1 = p[i]
            x2, y2 = p[(i + 1) % n]
            if (y1 <= yc < y2) or (y2 <= yc < y1):
                schnitte.append(x1 + (yc - y1) * (x2 - x1) / (y2 - y1))
        schnitte.sort()
        for i in range(0, len(schnitte) - 1, 2):
            a = max(0, int(schnitte[i] + 0.5))
            b = min(breite - 1, int(schnitte[i+1] - 0.5))
            if b >= a:
                zeile = y * breite
                for x in range(a, b + 1):
                    maske[zeile + x] = 1


def fuelle_kreis(maske, breite, hoehe, mitte, radius, skala):
    cx, cy, r = mitte[0]*skala, mitte[1]*skala, radius*skala
    r2 = r * r
    for y in range(max(0, int(cy-r)), min(hoehe-1, int(cy+r)+1) + 1):
        dy = y + 0.5 - cy
        rest = r2 - dy*dy
        if rest <= 0:
            continue
        dx = rest ** 0.5
        a, b = max(0, int(cx-dx+0.5)), min(breite-1, int(cx+dx-0.5))
        zeile = y * breite
        for x in range(a, b + 1):
            maske[zeile + x] = 1


def zeichne_linie(maske, breite, hoehe, punkte, dicke, skala):
    """Dicke Linie mit runden Enden: Scheiben entlang des Zuges stempeln."""
    r = dicke / 2.0
    vorher = None
    for x, y in punkte:
        if vorher is not None:
            # Zwischenpunkte, damit keine Luecken entstehen
            n = max(1, int(((x-vorher[0])**2 + (y-vorher[1])**2) ** 0.5))
            for i in range(1, n + 1):
                t = i / n
                fuelle_kreis(maske, breite, hoehe,
                             (vorher[0] + (x-vorher[0])*t,
                              vorher[1] + (y-vorher[1])*t), r, skala)
        else:
            fuelle_kreis(maske, breite, hoehe, (x, y), r, skala)
        vorher = (x, y)


def rundrechteck(maske, breite, hoehe, seite, radius, skala):
    r = radius * skala
    s = seite * skala
    for y in range(hoehe):
        yc = y + 0.5
        zeile = y * breite
        for x in range(breite):
            xc = x + 0.5
            # Naechster Punkt des inneren Rechtecks
            nx = min(max(xc, r), s - r)
            ny = min(max(yc, r), s - r)
            if (xc-nx)**2 + (yc-ny)**2 <= r*r:
                maske[zeile + x] = 1


def verlauf_farbe(t):
    t = min(1.0, max(0.0, t))
    for i in range(len(VERLAUF) - 1):
        t0, c0 = VERLAUF[i]
        t1, c1 = VERLAUF[i+1]
        if t0 <= t <= t1:
            f = (t - t0) / (t1 - t0) if t1 > t0 else 0.0
            return tuple(round(c0[k] + (c1[k]-c0[k]) * f) for k in range(3))
    return VERLAUF[-1][1]


def schreibe_png(pfad_datei, breite, hoehe, pixel):
    """RGBA-Bytes als PNG ablegen."""
    roh = bytearray()
    for y in range(hoehe):
        roh.append(0)                                  # Filter "None"
        roh += pixel[y*breite*4:(y+1)*breite*4]

    def block(typ, daten):
        return (struct.pack(">I", len(daten)) + typ + daten
                + struct.pack(">I", zlib.crc32(typ + daten) & 0xFFFFFFFF))

    datei = (b"\x89PNG\r\n\x1a\n"
             + block(b"IHDR", struct.pack(">IIBBBBB", breite, hoehe, 8, 6, 0, 0, 0))
             + block(b"IDAT", zlib.compress(bytes(roh), 9))
             + block(b"IEND", b""))
    pathlib.Path(pfad_datei).write_bytes(datei)
    return len(datei)


def rendere(kante: int) -> bytes:
    """Ein quadratisches Symbol der Kantenlaenge `kante` als RGBA-Bytes."""
    gr = kante * SS
    skala = gr / 256.0

    hintergrund = bytearray(gr * gr)
    weiss = bytearray(gr * gr)
    welle2 = bytearray(gr * gr)
    punkt = bytearray(gr * gr)

    rundrechteck(hintergrund, gr, gr, 256, ECKRADIUS, skala)

    fluegel = pfad(FLUEGEL)
    for winkel in (0, 120, 240):
        fuelle_polygon(weiss, gr, gr, drehe(fluegel, winkel, NABE), skala)
    fuelle_kreis(weiss, gr, gr, NABE, NABENRADIUS, skala)

    zeichne_linie(weiss, gr, gr, pfad(WELLE_1), WELLENBREITE, skala)
    zeichne_linie(welle2, gr, gr, pfad(WELLE_2), WELLENBREITE, skala)

    fuelle_kreis(punkt, gr, gr, NABE, PUNKTRADIUS, skala)

    # Zusammensetzen mit Mittelung ueber die Ueberabtastung
    aus = bytearray(kante * kante * 4)
    teiler = SS * SS
    for oy in range(kante):
        for ox in range(kante):
            r = g = b = a = 0
            for sy in range(SS):
                yy = oy * SS + sy
                zeile = yy * gr
                for sx in range(SS):
                    xx = ox * SS + sx
                    i = zeile + xx
                    if not hintergrund[i]:
                        continue
                    a += 255
                    if punkt[i]:
                        fr, fg, fb = PUNKTFARBE
                    elif weiss[i]:
                        fr, fg, fb = WEISS
                    else:
                        gv = verlauf_farbe((xx / gr + yy / gr) / 2.0)
                        if welle2[i]:
                            # Zweite Welle mit 55 % Deckung
                            fr = round(gv[0] + (255 - gv[0]) * 0.55)
                            fg = round(gv[1] + (255 - gv[1]) * 0.55)
                            fb = round(gv[2] + (255 - gv[2]) * 0.55)
                        else:
                            fr, fg, fb = gv
                    r += fr; g += fg; b += fb
            j = (oy * kante + ox) * 4
            if a:
                # Nicht durch teiler, sondern durch die gedeckten Teilproben -
                # sonst werden die Kanten zum Rand hin dunkel statt nur durchsichtig.
                n = a // 255
                aus[j]   = r // n
                aus[j+1] = g // n
                aus[j+2] = b // n
                aus[j+3] = a // teiler
    return bytes(aus)


def main() -> None:
    for name, kante in (("icon.png", 256), ("icon@2x.png", 512)):
        pixel = rendere(kante)
        groesse = schreibe_png(HIER / name, kante, kante, pixel)
        print(f"  {name:12s} {kante}x{kante}  {groesse/1024:.1f} kB")
        # Home Assistant nimmt fuer quadratische Marken dasselbe Bild als Logo.
        logo = name.replace("icon", "logo")
        schreibe_png(HIER / logo, kante, kante, pixel)
        print(f"  {logo:12s} {kante}x{kante}  (Kopie)")


if __name__ == "__main__":
    main()
