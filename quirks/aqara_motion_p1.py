"""Quirk v2 for Aqara Motion Sensor P1 lumi.motion.ac02 / RTCGQ14LM."""

import asyncio
import math
from typing import Any, Final

from zigpy import types as t
from zigpy.quirks.v2 import (
    EntityType,
    NumberDeviceClass,
    QuirkBuilder,
    SensorDeviceClass,
    SensorStateClass,
)
from zigpy.quirks.v2.homeassistant import UnitOfElectricPotential, UnitOfTime
from zigpy.zcl import ClusterType, foundation
from zigpy.zcl.clusters.general import PowerConfiguration
from zigpy.zcl.clusters.measurement import IlluminanceMeasurement, OccupancySensing
from zigpy.zcl.foundation import BaseAttributeDefs, DataTypeId, ZCLAttributeDef

from zhaquirks import CustomCluster, LocalDataCluster

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

    AQARA_LIFELINE_ATTR_ID: Final = 0x00F7
    OCCUPANCY_ILLUMINANCE_ATTR_ID: Final = 0x0112

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

    def _handle_aqara_lifeline_report(self, data: bytes) -> None:
        """Handle Aqara lifeline report: tag + ZCL type + value."""
        while len(data) >= 2:
            tag = data[0]

            try:
                typed_value, data = foundation.TypeValue.deserialize(data[1:])
            except ValueError:
                self.debug(
                    "Failed to deserialize Aqara lifeline tag 0x%02x from %r",
                    tag,
                    data,
                )
                return

            self._apply_aqara_lifeline_tag(tag, typed_value.value)

    def _apply_aqara_lifeline_tag(self, tag: int, value: Any) -> None:
        """Apply parsed Aqara lifeline tag."""
        if tag == self.BATTERY_VOLTAGE_TAG:
            self.endpoint.power.update_battery(
                value,
            )
        elif tag == self.ILLUMINANCE_TAG:
            self.endpoint.illuminance.update_attribute(
                IlluminanceMeasurement.AttributeDefs.measured_value.id,
                value,
            )
        elif tag == self.DETECTION_INTERVAL_TAG:
            super()._update_attribute(
                self.AttributeDefs.detection_interval.id,
                value,
            )
        elif tag == self.MOTION_SENSITIVITY_TAG:
            super()._update_attribute(
                self.AttributeDefs.motion_sensitivity.id,
                value,
            )
        elif tag == self.TRIGGER_INDICATOR_TAG:
            super()._update_attribute(
                self.AttributeDefs.trigger_indicator.id,
                value,
            )

    def _update_attribute(self, attrid: int, value: Any) -> None:
        """Update P1 manufacturer attributes and derived local clusters."""
        super()._update_attribute(attrid, value)

        if attrid == self.AQARA_LIFELINE_ATTR_ID:
            self._handle_aqara_lifeline_report(value)

        elif attrid == self.OCCUPANCY_ILLUMINANCE_ATTR_ID:
            self.endpoint.illuminance.update_attribute(
                IlluminanceMeasurement.AttributeDefs.measured_value.id,
                value & 0xFFFF,
            )
            self.endpoint.occupancy.update_attribute(
                OccupancySensing.AttributeDefs.occupancy.id,
                OccupancySensing.Occupancy.Occupied,
            )


