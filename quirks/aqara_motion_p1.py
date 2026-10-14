"""Quirk for Aqara Motion Sensor P1 lumi.motion.ac02 / RTCGQ14LM."""

import asyncio
from typing import Any, Final

from zigpy import types as t
from zigpy.zcl import AttributeReportedEvent, foundation
from zigpy.zcl.clusters.general import PowerConfiguration
from zigpy.zcl.clusters.measurement import IlluminanceMeasurement, OccupancySensing
from zigpy.zcl.foundation import BaseAttributeDefs, DataTypeId, ZCLAttributeDef

from zhaquirks import CustomCluster, LocalDataCluster
from zhaquirks.builder import NumberDeviceClass, QuirkBuilder, UnitOfTime
from zhaquirks.const import BatterySize
from zhaquirks.xiaomi import LocalIlluminanceMeasurementCluster, XiaomiPowerConfiguration

AQARA_MFG_CODE: Final = 0x115F


class MotionSensitivity(t.enum8):
    """Motion sensitivity."""

    Low = 0x01
    Medium = 0x02
    High = 0x03


class P1ManufacturerCluster(CustomCluster):
    """Aqara Motion Sensor P1 manufacturer cluster."""

    cluster_id = 0xFCC0
    ep_attribute = "p1_manufacturer"

    BATTERY_VOLTAGE_TAG: Final = 0x01
    ILLUMINANCE_TAG: Final = 0x65
    DETECTION_INTERVAL_TAG: Final = 0x69
    MOTION_SENSITIVITY_TAG: Final = 0x6A
    LED_TRIGGER_INDICATOR_TAG: Final = 0x6B

    class AttributeDefs(BaseAttributeDefs):
        """P1 manufacturer attributes."""

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
        led_trigger_indicator: Final = ZCLAttributeDef(
            id=0x0152,
            type=t.uint8_t,
            access="rwp",
            manufacturer_code=AQARA_MFG_CODE,
        )
        motion_illuminance: Final = ZCLAttributeDef(
            id=0x0112,
            type=t.uint32_t,
            access="rp",
            manufacturer_code=AQARA_MFG_CODE,
        )
        aqara_heartbeat: Final = ZCLAttributeDef(
            id=0x00F7,
            type=t.LVBytes,
            access="rp",
            manufacturer_code=AQARA_MFG_CODE,
        )

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        """Init."""
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
        if event.attribute_id == self.AttributeDefs.aqara_heartbeat.id:
            values = self._parse_heartbeat_report(event.value)

            if self.BATTERY_VOLTAGE_TAG in values:
                self.endpoint.power.battery_reported(
                    values[self.BATTERY_VOLTAGE_TAG]
                )

            if self.ILLUMINANCE_TAG in values:
                self.endpoint.illuminance.update_attribute(
                    IlluminanceMeasurement.AttributeDefs.measured_value.id,
                    values[self.ILLUMINANCE_TAG],
                )

            if self.DETECTION_INTERVAL_TAG in values:
                self.update_attribute(
                    self.AttributeDefs.detection_interval.id,
                    values[self.DETECTION_INTERVAL_TAG],
                )

            if self.MOTION_SENSITIVITY_TAG in values:
                self.update_attribute(
                    self.AttributeDefs.motion_sensitivity.id,
                    values[self.MOTION_SENSITIVITY_TAG],
                )

            if self.LED_TRIGGER_INDICATOR_TAG in values:
                self.update_attribute(
                    self.AttributeDefs.led_trigger_indicator.id,
                    values[self.LED_TRIGGER_INDICATOR_TAG],
                )

        if event.attribute_id == self.AttributeDefs.motion_illuminance.id:
            self.endpoint.illuminance.update_attribute(
                IlluminanceMeasurement.AttributeDefs.measured_value.id,
                event.value & 0xFFFF,
            )
            self.endpoint.occupancy.set_occupied()

    def _parse_heartbeat_report(self, data: bytes) -> dict[int, Any]:
        """Parse Aqara P1 heartbeat report."""
        values: dict[int, Any] = {}

        while len(data) >= 2:
            tag = data[0]

            try:
                typed_value, data = foundation.TypeValue.deserialize(data[1:])
            except (KeyError, ValueError):
                self.debug(
                    "Failed to deserialize Aqara P1 heartbeat tag 0x%02X from %r",
                    tag,
                    data,
                )
                return values

            values[tag] = typed_value.value

        return values

    async def apply_custom_configuration(self, *args, **kwargs):
        """Read P1 configuration attributes."""
        await self.read_attributes(
            [
                self.AttributeDefs.detection_interval.id,
                self.AttributeDefs.motion_sensitivity.id,
                self.AttributeDefs.led_trigger_indicator.id,
            ]
        )


