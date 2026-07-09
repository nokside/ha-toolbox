"""Quirk v2 for Aqara Motion Sensor P1 lumi.motion.ac02 / RTCGQ14LM."""

import asyncio
import math
from typing import Any, Final

from zha.units import UnitOfElectricPotential, UnitOfTime
from zhaquirks import CustomCluster, LocalDataCluster
from zhaquirks.builder import (
    EntityType,
    NumberDeviceClass,
    QuirkBuilder,
    SensorDeviceClass,
    SensorStateClass,
)
from zigpy import types as t
from zigpy.zcl import AttributeReportedEvent, ClusterType, foundation
from zigpy.zcl.clusters.general import PowerConfiguration
from zigpy.zcl.clusters.measurement import IlluminanceMeasurement, OccupancySensing
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
    DETECTION_INTERVAL_TAG: Final = 0x69
    MOTION_SENSITIVITY_TAG: Final = 0x6A
    TRIGGER_INDICATOR_TAG: Final = 0x6B

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
        """Initialize manufacturer cluster and subscribe to source reports."""
        super().__init__(*args, **kwargs)
        self.on_event(AttributeReportedEvent.event_type, self._handle_attribute_event)

    def _handle_attribute_event(self, event: AttributeReportedEvent) -> None:
        """Handle manufacturer reports and update derived local clusters."""
        if event.attribute_id == self.AttributeDefs.aqara_lifeline.id:
            values = self._parse_lifeline_report(event.value)

            if self.BATTERY_VOLTAGE_TAG in values:
                self.endpoint.power.update_from_voltage(
                    values[self.BATTERY_VOLTAGE_TAG]
                )

            if self.ILLUMINANCE_TAG in values:
                self.endpoint.illuminance.update_from_lux(values[self.ILLUMINANCE_TAG])

            if self.DETECTION_INTERVAL_TAG in values:
                self._update_attribute(
                    self.AttributeDefs.detection_interval.id,
                    values[self.DETECTION_INTERVAL_TAG],
                )

            if self.MOTION_SENSITIVITY_TAG in values:
                self._update_attribute(
                    self.AttributeDefs.motion_sensitivity.id,
                    values[self.MOTION_SENSITIVITY_TAG],
                )

            if self.TRIGGER_INDICATOR_TAG in values:
                self._update_attribute(
                    self.AttributeDefs.trigger_indicator.id,
                    values[self.TRIGGER_INDICATOR_TAG],
                )

        elif event.attribute_id == self.AttributeDefs.occupancy_illuminance.id:
            self.endpoint.illuminance.update_from_lux(event.value & 0xFFFF)
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


class AqaraP1PowerConfigurationCluster(LocalDataCluster, PowerConfiguration):
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
        BATTERY_QUANTITY_ATTR_ID: 2,
        BATTERY_SIZE_ATTR_ID: PowerConfiguration.BatterySize.Other,
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


class AqaraP1IlluminanceCluster(LocalDataCluster, IlluminanceMeasurement):
    """Local illuminance measurement cluster for Aqara Motion Sensor P1."""

    MEASURED_VALUE_ATTR_ID: Final = (
        IlluminanceMeasurement.AttributeDefs.measured_value.id
    )

    _VALID_ATTRIBUTES: set[int] = {
        MEASURED_VALUE_ATTR_ID,
    }

    def update_from_lux(self, value: int) -> None:
        """Update illuminance from raw lux reported by the device."""
        if value < 0 or value > 0xFDE8:
            self.debug(
                "Received invalid illuminance value: %s - setting illuminance to 0",
                value,
            )
            value = 0

        if value > 0:
            value = round(10000 * math.log10(value) + 1)

        self._update_attribute(self.MEASURED_VALUE_ATTR_ID, value)


(
    QuirkBuilder("LUMI", "lumi.motion.ac02")
    .friendly_name(manufacturer="Aqara", model="Motion Sensor P1")
    .replaces(AqaraP1PowerConfigurationCluster, endpoint_id=1)
    .adds(AqaraP1OccupancyCluster, endpoint_id=1)
    .adds(AqaraP1IlluminanceCluster, endpoint_id=1)
    .replaces(AqaraP1ManufacturerCluster, endpoint_id=1)
    .removes(
        AqaraP1ManufacturerCluster.cluster_id,
        cluster_type=ClusterType.Client,
    )
    .sensor(
        attribute_name="battery_voltage",
        cluster_id=AqaraP1PowerConfigurationCluster.cluster_id,
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
