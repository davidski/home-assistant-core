"""Configflow for the emoncms integration."""

from typing import Any, override

import probatio
from pyemoncms import EmoncmsClient

from homeassistant.config_entries import (
    ConfigFlow,
    ConfigFlowResult,
    OptionsFlowWithReload,
)
from homeassistant.const import CONF_API_KEY, CONF_URL
from homeassistant.core import callback
from homeassistant.data_entry_flow import section
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.selector import (
    NumberSelector,
    NumberSelectorConfig,
    NumberSelectorMode,
    ObjectSelector,
    ObjectSelectorConfig,
    ObjectSelectorField,
    SelectSelector,
    SelectSelectorConfig,
    SelectSelectorMode,
    selector,
)

from .const import (
    CONF_DEVICE,
    CONF_MESSAGE,
    CONF_OFFLINE_DETECTION,
    CONF_ONLY_INCLUDE_FEEDID,
    CONF_STALE_AFTER,
    CONF_STALE_AFTER_OVERRIDES,
    CONF_SUCCESS,
    DEFAULT_STALE_AFTER,
    DOMAIN,
    FEED_ID,
    FEED_NAME,
    FEED_TAG,
    SYNC_MODE,
    SYNC_MODE_AUTO,
    SYNC_MODE_MANUAL,
)
from .coordinator import EmonCMSConfigEntry


