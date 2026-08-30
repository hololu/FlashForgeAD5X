from __future__ import annotations
import logging
from typing import Any
import aiohttp

from homeassistant.components.camera import Camera, CameraEntityFeature
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DOMAIN
from .sensor import FlashForgeBaseEntity

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """FlashForge kamera varlığını tanımlar."""
    coordinator_info = hass.data[DOMAIN][entry.entry_id]
    coordinator = coordinator_info["coordinator"]
    api = coordinator_info["api"]

    async_add_entities([FlashForgeCamera(coordinator, entry, api)])


class FlashForgeCamera(FlashForgeBaseEntity, Camera):
    """FlashForge AD5X Kamera Varlığı."""

    _attr_has_entity_name = True
    _attr_name = "FlashForge Kamera"
    _attr_icon = "mdi:camera"
    _attr_supported_features = CameraEntityFeature.STREAM

    def __init__(self, coordinator, entry: ConfigEntry, api) -> None:
        """Kamera varlığını başlatır."""
        super().__init__(coordinator, entry)
        Camera.__init__(self)
        self.api = api
        self._attr_unique_id = f"{entry.entry_id}_camera"
        self._host = entry.data["host"]
        self._mjpeg_url = f"http://{self._host}:8080/?action=stream"
        self._snapshot_url = f"http://{self._host}:8080/?action=snapshot"

    @property
    def is_on(self) -> bool:
        """Kamera açık mı?"""
        if not self.coordinator.data:
            return False
        return self.coordinator.data.get("online", False)

    @property
    def is_streaming(self) -> bool:
        """Kamera yayında mı?"""
        return self.is_on

    async def async_camera_image(
        self, width: int | None = None, height: int | None = None
    ) -> bytes | None:
        """Tek bir anlık kamera karesi çeker."""
        try:
            session = async_get_clientsession(self.hass)
            async with session.get(self._snapshot_url, timeout=aiohttp.ClientTimeout(total=4)) as response:
                if response.status == 200:
                    return await response.read()
        except Exception as e:
            _LOGGER.debug("FlashForge camera snapshot error (%s): %s", self._snapshot_url, e)
        return None

    async def async_mjpeg_stream(self, response: aiohttp.web.StreamResponse) -> None:
        """MJPEG akışını Home Assistant'a aktarır."""
        session = async_get_clientsession(self.hass)
        try:
            async with session.get(self._mjpeg_url, timeout=aiohttp.ClientTimeout(total=None)) as upstream_resp:
                if upstream_resp.status != 200:
                    return
                async for chunk in upstream_resp.content.iter_chunked(8192):
                    await response.write(chunk)
        except Exception as err:
            _LOGGER.debug("FlashForge MJPEG stream error: %s", err)
