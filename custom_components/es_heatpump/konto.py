"""Benutzerwechsel im Reconfigure-Dialog (v4.1.0) - die reine Logik.

Der Portal-Benutzer steckt in jeder unique_id (``es_heatpump_<benutzer>_...``)
und in der Geraetekennung ``(es_heatpump, <benutzer>)``. Aendert sich der
Benutzer (neues Portal-Konto fuer dieselbe Anlage, korrigierte Schreibweise),
wuerden beim Neuladen alle Entities mit neuen unique_ids angelegt - als
Doppelgaenger mit ``_2`` in der ID, und Historie und Statistik blieben bei den
alten, verwaisten Eintraegen.

Deshalb schreibt der Dialog vor dem Neuladen die Register um: gleiche
Entity-IDs, gleiche Historie, nur der Benutzer-Teil der Kennung ist neu. Die
Entity-IDs selbst (``sensor.es_hp_...``) enthalten den Benutzer nicht und
bleiben unberuehrt.

Das Modul ist frei von Home-Assistant-Importen und laesst sich ohne HA testen.
"""
from __future__ import annotations


def umbenannte_unique_id(
    unique_id: str | None, domain: str, alt: str, neu: str
) -> str | None:
    """unique_id mit neuem Benutzer - oder None, wenn sie nicht betroffen ist.

    Ersetzt wird nur das Praefix ``<domain>_<alt>_``, damit ein Benutzername,
    der zufaellig auch im Rest vorkommt, dort stehen bleibt.
    """
    if not unique_id or alt == neu:
        return None
    praefix = f"{domain}_{alt}_"
    if not unique_id.startswith(praefix):
        return None
    return f"{domain}_{neu}_{unique_id[len(praefix):]}"


def neuer_titel(titel: str, alt: str, neu: str) -> str:
    """Titel des Eintrags nachziehen, solange er der automatisch vergebene ist."""
    if titel == f"ES Heatpump ({alt})":
        return f"ES Heatpump ({neu})"
    return titel
