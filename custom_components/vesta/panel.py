"""Register the Vesta schedule panel in the Home Assistant sidebar."""
from __future__ import annotations

import json
import pathlib

from homeassistant.components import panel_custom
from homeassistant.components.http import StaticPathConfig
from homeassistant.core import HomeAssistant

_MANIFEST = pathlib.Path(__file__).parent / "manifest.json"


def _version() -> str:
    try:
        return json.loads(_MANIFEST.read_text())["version"]
    except Exception:
        return "0"


async def async_setup_panel(hass: HomeAssistant) -> None:
    """Register static files and the sidebar panel."""
    frontend_dir = str(pathlib.Path(__file__).parent / "frontend")
    static_url = "/vesta_panel_static"

    await hass.http.async_register_static_paths([
        StaticPathConfig(
            url_path=static_url,
            path=frontend_dir,
            cache_headers=False,
        )
    ])

    await panel_custom.async_register_panel(
        hass,
        webcomponent_name="vesta-panel",
        frontend_url_path="vesta",
        sidebar_title="Vesta",
        sidebar_icon="mdi:thermometer-auto",
        module_url=f"{static_url}/vesta-panel.js?v={_version()}",
        embed_iframe=False,
        require_admin=False,
    )
