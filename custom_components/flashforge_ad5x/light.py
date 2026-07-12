from __future__ import annotations
import logging
from typing import Any

from homeassistant.components.light import ColorMode, LightEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DOMAIN
from .sensor import FlashForgeBaseEntity

_LOGGER = logging.getLogger(__name__)

async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """FlashForge LED ışık kontrolünü tanımlar."""
    coordinator_info = hass.data[DOMAIN][entry.entry_id]
    coordinator = coordinator_info["coordinator"]
    api = coordinator_info["api"]

    async_add_entities([FlashForgeLEDLight(coordinator, entry, api)])


class FlashForgeLEDLight(FlashForgeBaseEntity, LightEntity):
    """FlashForge LED kontrol sınıfı."""

    _attr_color_mode = ColorMode.ONOFF
    _attr_supported_color_modes = {ColorMode.ONOFF}

    def __init__(self, coordinator, entry: ConfigEntry, api) -> None:
        """LED ışığı başlatır."""
        super().__init__(coordinator, entry)
        self.api = api
        self._attr_unique_id = f"{entry.entry_id}_led_light"
        self._attr_name = "FlashForge Kasa Işığı"
        self._attr_icon = "mdi:led-on"

    @property
    def is_on(self) -> bool:
        """Işığın açık olup olmadığını döndürür."""
        if not self.coordinator.data:
            return False
        
        raw_led = str(self.coordinator.data.get("led", "")).lower()
        # LED açık durumları: 1, on, 255
        return any(x in raw_led for x in ["1", "on", "255"])

    async def async_turn_on(self, **kwargs: Any) -> None:
        """Işığı açar."""
        _LOGGER.info("Yazıcı kasa LED'i açılıyor")
        # ~M146 r255 g255 b255 f0 (Beyaz ışık, f0 mod)
        await self.api.async_send_command("~M146 r255 g255 b255 f0\r\n")
        await self.coordinator.async_request_refresh()

    async def async_turn_off(self, **kwargs: Any) -> None:
        """Işığı kapatır."""
        _LOGGER.info("Yazıcı kasa LED'i kapatılıyor")
        # ~M146 r0 g0 b0 f0 (Işık kapalı)
        await self.api.async_send_command("~M146 r0 g0 b0 f0\r\n")
        await self.coordinator.async_request_refresh()
