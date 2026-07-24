"""Quirk v2 for Aqara Door and Window Sensor E1 lumi.magnet.acn001 / MCCGQ14LM."""

from typing import Any, Final

from zhaquirks import CustomCluster, LocalDataCluster
from zhaquirks.builder import (
    BinarySensorDeviceClass,
    EntityType,
    QuirkBuilder,
    SensorDeviceClass,
    SensorStateClass,
    UnitOfElectricPotential,
)
from zhaquirks.const import BatterySize
from zigpy import types as t
from zigpy.zcl import AttributeReportedEvent, ClusterType, foundation
from zigpy.zcl.clusters.general import Ota, PowerConfiguration
from zigpy.zcl.clusters.security import IasZone
from zigpy.zcl.foundation import BaseAttributeDefs, ZCLAttributeDef

AQARA_MFG_CODE: Final = 0x115F


class AqaraE1ManufacturerCluster(CustomCluster):
    """Aqara Door and Window Sensor E1 manufacturer cluster."""

    cluster_id = 0xFCC0
    ep_attribute = "aqara_e1_manufacturer"

    BATTERY_VOLTAGE_TAG: Final = 0x01

    class AttributeDefs(BaseAttributeDefs):
        """Aqara E1 manufacturer attributes."""

        aqara_lifeline: Final = ZCLAttributeDef(
            id=0x00F7,
            type=t.LVBytes,
            access="rp",
            manufacturer_code=AQARA_MFG_CODE,
        )

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        """Initialize manufacturer cluster and subscribe to lifeline reports."""
        super().__init__(*args, **kwargs)
        self.on_event(AttributeReportedEvent.event_type, self._handle_attribute_event)

    def _handle_attribute_event(self, event: AttributeReportedEvent) -> None:
        """Handle Aqara lifeline reports."""
        if event.attribute_id == self.AttributeDefs.aqara_lifeline.id:
            values = self._parse_lifeline_report(event.value)

            if self.BATTERY_VOLTAGE_TAG in values:
                self.endpoint.power.update_from_voltage(
                    values[self.BATTERY_VOLTAGE_TAG]
                )

    def _parse_lifeline_report(self, data: bytes) -> dict[int, Any]:
        """Parse Aqara E1 lifeline report."""
        values: dict[int, Any] = {}

        while len(data) >= 2:
            tag = data[0]

            try:
                typed_value, data = foundation.TypeValue.deserialize(data[1:])
            except ValueError:
                self.debug(
                    "Failed to deserialize Aqara E1 lifeline tag 0x%02X from %r",
                    tag,
                    data,
                )
                return values

            values[tag] = typed_value.value

        return values


class AqaraE1PowerConfigurationCluster(LocalDataCluster, PowerConfiguration):
    """Power cluster with coarse voltage-based battery percentage estimation."""

    BATTERY_VOLTAGE_ATTR_ID: Final = PowerConfiguration.AttributeDefs.battery_voltage.id
    BATTERY_PERCENTAGE_REMAINING_ATTR_ID: Final = (
        PowerConfiguration.AttributeDefs.battery_percentage_remaining.id
    )
    BATTERY_QUANTITY_ATTR_ID: Final = (
        PowerConfiguration.AttributeDefs.battery_quantity.id
    )
    BATTERY_SIZE_ATTR_ID: Final = PowerConfiguration.AttributeDefs.battery_size.id

    BATTERY_HYSTERESIS_MV: Final = 10

    BATTERY_PERCENTAGE_THRESHOLDS_MV: Final = (
        (2870, 200),
        (2840, 100),
        (2810, 50),
        (2790, 10),
    )

    _VALID_ATTRIBUTES: set[int] = {
        BATTERY_VOLTAGE_ATTR_ID,
        BATTERY_PERCENTAGE_REMAINING_ATTR_ID,
    }

    _CONSTANT_ATTRIBUTES: dict[int, Any] = {
        BATTERY_QUANTITY_ATTR_ID: 1,
        BATTERY_SIZE_ATTR_ID: BatterySize.CR1632,
    }

    def update_from_voltage(self, voltage_mv: int) -> None:
        """Update battery voltage and estimated battery percentage."""
        self._update_attribute(
            self.BATTERY_VOLTAGE_ATTR_ID,
            round(voltage_mv / 100, 1),
        )
        self._update_attribute(
            self.BATTERY_PERCENTAGE_REMAINING_ATTR_ID,
            self._battery_percentage_with_hysteresis(voltage_mv),
        )

    def _battery_percentage_from_voltage(self, voltage_mv: int) -> int:
        """Estimate coarse CR battery percentage from voltage."""
        for threshold_mv, battery_percentage in self.BATTERY_PERCENTAGE_THRESHOLDS_MV:
            if voltage_mv >= threshold_mv:
                return battery_percentage

        return 0

    def _battery_percentage_with_hysteresis(self, voltage_mv: int) -> int:
        """Estimate coarse CR battery percentage with two-way hysteresis."""
        new_percentage = self._battery_percentage_from_voltage(voltage_mv)

        cached_percentage = self.get(self.BATTERY_PERCENTAGE_REMAINING_ATTR_ID)
        if cached_percentage is None or new_percentage == cached_percentage:
            return new_percentage

        if new_percentage < cached_percentage:
            voltage_mv += self.BATTERY_HYSTERESIS_MV
        else:
            voltage_mv -= self.BATTERY_HYSTERESIS_MV

        return self._battery_percentage_from_voltage(voltage_mv)


(
    QuirkBuilder("LUMI", "lumi.magnet.acn001")
    .friendly_name(manufacturer="Aqara", model="Door and Window Sensor E1")
    .replaces(AqaraE1PowerConfigurationCluster, endpoint_id=1)
    .replaces(AqaraE1ManufacturerCluster, endpoint_id=1)
    .removes(Ota.cluster_id, endpoint_id=1, cluster_type=ClusterType.Client)
    .sensor(
        attribute_name="battery_voltage",
        cluster_id=AqaraE1PowerConfigurationCluster.cluster_id,
        device_class=SensorDeviceClass.VOLTAGE,
        state_class=SensorStateClass.MEASUREMENT,
        unit=UnitOfElectricPotential.VOLT,
        multiplier=0.1,
        suggested_display_precision=2,
        entity_type=EntityType.DIAGNOSTIC,
        initially_disabled=True,
        translation_key="battery_voltage",
        fallback_name="Battery voltage",
    )
    .binary_sensor(
        attribute_name=IasZone.AttributeDefs.zone_status.name,
        cluster_id=IasZone.cluster_id,
        device_class=BinarySensorDeviceClass.BATTERY,
        attribute_converter=lambda value: bool(value & IasZone.ZoneStatus.Battery),
        entity_type=EntityType.DIAGNOSTIC,
        fallback_name="Battery",
    )
    .add_to_registry()
)