class AqaraP1PowerConfigurationCluster(LocalDataCluster, PowerConfiguration):
    """Power cluster with coarse voltage-based battery percentage estimation."""

    BATTERY_VOLTAGE_ATTR_ID: Final = PowerConfiguration.AttributeDefs.battery_voltage.id
    BATTERY_PERCENTAGE_ATTR_ID: Final = (
        PowerConfiguration.AttributeDefs.battery_percentage_remaining.id
    )
    BATTERY_QUANTITY_ATTR_ID: Final = (
        PowerConfiguration.AttributeDefs.battery_quantity.id
    )
    BATTERY_SIZE_ATTR_ID: Final = PowerConfiguration.AttributeDefs.battery_size.id

    BATTERY_HYSTERESIS_MV: Final = 10

    # battery_percentage_remaining is encoded in half-percent units:
    # 200 -> 100%, 100 -> 50%, 50 -> 25%, 10 -> 5%.
    BATTERY_PERCENTAGE_THRESHOLDS_MV: Final = (
        (2870, 200),
        (2840, 100),
        (2810, 50),
        (2790, 10),
    )

    _VALID_ATTRIBUTES: set[int] = {
        BATTERY_VOLTAGE_ATTR_ID,
        BATTERY_PERCENTAGE_ATTR_ID,
    }

    _CONSTANT_ATTRIBUTES: dict[int, Any] = {
        BATTERY_QUANTITY_ATTR_ID: 2,
        BATTERY_SIZE_ATTR_ID: PowerConfiguration.BatterySize.Other,
    }

    def update_battery(self, voltage_mv: int) -> None:
        """Update battery voltage and estimated battery percentage."""
        self._update_attribute(
            self.BATTERY_VOLTAGE_ATTR_ID,
            round(voltage_mv / 100, 1),
        )
        self._update_attribute(
            self.BATTERY_PERCENTAGE_ATTR_ID,
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
        battery_percentage = self._battery_percentage_from_voltage(voltage_mv)

        cached_percentage = self.get(self.BATTERY_PERCENTAGE_ATTR_ID)
        if cached_percentage is None:
            return battery_percentage

        if battery_percentage == cached_percentage:
            return battery_percentage

        if battery_percentage < cached_percentage:
            return self._battery_percentage_from_voltage(
                voltage_mv + self.BATTERY_HYSTERESIS_MV
            )

        if battery_percentage > cached_percentage:
            return self._battery_percentage_from_voltage(
                voltage_mv - self.BATTERY_HYSTERESIS_MV
            )

        return battery_percentage


class AqaraP1OccupancyCluster(LocalDataCluster, OccupancySensing):
    """Local occupancy cluster for Aqara Motion Sensor P1."""

    DETECTION_INTERVAL_SECONDS: Final = 30

    OCCUPANCY_ATTR_ID: Final = OccupancySensing.AttributeDefs.occupancy.id

    _VALID_ATTRIBUTES: set[int] = {
        OCCUPANCY_ATTR_ID,
    }

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        """Init local occupancy timer."""
        super().__init__(*args, **kwargs)
        self._occupancy_timer_handle: asyncio.TimerHandle | None = None

    def _reschedule_timer(self) -> None:
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
            self._clear_occupancy,
        )

    def _clear_occupancy(self) -> None:
        """Clear occupancy after the reset timer expires."""
        self._occupancy_timer_handle = None
        self._update_attribute(
            self.OCCUPANCY_ATTR_ID,
            OccupancySensing.Occupancy.Unoccupied,
        )

    def _update_attribute(self, attrid: int, value: Any) -> None:
        """Update occupancy and reschedule reset timer on occupied reports."""
        super()._update_attribute(attrid, value)

        if (
            attrid == self.OCCUPANCY_ATTR_ID
            and value == OccupancySensing.Occupancy.Occupied
        ):
            self._reschedule_timer()


class AqaraP1IlluminanceCluster(LocalDataCluster, IlluminanceMeasurement):
    """Local illuminance measurement cluster for Aqara Motion Sensor P1."""

    MEASURED_VALUE_ATTR_ID: Final = (
        IlluminanceMeasurement.AttributeDefs.measured_value.id
    )

    _VALID_ATTRIBUTES: set[int] = {
        MEASURED_VALUE_ATTR_ID,
    }

    def _update_attribute(self, attrid: int, value: Any) -> None:
        """Update illuminance from lux and discard invalid values sent by this device."""
        if attrid == self.MEASURED_VALUE_ATTR_ID:
            if value < 0 or value > 0xFFDC:
                self.debug(
                    "Received invalid illuminance value: %s - setting illuminance to 0",
                    value,
                )
                value = 0

            if value > 0:
                value = round(10000 * math.log10(value) + 1)

        super()._update_attribute(attrid, value)


(
    QuirkBuilder("LUMI", "lumi.motion.ac02")
    .friendly_name(manufacturer="Aqara", model="Motion Sensor P1")
    .replaces(AqaraP1PowerConfigurationCluster, endpoint_id=1)
    .adds(AqaraP1OccupancyCluster, endpoint_id=1)
    .adds(AqaraP1IlluminanceCluster, endpoint_id=1)
    .replaces(AqaraP1ManufacturerCluster, endpoint_id=1)
    # Remove the unused client-side 0xFCC0 cluster; the server
    # cluster is replaced above.
    .removes(
        AqaraP1ManufacturerCluster.cluster_id,
        endpoint_id=1,
        cluster_type=ClusterType.Client,
    )
    .sensor(
        attribute_name=PowerConfiguration.AttributeDefs.battery_voltage.name,
        cluster_id=PowerConfiguration.cluster_id,
        endpoint_id=1,
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
        attribute_name=AqaraP1ManufacturerCluster.AttributeDefs.detection_interval.name,
        cluster_id=AqaraP1ManufacturerCluster.cluster_id,
        endpoint_id=1,
        device_class=NumberDeviceClass.DURATION,
        min_value=2,
        max_value=200,
        step=1,
        unit=UnitOfTime.SECONDS,
        entity_type=EntityType.CONFIG,
        translation_key="detection_interval",
        fallback_name="Detection interval",
    )
    .enum(
        attribute_name=AqaraP1ManufacturerCluster.AttributeDefs.motion_sensitivity.name,
        cluster_id=AqaraP1ManufacturerCluster.cluster_id,
        endpoint_id=1,
        enum_class=MotionSensitivity,
        entity_type=EntityType.CONFIG,
        translation_key="motion_sensitivity",
        fallback_name="Motion sensitivity",
    )
    .switch(
        attribute_name=AqaraP1ManufacturerCluster.AttributeDefs.trigger_indicator.name,
        cluster_id=AqaraP1ManufacturerCluster.cluster_id,
        endpoint_id=1,
        entity_type=EntityType.CONFIG,
        off_value=0,
        on_value=1,
        translation_key="trigger_indicator",
        fallback_name="LED trigger indicator",
    )
    .add_to_registry()
)
