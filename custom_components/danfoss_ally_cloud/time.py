"""Time entity under supervised trial: the valve exercise time of a head (attribute 0x4011).

Zigbee2MQTT ``trigger_time`` of the valve exercise. Written through the local tunnel with the day
the head already has (read from the head first), by the descale service's path, and read back
through the tunnel (``local_write``): the state is what the head says, never the value written.
Exists only while the ``valve_exercise`` local-tunnel trial is armed for the designated head.
"""

from __future__ import annotations

from datetime import time

from homeassistant.components.time import TimeEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DATA_COORDINATOR, DATA_LOCAL, DOMAIN
from .coordinator import DanfossCoordinator, DanfossLocalCoordinator
from .entity import DanfossLocalTrialEntity, remove_registry_entries
from .local_write import async_local_write_valve_exercise, local_trial_split

VALVE_EXERCISE_TIME_UID = "valve_exercise_time"


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    data = hass.data[DOMAIN][entry.entry_id]
    coordinator: DanfossCoordinator = data[DATA_COORDINATOR]
    local: DanfossLocalCoordinator | None = data.get(DATA_LOCAL)
    armed, closed = local_trial_split(
        data, coordinator.data.values(), local, "valve_exercise", VALVE_EXERCISE_TIME_UID
    )
    remove_registry_entries(hass, entry, "time", closed)
    if local is not None:
        async_add_entities(DanfossValveExerciseTime(local, coordinator, dev_id) for dev_id in armed)


class DanfossValveExerciseTime(DanfossLocalTrialEntity, TimeEntity):
    """Valve exercise time (Danfoss attribute 0x4011), local-tunnel write under supervised trial."""

    _attr_translation_key = "valve_exercise_time"
    _attribute = "descale_time"

    def __init__(
        self, local: DanfossLocalCoordinator, cloud: DanfossCoordinator, device_id: str
    ) -> None:
        super().__init__(local, cloud, device_id, VALVE_EXERCISE_TIME_UID)

    @property
    def native_value(self) -> time | None:
        value = self._value(self._attribute)
        if not isinstance(value, str):
            return None
        try:
            hh, mm = (int(x) for x in value.split(":"))
            return time(hh, mm)
        except ValueError:
            return None

    async def async_set_value(self, value: time) -> None:
        head = self._head
        if head is None:
            raise HomeAssistantError("the local tunnel cannot reach this head")
        await self._async_run_trial(
            async_local_write_valve_exercise(
                self.hass, self.coordinator, head, hour=f"{value.hour:02d}:{value.minute:02d}"
            )
        )
