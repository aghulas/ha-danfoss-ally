"""Checks that the platform modules import (HA dependencies present)."""

import importlib

import pytest


@pytest.mark.parametrize(
    "module",
    [
        "custom_components.danfoss_ally_cloud",
        "custom_components.danfoss_ally_cloud.climate",
        "custom_components.danfoss_ally_cloud.sensor",
        "custom_components.danfoss_ally_cloud.binary_sensor",
        "custom_components.danfoss_ally_cloud.config_flow",
        "custom_components.danfoss_ally_cloud.coordinator",
        "custom_components.danfoss_ally_cloud.diagnostics",
        "custom_components.danfoss_ally_cloud.entity",
    ],
)
def test_import(module):
    assert importlib.import_module(module) is not None
