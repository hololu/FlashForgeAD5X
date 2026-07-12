import logging
from datetime import timedelta
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_HOST, CONF_PORT, Platform
from homeassistant.core import HomeAssistant
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .const import DOMAIN, CONF_SERIAL, CONF_CHECK_CODE, DEFAULT_SCAN_INTERVAL
from .api import FlashForgeAPI

_LOGGER = logging.getLogger(__name__)

PLATFORMS = [Platform.SENSOR, Platform.BUTTON, Platform.LIGHT]

async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Config entry üzerinden FlashForge AD5X kurulumunu yapar."""
    host = entry.data[CONF_HOST]
    port = entry.data[CONF_PORT]
    serial = entry.data.get(CONF_SERIAL, "")
    check_code = entry.data.get(CONF_CHECK_CODE, "")

    session = async_get_clientsession(hass)
    api = FlashForgeAPI(host, port, serial, check_code, session)

    async def async_update_data():
        """FlashForge API'sinden veri çeker."""
        try:
            data = await api.async_get_data()
            # Eğer çevrimdışıysa hata fırlatarak HA'in durumu güncellemesini sağlıyoruz
            if not data.get("online"):
                # Tamamen hata fırlatmak yerine çevrimdışı veriyi dönebiliriz.
                # Böylece sensörler durmaz, "Çevrimdışı" durumunu gösterebilirler.
                return data
            return data
        except Exception as err:
            raise UpdateFailed(f"Yazıcıyla iletişim kurulurken hata oluştu: {err}")

    coordinator = DataUpdateCoordinator(
        hass,
        _LOGGER,
        name=DOMAIN,
        update_method=async_update_data,
        update_interval=timedelta(seconds=DEFAULT_SCAN_INTERVAL),
    )

    # İlk verileri çek
    await coordinator.async_config_entry_first_refresh()

    hass.data.setdefault(DOMAIN, {})
    hass.data[DOMAIN][entry.entry_id] = {
        "coordinator": coordinator,
        "api": api
    }

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

    return True

async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Kurulum kaydını kaldırır."""
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unload_ok:
        hass.data[DOMAIN].pop(entry.entry_id)

    return unload_ok
