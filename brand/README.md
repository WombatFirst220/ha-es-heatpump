# Logo der Integration

![Symbol](../custom_components/es_heatpump/brand/icon.png)

Ein Rotor über zwei Wasserwellen, auf einem Verlauf von Kaltblau nach
Warmorange. Das ist die ganze Aussage einer Luft/Wasser-Wärmepumpe: Sie holt
Wärme aus der Luft und gibt sie ans Wasser ab. Der Farbverlauf läuft diagonal
von kalt oben links nach warm unten rechts — in derselben Richtung, in der auch
die Energie wandert.

## Wo was liegt

| Ort | Inhalt |
|---|---|
| `brand/` (dieser Ordner) | die **Quelle**: `icon.svg`, `erzeuge_png.py`, diese Beschreibung |
| `custom_components/es_heatpump/brand/` | die **ausgelieferten** PNGs: `icon.png`, `icon@2x.png` |

Der Generator schreibt direkt in den zweiten Ordner. Die Trennung hat einen
Grund: HACS kopiert nur `custom_components/es_heatpump/` in die Installation.
Eine Vorlage und ein Rasterizer, die dort mitreisen, wären toter Ballast auf
jedem System, das die Integration nutzt.

```bash
python3 brand/erzeuge_png.py
```

## Wie das Symbol in Home Assistant landet

**Seit Home Assistant 2026.3 bringt eine Custom-Integration ihr Symbol selbst
mit.** Es genügt ein Ordner `brand/` auf oberster Ebene der Integration. Aus
`homeassistant/loader.py`:

```python
@cached_property
def has_branding(self) -> bool:
    """Return if the integration has brand assets."""
    return "brand" in self._top_level_files
```

und aus `homeassistant/components/brands/__init__.py`:

```python
brand_dir = Path(integration.file_path) / "brand"
```

Keine Änderung an `manifest.json` nötig. Lokale Bilder haben Vorrang vor dem
Brands-CDN.

Erkannte Dateinamen sind `icon.png`, `logo.png`, `icon@2x.png`, `logo@2x.png`
sowie die vier `dark_`-Varianten. Fehlt eine, greift eine Ersatzkette —
`logo.png` fällt auf `icon.png` zurück, `icon@2x.png` ebenfalls. Deshalb
genügen hier zwei Dateien für alle acht Abrufwege.

## Der alte Weg ist geschlossen

Bis Anfang 2026 wanderten diese Bilder per Pull Request nach
[`home-assistant/brands`](https://github.com/home-assistant/brands). **Das geht
nicht mehr.** Die PR-Vorlage dort sagt es, und ein Workflow setzt es durch:

> Pull requests for adding new custom components will no longer be accepted.

`.github/workflows/close-new-custom-integrations.yml` erkennt jeden neu
angelegten Ordner unter `custom_integrations/`, kommentiert und **schließt den
Pull Request automatisch**. Ein Einreichen wäre also folgenlos geblieben.

Ankündigung:
<https://developers.home-assistant.io/blog/2026/02/24/brands-proxy-api>

## Warum ein eigener Rasterizer

Home Assistant erwartet PNGs mit **transparentem** Hintergrund. Die
naheliegenden Werkzeuge helfen hier nicht:

- `qlmanage`, auf jedem Mac vorhanden, legt die Grafik auf **Weiß**.
- `rsvg-convert`, Inkscape und ImageMagick waren nicht installiert.

Statt eine Abhängigkeit einzuführen, die später jemand nachziehen muss, zeichnet
`erzeuge_png.py` die Form direkt: dieselben Koordinaten wie im SVG, Zahl für
Zahl, mit dreifacher Überabtastung für die Kantenglättung. Es braucht nichts
außer der Standardbibliothek.

Zur Dateigröße: Die übliche Heuristik — je Zeile der PNG-Filter mit der
kleinsten Betragssumme — ist hier **nicht** die beste Wahl. Das Symbol besteht
überwiegend aus einfarbigen Flächen und harten Kanten; dort erzeugt jede
Differenzbildung Rauschen, das zlib schlechter packt als die Wiederholung
desselben Bytes. Gemessen: mit Heuristik 10,1 kB, ohne Filter 8,6 kB. Das
Skript rät deshalb nicht, sondern probiert sechs Strategien durch und nimmt die
kleinste.

**Wer die Form ändert, ändert sie im SVG _und_ in den Konstanten oben in
`erzeuge_png.py`.** Die Verdopplung ist der Preis dafür, ohne Fremdbibliothek
auszukommen; der Kopf des Skripts sagt das auch dort.

## Geprüft

| | `icon.png` | `icon@2x.png` |
|---|---|---|
| Größe | 256×256 | 512×512 |
| Seitenverhältnis | 1:1 | 1:1 |
| Farbtyp | RGBA, 8 bit | RGBA, 8 bit |
| Interlacing | keines | keines |
| CRC aller Blöcke | gültig | gültig |
| Ecken | Alpha 0 | Alpha 0 |
| Leerraum am Rand | keiner | keiner |
| Dateigröße | 8,6 kB | 19,8 kB |
