"""Quirk v2 for Aqara Door and Window Sensor E1 lumi.magnet.acn001 / MCCGQ14LM."""

from typing import Any, Final

from zhaquirks import CustomCluster, LocalDataCluster
from zhaquirks.builder import (
    PERCENTAGE,
    BinarySensorDeviceClass,
    EntityType,
    QuirkBuilder,
    SensorDeviceClass,
    SensorStateClass,
    UnitOfElectricPotential,
)
from zigpy import types as t
from zigpy.zcl import (
    AttributeReportedEvent,
    ClusterType,
    foundation,
)
from zigpy.zcl.clusters.general import Ota, PowerConfiguration
from zigpy.zcl.clusters.security import IasZone
from zigpy.zcl.foundation import BaseAttributeDefs, ZCLAttributeDef

AQARA_MFG_CODE: Final = 0x115F


class AqaraE1LifelineCluster(LocalDataCluster):
    """Values decoded from the Aqara lifeline."""

    cluster_id = 0xFC02
    ep_attribute = "aqara_e1_lifeline"

    BATTERY_HYSTERESIS_MV: Final = 10

    BATTERY_PERCENTAGE_THRESHOLDS_MV: Final = (
        (2870, 100),
        (2840, 50),
        (2810, 25),
        (2790, 5),
    )

    class AttributeDefs(BaseAttributeDefs):
        """Attribute definitions."""

        battery_percentage: Final = ZCLAttributeDef(
            id=0x0000,
            type=t.uint8_t,
            manufacturer_code=None,
        )
        battery_voltage: Final = ZCLAttributeDef(
            id=0x0001,
            type=t.Single,
            manufacturer_code=None,
        )

    _VALID_ATTRIBUTES: set[int] = {
        AttributeDefs.battery_percentage.id,
        AttributeDefs.battery_voltage.id,
    }

    def update_from_voltage(self, voltage_mv: int) -> None:
        """Update battery voltage and estimated battery percentage."""
        self.update_attribute(
            self.AttributeDefs.battery_voltage.id,
            voltage_mv / 1000,
        )
        self.update_attribute(
            self.AttributeDefs.battery_percentage.id,
            self._battery_percentage_with_hysteresis(voltage_mv),
        )

    def _battery_percentage_from_voltage(self, voltage_mv: int) -> int:
        """Estimate coarse CR1632 battery percentage from voltage."""
        for threshold_mv, battery_percentage in self.BATTERY_PERCENTAGE_THRESHOLDS_MV:
            if voltage_mv >= threshold_mv:
                return battery_percentage

        return 0

    def _battery_percentage_with_hysteresis(self, voltage_mv: int) -> int:
        """Estimate coarse battery percentage with two-way hysteresis."""
        new_percentage = self._battery_percentage_from_voltage(voltage_mv)
        cached_percentage = self.get(
            self.AttributeDefs.battery_percentage.id,
        )

        if cached_percentage is None or new_percentage == cached_percentage:
            return new_percentage

        if new_percentage < cached_percentage:
            voltage_mv += self.BATTERY_HYSTERESIS_MV
        else:
            voltage_mv -= self.BATTERY_HYSTERESIS_MV

        return self._battery_percentage_from_voltage(voltage_mv)


class AqaraE1ManufacturerCluster(CustomCluster):
    """Aqara Door and Window Sensor E1 manufacturer cluster."""

    cluster_id = 0xFCC0
    ep_attribute = "aqara_e1_manufacturer"

    BATTERY_VOLTAGE_TAG: Final = 0x01

    class AttributeDefs(BaseAttributeDefs):
        """Attribute definitions."""

        aqara_lifeline: Final = ZCLAttributeDef(
            id=0x00F7,
            type=t.LVBytes,
            access="rp",
            manufacturer_code=AQARA_MFG_CODE,
        )

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        """Initialize the Aqara manufacturer cluster."""
        super().__init__(*args, **kwargs)
        self.on_event(
            AttributeReportedEvent.event_type,
            self._handle_attribute_event,
        )

    def _handle_attribute_event(
        self,
        event: AttributeReportedEvent,
    ) -> None:
        """Handle the Aqara lifeline attribute."""
        if event.attribute_id == self.AttributeDefs.aqara_lifeline.id:
            values = self._parse_lifeline_report(event.value)
            lifeline_cluster = self.endpoint.aqara_e1_lifeline

            if self.BATTERY_VOLTAGE_TAG in values:
                lifeline_cluster.update_from_voltage(values[self.BATTERY_VOLTAGE_TAG])

    def _parse_lifeline_report(self, data: bytes) -> dict[int, Any]:
        """Parse the Aqara lifeline report."""
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


(
    QuirkBuilder("LUMI", "lumi.magnet.acn001")
    .friendly_name(manufacturer="Aqara", model="Door and Window Sensor E1")
    .replaces(AqaraE1ManufacturerCluster)
    .removes(PowerConfiguration.cluster_id)
    .adds(AqaraE1LifelineCluster)
    .removes(
        Ota.cluster_id,
        cluster_type=ClusterType.Client,
    )
    .sensor(
        attribute_name="battery_percentage",
        cluster_id=AqaraE1LifelineCluster.cluster_id,
        entity_type=EntityType.DIAGNOSTIC,
        device_class=SensorDeviceClass.BATTERY,
        state_class=SensorStateClass.MEASUREMENT,
        unit=PERCENTAGE,
        suggested_display_precision=0,
        translation_key="battery",
        fallback_name="Battery",
    )
    .sensor(
        attribute_name="battery_voltage",
        cluster_id=AqaraE1LifelineCluster.cluster_id,
        entity_type=EntityType.DIAGNOSTIC,
        device_class=SensorDeviceClass.VOLTAGE,
        state_class=SensorStateClass.MEASUREMENT,
        unit=UnitOfElectricPotential.VOLT,
        initially_disabled=True,
        suggested_display_precision=3,
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
