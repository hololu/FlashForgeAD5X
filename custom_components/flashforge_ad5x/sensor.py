from __future__ import annotations
import logging
from dataclasses import dataclass
from typing import Any, Callable

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorEntityDescription,
    SensorStateClass,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_HOST, PERCENTAGE, UnitOfTemperature
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN

_LOGGER = logging.getLogger(__name__)

@dataclass(frozen=True, kw_only=True)
class FlashForgeSensorDescription(SensorEntityDescription):
    """FlashForge sensör tanım sınıfı."""
    value_fn: Callable[[dict[str, Any]], Any]
    extra_attrs_fn: Callable[[dict[str, Any]], dict[str, Any]] | None = None


SENSOR_DESCRIPTIONS: list[FlashForgeSensorDescription] = [
    FlashForgeSensorDescription(
        key="machine_status",
        name="Yazıcı Durumu",
        icon="mdi:printer-3d",
        value_fn=lambda data: data.get("machine_status"),
        extra_attrs_fn=lambda data: {
            "hareket_modu": data.get("move_mode"),
            "durum_bayraklari": data.get("status_flags"),
            "endstop_x": data.get("endstop_x"),
            "endstop_y": data.get("endstop_y"),
            "endstop_z": data.get("endstop_z"),
        },
    ),
    FlashForgeSensorDescription(
        key="progress",
        name="Baskı İlerlemesi",
        icon="mdi:progress-clock",
        native_unit_of_measurement=PERCENTAGE,
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda data: data.get("progress"),
    ),
    FlashForgeSensorDescription(
        key="t0_current",
        name="Nozul Sıcaklığı",
        device_class=SensorDeviceClass.TEMPERATURE,
        native_unit_of_measurement=UnitOfTemperature.CELSIUS,
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda data: data.get("t0_current"),
        extra_attrs_fn=lambda data: {
            "hedef_sicaklik": data.get("t0_target")
        },
    ),
    FlashForgeSensorDescription(
        key="bed_current",
        name="Yatak Sıcaklığı",
        device_class=SensorDeviceClass.TEMPERATURE,
        native_unit_of_measurement=UnitOfTemperature.CELSIUS,
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda data: data.get("bed_current"),
        extra_attrs_fn=lambda data: {
            "hedef_sicaklik": data.get("bed_target")
        },
    ),
    FlashForgeSensorDescription(
        key="current_file",
        name="Aktif Dosya",
        icon="mdi:file-code-outline",
        value_fn=lambda data: data.get("current_file"),
    ),
    FlashForgeSensorDescription(
        key="current_layer",
        name="Mevcut Katman",
        icon="mdi:layers",
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda data: data.get("current_layer"),
    ),
    FlashForgeSensorDescription(
        key="total_layers",
        name="Toplam Katman",
        icon="mdi:layers-triple",
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda data: data.get("total_layers"),
    ),
    FlashForgeSensorDescription(
        key="layer",
        name="Katman Oranı",
        icon="mdi:layers-outline",
        value_fn=lambda data: data.get("layer"),
    ),
]


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """FlashForge sensörlerini tanımlar."""
    coordinator_info = hass.data[DOMAIN][entry.entry_id]
    coordinator = coordinator_info["coordinator"]

    entities: list[SensorEntity] = []

    # Standart sensörleri ekle
    for description in SENSOR_DESCRIPTIONS:
        entities.append(FlashForgeSensor(coordinator, entry, description))

    # Filament slot sensörlerini ekle (Varsayılan olarak 4 slot tanımlanıyor)
    for slot_id in range(1, 5):
        entities.append(FlashForgeFilamentSensor(coordinator, entry, slot_id))

    # Aktif filament slot sensörü
    entities.append(FlashForgeActiveSlotSensor(coordinator, entry))

    async_add_entities(entities)


class FlashForgeBaseEntity(CoordinatorEntity):
    """Ortak cihaz bilgilerini içeren temel varlık sınıfı."""

    def __init__(self, coordinator, entry: ConfigEntry) -> None:
        """Sınıfı başlatır."""
        super().__init__(coordinator)
        self.entry = entry
        self._host = entry.data[CONF_HOST]

    @property
    def device_info(self) -> DeviceInfo:
        """Cihaz bilgilerini döndürür."""
        return DeviceInfo(
            identifiers={(DOMAIN, self.entry.entry_id)},
            name="FlashForge AD5X",
            manufacturer="FlashForge",
            model="AD5X Series",
            configuration_url=f"http://{self._host}",
        )


