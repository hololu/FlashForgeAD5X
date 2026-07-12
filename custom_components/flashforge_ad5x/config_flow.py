import voluptuous as vol
import logging
from homeassistant import config_entries
from homeassistant.const import CONF_HOST, CONF_PORT

from .const import DOMAIN, CONF_SERIAL, CONF_CHECK_CODE, DEFAULT_PORT
from .api import FlashForgeAPI

_LOGGER = logging.getLogger(__name__)

class FlashForgeConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """FlashForge AD5X entegrasyonu için yapılandırma akışını yönetir."""

    VERSION = 1

    async def async_step_user(self, user_input=None):
        """İlk kurulum adımını yönetir."""
        errors = {}

        if user_input is not None:
            host = user_input[CONF_HOST]
            port = user_input[CONF_PORT]
            serial = user_input.get(CONF_SERIAL, "")
            check_code = user_input.get(CONF_CHECK_CODE, "")

            # Bağlantıyı test et
            api = FlashForgeAPI(host, port, serial, check_code)
            res = await api.async_send_command("~M119\r\n")
            if "ERR:" in res:
                errors["base"] = "cannot_connect"
            else:
                return self.async_create_entry(
                    title=f"FlashForge ({host})",
                    data=user_input
                )

        schema = vol.Schema({
            vol.Required(CONF_HOST): str,
            vol.Required(CONF_PORT, default=DEFAULT_PORT): int,
            vol.Optional(CONF_SERIAL, default=""): str,
            vol.Optional(CONF_CHECK_CODE, default=""): str,
        })

        return self.async_show_form(
            step_id="user",
            data_schema=schema,
            errors=errors
        )
