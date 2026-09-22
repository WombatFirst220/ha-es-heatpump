"""Geraeteeintrag aus den echten Stammdaten der Anlage.

Bis v2.5.0 stand im Geraeteregister ein fest verdrahteter Modellname. Jetzt, wo
Modell, Seriennummer und Firmware-Stand aus dem Portal kommen, steht dort das,
was tatsaechlich an der Wand haengt - und Home Assistant zeigt es auf jeder
Geraeteseite an, ohne dass man dafuer eine Entity oeffnen muesste.
"""
from __future__ import annotations

from typing import Any

from homeassistant.helpers.device_registry import DeviceInfo

from .const import DEVICE_MANUFACTURER, DEVICE_MODEL, DEVICE_NAME, DOMAIN
from .metadata import Stammdaten


def baue_device_info(
    username: str,
    base_url: str,
    stammdaten: Stammdaten | None = None,
    konfiguration: dict[str, Any] | None = None,
) -> DeviceInfo:
    """Baut den Geraeteeintrag, so vollstaendig wie die Daten es hergeben."""
    s = stammdaten or Stammdaten()

    # Firmware: par2 aus der Konfiguration ist die Softwareversion der
    # Bedieneinheit, par137 die der Waermepumpen-Platine. Beide sind
    # aussagekraeftig, deshalb beide.
    firmware: str | None = None
    if konfiguration:
        bedien = konfiguration.get("par2")
        platine = konfiguration.get("par137")
        teile = []
        if bedien is not None:
            teile.append(f"Bedieneinheit {bedien:g}")
        if platine is not None:
            teile.append(f"Platine {platine:g}")
        firmware = ", ".join(teile) or None

    # Seriennummer: die des Aussengeraets ist die, die auf dem Typenschild und
    # in Garantievorgaengen steht.
    seriennummer = (
        s.seriennummer_aussengeraet or s.seriennummer or s.mac or None
    )

    info = DeviceInfo(
        identifiers={(DOMAIN, username)},
        name=DEVICE_NAME,
        manufacturer=DEVICE_MANUFACTURER,
        model=s.modell or DEVICE_MODEL,
        configuration_url=base_url,
    )
    if seriennummer:
        info["serial_number"] = seriennummer
    if firmware:
        info["sw_version"] = firmware
    if s.mac:
        # Als Hardware-Stand ausgewiesen, nicht als Netzwerkverbindung: Das
        # Geraet haengt nicht im eigenen LAN, die MAC kommt aus der Cloud.
        info["hw_version"] = f"MAC {s.mac}"
    return info
