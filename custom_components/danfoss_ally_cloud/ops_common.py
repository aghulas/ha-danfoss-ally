"""Shared operation primitives: errors, admin check, target resolution, and refresh helpers."""

from __future__ import annotations

import re
from typing import TYPE_CHECKING, Any

from homeassistant.core import HomeAssistant

from .api import write_allowed
from .api.client import CloudError

if TYPE_CHECKING:
    from .coordinator import DanfossCoordinator

_HHMM = re.compile(r"^([01]\d|2[0-3]):[0-5]\d$")


class OperationError(Exception):
    """Error carrying a stable contract code (§5.4), translated by the wrappers."""

    def __init__(
        self,
        code: str,
        message: str | None = None,
        errors: list[dict] | None = None,
        day: str | None = None,
    ) -> None:
        self.code = code
        self.errors = errors
        self.day = day
        super().__init__(message or code)


async def ensure_admin(
    hass: HomeAssistant, user_id: str | None, *, allow_internal: bool = True
) -> None:
    """Refuse a non-admin user (contract §5.2). None = internal call, allowed by default.

    ``allow_internal=False`` additionally refuses a user-less call (``user_id is None``): used by
    ``disconnect_head``, the most destructive write, so that an unattended automation/script cannot
    unbind a head without a real administrator in context (opt-in + confirm are not enough there).
    """
    if user_id is None:
        if allow_internal:
            return
        raise OperationError("not_admin", "this action requires an administrator user")
    user = await hass.auth.async_get_user(user_id)
    if user is None or not user.is_admin:
        raise OperationError("not_admin", "write reserved for administrators")


def _require_verified_head(
    coordinator: DanfossCoordinator, target: dict, *, not_found_code: str = "unknown_head"
):
    """Resolve a ``{type:"device", id}`` target to a known, write-verified head, or raise.

    The target-safety sequence shared by writes that address a single head (contract write-safety):
    the target must be ``type=device``, a known head, of a write-verified product. The
    ``not_found_code`` arg lets each caller keep its own stable code for an unknown target
    (``unknown_head`` for the head writes, ``unknown_target`` for the local tunnel) — observable
    behaviour unchanged. Returns the resolved ``DanfossDevice``.
    """
    if target.get("type") != "device":
        raise OperationError("device_only", "this write targets a head (type=device)")
    dev = coordinator.data.get(str(target.get("id")))
    if dev is None or not dev.is_head:
        raise OperationError(not_found_code, f"head not found: {target.get('id')}")
    if not write_allowed(dev):
        raise OperationError("unverified_product", "write not verified for this product")
    return dev


async def _run_cloud_write(func, *args) -> Any:
    try:
        return await func(*args)
    except CloudError as err:
        raise OperationError("cloud_refused", str(err)) from err


async def _refresh_after_structural_write(coordinator) -> None:
    """Make a structural change visible now: drop the topology cache, then refresh.

    ``async_request_refresh`` alone re-reads device state but keeps the hourly-cached room topology,
    so a new/changed/removed room would stay invisible to ``get_rooms`` and the resolver until the
    next poll. Invalidating the topology first forces it to be re-read on this refresh.
    """
    coordinator.invalidate_topology()
    await coordinator.async_request_refresh()


def _room_target(target: dict) -> str:
    if target.get("type") != "room":
        raise OperationError("unknown_room", "this action targets a room")
    return str(target.get("id"))