class P1PowerConfigurationCluster(XiaomiPowerConfiguration):
    """Aqara P1 power configuration cluster."""

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        """Initialize battery metadata."""
        super().__init__(*args, **kwargs)
        self._CONSTANT_ATTRIBUTES = {
            PowerConfiguration.AttributeDefs.battery_size.id: BatterySize.CR2450,
            PowerConfiguration.AttributeDefs.battery_quantity.id: 2,
        }

    def _update_battery_percentage(self, voltage_mv: int) -> None:
        """Update battery percentage from voltage."""
        # Aqara voltage curve.
        curve_value = 0.00045 * voltage_mv**2 - 2.277 * voltage_mv + 2880

        # Remap [33, 100] curve range to [20, 100]
        percentage = 20 + (curve_value - 33) * (100 - 20) / (100 - 33)

        # Clamp between 0 and 100
        percentage = max(0, min(100, percentage))

        self._update_attribute(
            self.BATTERY_PERCENTAGE_REMAINING,
            round(percentage * 2),
        )


class P1OccupancySensingCluster(LocalDataCluster, OccupancySensing):
    """Local occupancy cluster for Aqara Motion Sensor P1."""

    OCCUPANCY_ATTR_ID: Final = OccupancySensing.AttributeDefs.occupancy.id

    _VALID_ATTRIBUTES: set[int] = {OCCUPANCY_ATTR_ID}

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

        detection_interval = self.endpoint.p1_manufacturer.get(
            P1ManufacturerCluster.AttributeDefs.detection_interval.id,
            30,
        )

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


class P1IlluminanceMeasurementCluster(LocalIlluminanceMeasurementCluster):
    """Local illuminance measurement cluster for Aqara Motion Sensor P1."""

    def _update_attribute(self, attrid, value):
        if attrid == self.AttributeDefs.measured_value.id and (
            value < 0 or value > 0xFDE8
        ):
            self.debug(
                "Received invalid illuminance value: %s - setting illuminance to 0",
                value,
            )
            value = 0

        super()._update_attribute(attrid, value)


(
    QuirkBuilder("LUMI", "lumi.motion.ac02")
    .friendly_name(manufacturer="Aqara", model="Motion Sensor P1")
    .adds(P1OccupancySensingCluster, endpoint_id=1)
    .adds(P1IlluminanceMeasurementCluster, endpoint_id=1)
    .replaces(P1PowerConfigurationCluster, endpoint_id=1)
    .replaces(P1ManufacturerCluster, endpoint_id=1)
    .number(
        attribute_name="detection_interval",
        cluster_id=P1ManufacturerCluster.cluster_id,
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
        cluster_id=P1ManufacturerCluster.cluster_id,
        translation_key="motion_sensitivity",
        fallback_name="Motion sensitivity",
    )
    .switch(
        attribute_name="led_trigger_indicator",
        cluster_id=P1ManufacturerCluster.cluster_id,
        translation_key="led_trigger_indicator",
        fallback_name="LED trigger indicator",
    )
    .skip_configuration()
    .add_to_registry()
)