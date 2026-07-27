"""Quirk v2 for Aqara Motion Sensor P1 lumi.motion.ac02 / RTCGQ14LM."""

import asyncio
from typing import Any, Final

from zhaquirks import CustomCluster, LocalDataCluster
from zhaquirks.builder import (
    PERCENTAGE,
    EntityType,
    NumberDeviceClass,
    QuirkBuilder,
    SensorDeviceClass,
    SensorStateClass,
    UnitOfElectricPotential,
    UnitOfTime,
)
from zigpy import types as t
from zigpy.zcl import (
    AttributeReportedEvent,
    ClusterType,
    foundation,
)
from zigpy.zcl.clusters.general import PowerConfiguration
from zigpy.zcl.clusters.measurement import OccupancySensing
from zigpy.zcl.foundation import BaseAttributeDefs, DataTypeId, ZCLAttributeDef

AQARA_MFG_CODE: Final = 0x115F


class MotionSensitivity(t.enum8):
    """Aqara Motion Sensor P1 motion sensitivity."""

    Low = 0x01
    Medium = 0x02
    High = 0x03


class AqaraP1ManufacturerCluster(CustomCluster):
    """Aqara Motion Sensor P1 manufacturer cluster."""

    cluster_id = 0xFCC0
    ep_attribute = "aqara_p1_manufacturer"

    BATTERY_VOLTAGE_TAG: Final = 0x01
    ILLUMINANCE_TAG: Final = 0x65

    class AttributeDefs(BaseAttributeDefs):
        """Aqara P1 manufacturer attributes."""

        detection_interval: Final = ZCLAttributeDef(
            id=0x0102,
            type=t.uint8_t,
            access="rwp",
            manufacturer_code=AQARA_MFG_CODE,
        )
        motion_sensitivity: Final = ZCLAttributeDef(
            id=0x010C,
            type=MotionSensitivity,
            zcl_type=DataTypeId.uint8,
            access="rwp",
            manufacturer_code=AQARA_MFG_CODE,
        )
        trigger_indicator: Final = ZCLAttributeDef(
            id=0x0152,
            type=t.uint8_t,
            access="rwp",
            manufacturer_code=AQARA_MFG_CODE,
        )
        occupancy_illuminance: Final = ZCLAttributeDef(
            id=0x0112,
            type=t.uint32_t,
            access="rp",
            manufacturer_code=AQARA_MFG_CODE,
        )
        aqara_lifeline: Final = ZCLAttributeDef(
            id=0x00F7,
            type=t.LVBytes,
            access="rp",
            manufacturer_code=AQARA_MFG_CODE,
        )

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        """Initialize manufacturer cluster and subscribe to source updates."""
        super().__init__(*args, **kwargs)
        self.on_event(
            AttributeReportedEvent.event_type,
            self._handle_attribute_event,
        )

    def _handle_attribute_event(
        self,
        event: AttributeReportedEvent,
    ) -> None:
        """Handle manufacturer attribute updates."""
        if event.attribute_id == self.AttributeDefs.aqara_lifeline.id:
            values = self._parse_lifeline_report(event.value)

            if self.BATTERY_VOLTAGE_TAG in values:
                self.endpoint.aqara_p1_lifeline.update_from_voltage(
                    values[self.BATTERY_VOLTAGE_TAG]
                )

            if self.ILLUMINANCE_TAG in values:
                self.endpoint.aqara_p1_illuminance.update_from_lux(
                    values[self.ILLUMINANCE_TAG]
                )

        if event.attribute_id == self.AttributeDefs.occupancy_illuminance.id:
            self.endpoint.aqara_p1_illuminance.update_from_lux(event.value & 0xFFFF)
            self.endpoint.occupancy.set_occupied()

    def _parse_lifeline_report(self, data: bytes) -> dict[int, Any]:
        """Parse Aqara P1 lifeline report."""
        values: dict[int, Any] = {}

        while len(data) >= 2:
            tag = data[0]

            try:
                typed_value, data = foundation.TypeValue.deserialize(data[1:])
            except ValueError:
                self.debug(
                    "Failed to deserialize Aqara P1 lifeline tag 0x%02X from %r",
                    tag,
                    data,
                )
                return values

            values[tag] = typed_value.value

        return values


class AqaraP1LifelineCluster(LocalDataCluster):
    """Values decoded from the Aqara lifeline."""

    cluster_id = 0xFC02
    ep_attribute = "aqara_p1_lifeline"

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
        """Estimate coarse CR battery percentage from voltage."""
        for threshold_mv, percentage in self.BATTERY_PERCENTAGE_THRESHOLDS_MV:
            if voltage_mv >= threshold_mv:
                return percentage

        return 0

    def _battery_percentage_with_hysteresis(self, voltage_mv: int) -> int:
        """Estimate coarse CR battery percentage with two-way hysteresis."""
        cached_percentage = self.get(
            self.AttributeDefs.battery_percentage.id,
        )
        new_percentage = self._battery_percentage_from_voltage(voltage_mv)

        if cached_percentage is None or new_percentage == cached_percentage:
            return new_percentage

        if new_percentage < cached_percentage:
            voltage_mv += self.BATTERY_HYSTERESIS_MV
        else:
            voltage_mv -= self.BATTERY_HYSTERESIS_MV

        return self._battery_percentage_from_voltage(voltage_mv)


