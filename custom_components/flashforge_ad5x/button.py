from __future__ import annotations
import logging
from dataclasses import dataclass

from homeassistant.components.button import ButtonEntity, ButtonEntityDescription
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DOMAIN
from .sensor import FlashForgeBaseEntity

_LOGGER = logging.getLogger(__name__)

@dataclass(frozen=True, kw_only=True)
class FlashForgeButtonDescription(ButtonEntityDescription):
    """FlashForge buton tanım sınıfı."""
    command: str


BUTTON_DESCRIPTIONS: list[FlashForgeButtonDescription] = [
    FlashForgeButtonDescription(
        key="home",
        name="Tüm Eksenleri Sıfırla (Home)",
        icon="mdi:home-map-marker",
        command="~G28\r\n",
    ),
    FlashForgeButtonDescription(
        key="pause",
        name="Baskıyı Duraklat (Pause)",
        icon="mdi:pause-circle",
        command="~M25\r\n",
    ),
    FlashForgeButtonDescription(
        key="resume",
        name="Baskıya Devam Et (Resume)",
        icon="mdi:play-circle",
        command="~M24\r\n",
    ),
    FlashForgeButtonDescription(
        key="stop",
        name="Baskıyı İptal Et (Stop)",
        icon="mdi:stop-circle",
        command="~M26\r\n",
    ),
    FlashForgeButtonDescription(
        key="clear_platform",
        name="Platformu Temizle / Sıfırla (Clear Platform)",
        icon="mdi:broom",
        command="~M26\r\n",
    ),
    FlashForgeButtonDescription(
        key="reboot",
        name="Yazıcıyı Yeniden Başlat (Restart)",
        icon="mdi:restart",
        command="~M999\r\n",
    ),
    FlashForgeButtonDescription(
        key="unlock",
        name="Oturumu Sıfırla (Unlock)",
        icon="mdi:lock-open-variant",
        command="~M602\r\n",
    ),
]


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """FlashForge kontrol butonlarını tanımlar."""
    coordinator_info = hass.data[DOMAIN][entry.entry_id]
    coordinator = coordinator_info["coordinator"]
    api = coordinator_info["api"]

    entities = [
        FlashForgeButton(coordinator, entry, api, description)
        for description in BUTTON_DESCRIPTIONS
    ]

    async_add_entities(entities)


class FlashForgeButton(FlashForgeBaseEntity, ButtonEntity):
    """FlashForge kontrol butonu sınıfı."""

    entity_description: FlashForgeButtonDescription

    def __init__(
        self,
        coordinator,
        entry: ConfigEntry,
        api,
        description: FlashForgeButtonDescription,
    ) -> None:
        """Butonu başlatır."""
        super().__init__(coordinator, entry)
        self.api = api
        self.entity_description = description
        self._attr_unique_id = f"{entry.entry_id}_{description.key}"
        self._attr_name = f"FlashForge {description.name}"

    async def async_press(self) -> None:
        """Butona basıldığında komutu gönderir."""
        _LOGGER.info(
            "Yazıcıya buton komutu gönderiliyor (%s): %s",
            self.name,
            self.entity_description.command.strip(),
        )
        if self.entity_description.key == "clear_platform":
            await self.api.async_clear_platform()
        else:
            await self.api.async_send_command(self.entity_description.command)
        # Verilerin hızlı güncellenmesini tetiklemek için koordinatör güncellemesini tetikle
        await self.coordinator.async_request_refresh()