def get_options(feeds: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Build the selector options with the feed list."""
    return [
        {
            "value": feed[FEED_ID],
            "label": f"{feed[FEED_ID]}|{feed[FEED_TAG]}|{feed[FEED_NAME]}",
        }
        for feed in feeds
    ]


def sensor_name(url: str) -> str:
    """Return sensor name."""
    sensorip = url.rsplit("//", maxsplit=1)[-1]
    return f"emoncms@{sensorip}"


async def get_feed_list(
    emoncms_client: EmoncmsClient,
) -> dict[str, Any]:
    """Check connection to emoncms and return feed list if successful."""
    return await emoncms_client.async_request("/feed/list.json")


class EmoncmsConfigFlow(ConfigFlow, domain=DOMAIN):
    """emoncms integration UI config flow."""

    url: str
    api_key: str
    include_only_feeds: list | None = None
    dropdown: dict = {}

    @staticmethod
    @callback
    @override
    def async_get_options_flow(
        config_entry: EmonCMSConfigEntry,
    ) -> EmoncmsOptionsFlow:
        """Get the options flow for this handler."""
        return EmoncmsOptionsFlow(config_entry)

    @override
    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Initiate a flow via the UI."""
        errors: dict[str, str] = {}
        description_placeholders = {}

        if user_input is not None:
            self.url = user_input[CONF_URL]
            self.api_key = user_input[CONF_API_KEY]
            self._async_abort_entries_match(
                {
                    CONF_API_KEY: self.api_key,
                    CONF_URL: self.url,
                }
            )
            emoncms_client = EmoncmsClient(
                self.url, self.api_key, session=async_get_clientsession(self.hass)
            )
            result = await get_feed_list(emoncms_client)
            if not result[CONF_SUCCESS]:
                errors["base"] = "api_error"
                description_placeholders = {"details": result[CONF_MESSAGE]}
            else:
                self.include_only_feeds = user_input.get(CONF_ONLY_INCLUDE_FEEDID)
                await self.async_set_unique_id(await emoncms_client.async_get_uuid())
                self._abort_if_unique_id_configured()
                options = get_options(result[CONF_MESSAGE])
                self.dropdown = {
                    "options": options,
                    "mode": "dropdown",
                    "multiple": True,
                }
                if user_input.get(SYNC_MODE) == SYNC_MODE_AUTO:
                    return self.async_create_entry(
                        title=sensor_name(self.url),
                        data={
                            CONF_URL: self.url,
                            CONF_API_KEY: self.api_key,
                            CONF_ONLY_INCLUDE_FEEDID: [
                                feed[FEED_ID] for feed in result[CONF_MESSAGE]
                            ],
                        },
                    )
                return await self.async_step_choose_feeds()
        return self.async_show_form(
            step_id="user",
            data_schema=self.add_suggested_values_to_schema(
                probatio.Schema(
                    {
                        probatio.Required(CONF_URL): str,
                        probatio.Required(probatio.Secret(CONF_API_KEY)): str,
                        probatio.Required(
                            SYNC_MODE, default=SYNC_MODE_MANUAL
                        ): SelectSelector(
                            SelectSelectorConfig(
                                options=[SYNC_MODE_MANUAL, SYNC_MODE_AUTO],
                                mode=SelectSelectorMode.DROPDOWN,
                                translation_key=SYNC_MODE,
                            )
                        ),
                    }
                ),
                user_input,
            ),
            errors=errors,
            description_placeholders=description_placeholders,
        )

    async def async_step_choose_feeds(
        self,
        user_input: dict[str, Any] | None = None,
    ) -> ConfigFlowResult:
        """Choose feeds to import."""
        errors: dict[str, str] = {}
        include_only_feeds: list = []
        if user_input or self.include_only_feeds is not None:
            if self.include_only_feeds is not None:
                include_only_feeds = self.include_only_feeds
            elif user_input:
                include_only_feeds = user_input[CONF_ONLY_INCLUDE_FEEDID]
            return self.async_create_entry(
                title=sensor_name(self.url),
                data={
                    CONF_URL: self.url,
                    CONF_API_KEY: self.api_key,
                    CONF_ONLY_INCLUDE_FEEDID: include_only_feeds,
                },
            )
        return self.async_show_form(
            step_id="choose_feeds",
            data_schema=probatio.Schema(
                {
                    probatio.Required(
                        CONF_ONLY_INCLUDE_FEEDID,
                        default=include_only_feeds,
                    ): selector({"select": self.dropdown}),
                }
            ),
            errors=errors,
        )

    async def async_step_reconfigure(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Reconfigure the entry."""
        errors: dict[str, str] = {}
        description_placeholders = {}
        reconfig_entry = self._get_reconfigure_entry()
        if user_input is not None:
            url = user_input[CONF_URL]
            api_key = user_input[CONF_API_KEY]
            emoncms_client = EmoncmsClient(
                url, api_key, session=async_get_clientsession(self.hass)
            )
            result = await get_feed_list(emoncms_client)
            if not result[CONF_SUCCESS]:
                errors["base"] = "api_error"
                description_placeholders = {"details": result[CONF_MESSAGE]}
            else:
                await self.async_set_unique_id(await emoncms_client.async_get_uuid())
                self._abort_if_unique_id_mismatch()
                return self.async_update_reload_and_abort(
                    reconfig_entry,
                    title=sensor_name(url),
                    data=user_input,
                    reload_even_if_entry_is_unchanged=False,
                )
        return self.async_show_form(
            step_id="reconfigure",
            data_schema=self.add_suggested_values_to_schema(
                probatio.Schema(
                    {
                        probatio.Required(CONF_URL): str,
                        probatio.Required(probatio.Secret(CONF_API_KEY)): str,
                    }
                ),
                user_input or reconfig_entry.data,
            ),
            errors=errors,
            description_placeholders=description_placeholders,
        )


class EmoncmsOptionsFlow(OptionsFlowWithReload):
    """Emoncms Options flow handler."""

    def __init__(self, config_entry: EmonCMSConfigEntry) -> None:
        """Initialize emoncms options flow."""
        self._url = config_entry.data[CONF_URL]
        self._api_key = config_entry.data[CONF_API_KEY]

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Manage the options."""
        errors: dict[str, str] = {}
        description_placeholders = {}
        include_only_feeds = self.config_entry.options.get(
            CONF_ONLY_INCLUDE_FEEDID,
            self.config_entry.data.get(CONF_ONLY_INCLUDE_FEEDID, []),
        )
        options: list = include_only_feeds
        emoncms_client = EmoncmsClient(
            self._url,
            self._api_key,
            session=async_get_clientsession(self.hass),
        )
        overrides = self.config_entry.options.get(CONF_STALE_AFTER_OVERRIDES, [])
        tags = {override[CONF_DEVICE] for override in overrides}
        result = await get_feed_list(emoncms_client)
        if not result[CONF_SUCCESS]:
            errors["base"] = "api_error"
            description_placeholders = {"details": result[CONF_MESSAGE]}
        else:
            options = get_options(result[CONF_MESSAGE])
            tags.update(
                feed[FEED_TAG] for feed in result[CONF_MESSAGE] if feed[FEED_TAG]
            )
        dropdown = {"options": options, "mode": "dropdown", "multiple": True}
        stale_after = self.config_entry.options.get(
            CONF_STALE_AFTER, DEFAULT_STALE_AFTER
        )
        if user_input:
            offline = user_input.get(CONF_OFFLINE_DETECTION, {})
            return self.async_create_entry(
                data={
                    CONF_ONLY_INCLUDE_FEEDID: user_input[CONF_ONLY_INCLUDE_FEEDID],
                    CONF_STALE_AFTER: int(offline.get(CONF_STALE_AFTER, stale_after)),
                    CONF_STALE_AFTER_OVERRIDES: [
                        {
                            CONF_DEVICE: override[CONF_DEVICE],
                            CONF_STALE_AFTER: int(override[CONF_STALE_AFTER]),
                        }
                        for override in offline.get(
                            CONF_STALE_AFTER_OVERRIDES, overrides
                        )
                    ],
                },
            )

        return self.async_show_form(
            step_id="init",
            data_schema=probatio.Schema(
                {
                    probatio.Required(
                        CONF_ONLY_INCLUDE_FEEDID, default=include_only_feeds
                    ): selector({"select": dropdown}),
                    probatio.Optional(CONF_OFFLINE_DETECTION): section(
                        probatio.Schema(
                            {
                                probatio.Required(
                                    CONF_STALE_AFTER, default=stale_after
                                ): NumberSelector(
                                    NumberSelectorConfig(
                                        min=1,
                                        max=1440,
                                        step=1,
                                        unit_of_measurement="min",
                                        mode=NumberSelectorMode.BOX,
                                    )
                                ),
                                probatio.Optional(
                                    CONF_STALE_AFTER_OVERRIDES, default=overrides
                                ): ObjectSelector(
                                    ObjectSelectorConfig(
                                        multiple=True,
                                        label_field=CONF_DEVICE,
                                        description_field=CONF_STALE_AFTER,
                                        translation_key=CONF_STALE_AFTER_OVERRIDES,
                                        fields={
                                            CONF_DEVICE: ObjectSelectorField(
                                                required=True,
                                                selector=SelectSelector(
                                                    SelectSelectorConfig(
                                                        options=sorted(tags),
                                                        mode=SelectSelectorMode.DROPDOWN,
                                                    )
                                                ),
                                            ),
                                            CONF_STALE_AFTER: ObjectSelectorField(
                                                required=True,
                                                default=stale_after,
                                                selector=NumberSelector(
                                                    NumberSelectorConfig(
                                                        min=1,
                                                        max=1440,
                                                        step=1,
                                                        unit_of_measurement="min",
                                                        mode=NumberSelectorMode.BOX,
                                                    )
                                                ),
                                            ),
                                        },
                                    )
                                ),
                            }
                        ),
                        {"collapsed": False},
                    ),
                }
            ),
            errors=errors,
            description_placeholders=description_placeholders,
        )
