# Logo der Integration

![Symbol](icon.png)

Ein Rotor über zwei Wasserwellen, auf einem Verlauf von Kaltblau nach
Warmorange. Das ist die ganze Aussage einer Luft/Wasser-Wärmepumpe: Sie holt
Wärme aus der Luft und gibt sie ans Wasser ab. Der Farbverlauf läuft diagonal
von kalt oben links nach warm unten rechts — in derselben Richtung, in der auch
die Energie wandert.

## Dateien

| Datei | Zweck |
|---|---|
| `icon.svg` | die Vorlage, von Hand gezeichnet |
| `icon.png` / `icon@2x.png` | 256 px und 512 px, RGBA mit transparenten Ecken |
| `erzeuge_png.py` | erzeugt die PNGs aus der Geometrie |

**Kein `logo.png`.** Das brands-Repository sagt es ausdrücklich: *„If the brand
uses the same image for the logo and icon (e.g., if the logo has a square aspect
ratio), only add the icon images. The icon will be used as a fallback for the
logo."* Eine quadratische Kopie würde das Repository nur größer machen.

## Warum ein eigener Rasterizer

Home Assistant verlangt für das `brands`-Repository PNGs mit **transparentem**
Hintergrund. Die naheliegenden Werkzeuge helfen hier nicht:

- `qlmanage`, auf jedem Mac vorhanden, legt die Grafik auf **Weiß**.
- `rsvg-convert`, Inkscape und ImageMagick waren nicht installiert.

Statt eine Abhängigkeit einzuführen, die später jemand nachziehen muss, zeichnet
`erzeuge_png.py` die Form direkt: dieselben Koordinaten wie im SVG, Zahl für
Zahl, mit dreifacher Überabtastung für die Kantenglättung. Es braucht nichts
außer der Standardbibliothek.

```bash
python3 brand/erzeuge_png.py
```

Läuft in wenigen Sekunden und schreibt beide Dateien.

Zur Größe: Die übliche Heuristik — je Zeile der Filter mit der kleinsten
Betragssumme — ist hier **nicht** die beste Wahl. Das Symbol besteht überwiegend
aus einfarbigen Flächen und harten Kanten; dort erzeugt jede Differenzbildung
Rauschen, das zlib schlechter packt als die Wiederholung desselben Bytes.
Gemessen: mit Heuristik 10,1 kB, ohne Filter 8,6 kB. Das Skript rät deshalb
nicht, sondern probiert sechs Strategien durch und nimmt die kleinste.

**Wer die Form ändert, ändert sie im SVG _und_ in den Konstanten oben in
`erzeuge_png.py`.** Die Verdopplung ist der Preis dafür, ohne Fremdbibliothek
auszukommen; der Kopf des Skripts sagt das auch dort.

## Damit das Logo in Home Assistant erscheint

Die Symbole der Integrationen liegen nicht im Integrations-Repository, sondern
zentral in [`home-assistant/brands`](https://github.com/home-assistant/brands).
HACS und die Oberfläche laden sie von dort.

1. `home-assistant/brands` forken.
2. Anlegen: `custom_integrations/es_heatpump/icon.png` und `icon@2x.png` —
   die beiden Dateien aus diesem Ordner.
3. Pull Request stellen. Geprüft werden Format (PNG), Seitenverhältnis (1:1),
   Größe (256 bzw. 512 Pixel) und dass das Motiv die Fläche ohne Leerraum am
   Rand ausfüllt.

Der Ordnername **muss** dem `domain` aus `manifest.json` entsprechen, also
`es_heatpump`.

Bis der Pull Request durch ist, zeigt Home Assistant das Standardsymbol. Am
Verhalten der Integration ändert das nichts.