class FlashForgeSensor(FlashForgeBaseEntity, SensorEntity):
    """FlashForge genel sensör sınıfı."""

    entity_description: FlashForgeSensorDescription

    def __init__(
        self,
        coordinator,
        entry: ConfigEntry,
        description: FlashForgeSensorDescription,
    ) -> None:
        """Sensörü başlatır."""
        super().__init__(coordinator, entry)
        self.entity_description = description
        self._attr_unique_id = f"{entry.entry_id}_{description.key}"
        self._attr_name = f"FlashForge {description.name}"

    @property
    def native_value(self) -> Any:
        """Sensör değerini döndürür."""
        if not self.coordinator.data:
            return None
        return self.entity_description.value_fn(self.coordinator.data)

    @property
    def extra_state_attributes(self) -> dict[str, Any] | None:
        """Ek öznitelikleri döndürür."""
        if not self.coordinator.data or not self.entity_description.extra_attrs_fn:
            return None
        return self.entity_description.extra_attrs_fn(self.coordinator.data)


class FlashForgeFilamentSensor(FlashForgeBaseEntity, SensorEntity):
    """IFS Filament Slot sensörü."""

    def __init__(self, coordinator, entry: ConfigEntry, slot_id: int) -> None:
        """Slot sensörünü başlatır."""
        super().__init__(coordinator, entry)
        self.slot_id = slot_id
        self._attr_unique_id = f"{entry.entry_id}_filament_slot_{slot_id}"
        self._attr_name = f"FlashForge Filament Slot {slot_id}"
        self._attr_icon = "mdi:printer-3d-nozzle"

    @property
    def native_value(self) -> str | None:
        """Filament tipini/ismini döndürür."""
        if not self.coordinator.data:
            return "Bilinmiyor"
        
        filament_info = self.coordinator.data.get("filament_info")
        if not filament_info:
            return "Bağlantı Yok / Pasif"

        slots = filament_info.get("slotInfos") or []
        for slot in slots:
            if slot.get("slotId") == self.slot_id:
                if slot.get("hasFilament"):
                    return slot.get("materialName") or "Bilinmeyen Filament"
                return "Boş"
        return "Boş"

    @property
    def extra_state_attributes(self) -> dict[str, Any] | None:
        """Slot detaylarını öznitelik olarak döndürür."""
        if not self.coordinator.data:
            return None

        filament_info = self.coordinator.data.get("filament_info")
        if not filament_info:
            return None

        slots = filament_info.get("slotInfos") or []
        active_slot_id = filament_info.get("currentLoadSlot")
        if active_slot_id is None:
            active_slot_id = filament_info.get("currentSlot")

        for slot in slots:
            if slot.get("slotId") == self.slot_id:
                return {
                    "slot_id": self.slot_id,
                    "has_filament": slot.get("hasFilament", False),
                    "renk": slot.get("materialColor"),
                    "aktif_yuklu": (self.slot_id == active_slot_id),
                }
        return None


class FlashForgeActiveSlotSensor(FlashForgeBaseEntity, SensorEntity):
    """Aktif yüklenmiş filament slot sensörü."""

    def __init__(self, coordinator, entry: ConfigEntry) -> None:
        """Aktif slot sensörünü başlatır."""
        super().__init__(coordinator, entry)
        self._attr_unique_id = f"{entry.entry_id}_active_filament_slot"
        self._attr_name = "FlashForge Aktif Filament Slotu"
        self._attr_icon = "mdi:arrow-decision-auto"

    @property
    def native_value(self) -> str | int | None:
        """Aktif slot ID'sini veya durumunu döndürür."""
        if not self.coordinator.data:
            return None

        filament_info = self.coordinator.data.get("filament_info")
        if not filament_info:
            return "Pasif"

        active_slot_id = filament_info.get("currentLoadSlot")
        if active_slot_id is None:
            active_slot_id = filament_info.get("currentSlot")

        if active_slot_id is not None and active_slot_id > 0:
            return active_slot_id
        return "Yok"