class AqaraP1OccupancyCluster(LocalDataCluster, OccupancySensing):
    """Local occupancy cluster for Aqara Motion Sensor P1."""

    DETECTION_INTERVAL_SECONDS: Final = 30

    OCCUPANCY_ATTR_ID: Final = OccupancySensing.AttributeDefs.occupancy.id

    _VALID_ATTRIBUTES: set[int] = {
        OCCUPANCY_ATTR_ID,
    }

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        """Initialize local occupancy timer."""
        super().__init__(*args, **kwargs)
        self._occupancy_timer_handle: asyncio.TimerHandle | None = None

    def set_occupied(self) -> None:
        """Set occupancy and schedule the reset timer."""
        self._update_attribute(
            self.OCCUPANCY_ATTR_ID,
            OccupancySensing.Occupancy.Occupied,
        )
        self._reschedule_occupancy_timer()

    def _reschedule_occupancy_timer(self) -> None:
        """Reschedule occupancy reset timer."""
        if self._occupancy_timer_handle is not None:
            self._occupancy_timer_handle.cancel()

        detection_interval = self.endpoint.aqara_p1_manufacturer.get(
            AqaraP1ManufacturerCluster.AttributeDefs.detection_interval.id,
        )

        if detection_interval is None:
            detection_interval = self.DETECTION_INTERVAL_SECONDS

        self._occupancy_timer_handle = asyncio.get_running_loop().call_later(
            detection_interval,
            self._set_unoccupied,
        )

    def _set_unoccupied(self) -> None:
        """Clear occupancy after the reset timer expires."""
        self._occupancy_timer_handle = None
        self._update_attribute(
            self.OCCUPANCY_ATTR_ID,
            OccupancySensing.Occupancy.Unoccupied,
        )


class AqaraP1IlluminanceCluster(LocalDataCluster):
    """Local illuminance values reported by Aqara Motion Sensor P1."""

    cluster_id = 0xFC03
    ep_attribute = "aqara_p1_illuminance"

    class AttributeDefs(BaseAttributeDefs):
        """Attribute definitions."""

        illuminance: Final = ZCLAttributeDef(
            id=0x0000,
            type=t.uint16_t,
            manufacturer_code=None,
        )

    _VALID_ATTRIBUTES: set[int] = {
        AttributeDefs.illuminance.id,
    }

    def update_from_lux(self, value: int) -> None:
        """Update illuminance in lux."""
        if value < 0 or value > 0xFDE8:
            self.debug(
                "Received invalid illuminance value: %s - setting illuminance to 0",
                value,
            )
            value = 0

        self.update_attribute(
            self.AttributeDefs.illuminance.id,
            value,
        )


(
    QuirkBuilder("LUMI", "lumi.motion.ac02")
    .friendly_name(manufacturer="Aqara", model="Motion Sensor P1")
    .adds(AqaraP1OccupancyCluster, endpoint_id=1)
    .adds(AqaraP1IlluminanceCluster, endpoint_id=1)
    .adds(AqaraP1LifelineCluster, endpoint_id=1)
    .replaces(AqaraP1ManufacturerCluster, endpoint_id=1)
    .removes(PowerConfiguration.cluster_id)
    .removes(
        AqaraP1ManufacturerCluster.cluster_id,
        cluster_type=ClusterType.Client,
    )
    .sensor(
        attribute_name="illuminance",
        cluster_id=AqaraP1IlluminanceCluster.cluster_id,
        device_class=SensorDeviceClass.ILLUMINANCE,
        state_class=SensorStateClass.MEASUREMENT,
        unit="lx",
        translation_key="illuminance",
        fallback_name="Illuminance",
    )
    .sensor(
        attribute_name="battery_percentage",
        cluster_id=AqaraP1LifelineCluster.cluster_id,
        device_class=SensorDeviceClass.BATTERY,
        state_class=SensorStateClass.MEASUREMENT,
        unit=PERCENTAGE,
        entity_type=EntityType.DIAGNOSTIC,
        suggested_display_precision=0,
        translation_key="battery",
        fallback_name="Battery",
    )
    .sensor(
        attribute_name="battery_voltage",
        cluster_id=AqaraP1LifelineCluster.cluster_id,
        device_class=SensorDeviceClass.VOLTAGE,
        state_class=SensorStateClass.MEASUREMENT,
        unit=UnitOfElectricPotential.VOLT,
        entity_type=EntityType.DIAGNOSTIC,
        initially_disabled=True,
        suggested_display_precision=3,
        translation_key="battery_voltage",
        fallback_name="Battery voltage",
    )
    .number(
        attribute_name="detection_interval",
        cluster_id=AqaraP1ManufacturerCluster.cluster_id,
        device_class=NumberDeviceClass.DURATION,
        min_value=2,
        max_value=200,
        step=1,
        unit=UnitOfTime.SECONDS,
        translation_key="detection_interval",
        fallback_name="Detection interval",
    )
    .enum(
        attribute_name="motion_sensitivity",
        enum_class=MotionSensitivity,
        cluster_id=AqaraP1ManufacturerCluster.cluster_id,
        translation_key="motion_sensitivity",
        fallback_name="Motion sensitivity",
    )
    .switch(
        attribute_name="trigger_indicator",
        cluster_id=AqaraP1ManufacturerCluster.cluster_id,
        translation_key="trigger_indicator",
        fallback_name="LED trigger indicator",
    )
    .add_to_registry()
)
