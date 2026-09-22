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
| `logo.png` / `logo@2x.png` | identisch — die Marke ist quadratisch |
| `erzeuge_png.py` | erzeugt die PNGs aus der Geometrie |

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

Läuft in rund fünf Sekunden und schreibt alle vier Dateien.

**Wer die Form ändert, ändert sie im SVG _und_ in den Konstanten oben in
`erzeuge_png.py`.** Die Verdopplung ist der Preis dafür, ohne Fremdbibliothek
auszukommen; der Kopf des Skripts sagt das auch dort.

## Damit das Logo in Home Assistant erscheint

Die Symbole der Integrationen liegen nicht im Integrations-Repository, sondern
zentral in [`home-assistant/brands`](https://github.com/home-assistant/brands).
HACS und die Oberfläche laden sie von dort.

1. `home-assistant/brands` forken.
2. Anlegen: `custom_integrations/es_heatpump/icon.png`,
   `icon@2x.png`, `logo.png`, `logo@2x.png` — die Dateien aus diesem Ordner.
3. Pull Request stellen. Die Prüfung achtet auf Format (PNG, RGBA), Größe
   (256 bzw. 512 Pixel im Quadrat) und darauf, dass das Motiv die Fläche
   ausfüllt.

Bis der Pull Request durch ist, zeigt Home Assistant das Standardsymbol. Am
Verhalten der Integration ändert das nichts.
