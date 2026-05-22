"""Quirk v2 for Aqara Motion Sensor P1 lumi.motion.ac02 / RTCGQ14LM."""

import asyncio
from typing import Any, Final

from zigpy import types as t
from zigpy.quirks.v2 import QuirkBuilder
from zigpy.quirks.v2.homeassistant import (
    EntityType,
    UnitOfElectricPotential,
    UnitOfTime,
)
from zigpy.quirks.v2.homeassistant.binary_sensor import BinarySensorDeviceClass
from zigpy.quirks.v2.homeassistant.number import NumberDeviceClass
from zigpy.quirks.v2.homeassistant.sensor import (
    SensorDeviceClass,
    SensorStateClass,
)
from zigpy.zcl import ClusterType
from zigpy.zcl.foundation import BaseAttributeDefs, DataTypeId, ZCLAttributeDef

from zhaquirks import LocalDataCluster
from zhaquirks.xiaomi import (
    XiaomiAqaraE1Cluster,
    XiaomiPowerConfiguration,
)

AQARA_MFG_CODE: Final = 0x115F


class MotionSensitivity(t.enum8):
    """Aqara Motion Sensor P1 motion sensitivity."""

    Low = 1
    Medium = 2
    High = 3


class AqaraP1PowerConfigurationCluster(XiaomiPowerConfiguration):
    """Power cluster for Aqara Motion Sensor P1 with Aqara-like coarse battery percentage."""

    FULL_THRESHOLD_MV: Final = 2880
    LOW_THRESHOLD_MV: Final = 2760

    def battery_reported(self, voltage_mv: int) -> None:
        """Update raw battery voltage in mV and derived battery percentage."""
        super()._update_attribute(self.BATTERY_VOLTAGE_ATTR, voltage_mv)
        self._update_battery_percentage(voltage_mv)

    def _update_battery_percentage(self, voltage_mv: int) -> None:
        """Update coarse battery percentage from battery voltage."""
        if voltage_mv >= self.FULL_THRESHOLD_MV:
            percentage = 100
        elif voltage_mv > self.LOW_THRESHOLD_MV:
            percentage = 50
        else:
            percentage = 0

        self._update_attribute(
            self.BATTERY_PERCENTAGE_REMAINING,
            percentage * 2,
        )


class AqaraP1ManuCluster(XiaomiAqaraE1Cluster):
    """Aqara Motion Sensor P1 manufacturer cluster."""

    cluster_id = 0xFCC0
    ep_attribute = "aqara_p1_manu"

    MOTION_ILLUMINANCE_ATTR: Final = 0x0112

    class AttributeDefs(XiaomiAqaraE1Cluster.AttributeDefs):
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

    def _update_attribute(self, attrid: int, value: Any) -> None:
        """Handle P1 manufacturer attribute updates."""
        super()._update_attribute(attrid, value)

        if attrid == self.MOTION_ILLUMINANCE_ATTR:
            self.endpoint.illuminance.motion_illuminance_reported(value)
            self.endpoint.aqara_p1_occupancy.motion_reported()


class AqaraP1OccupancyCluster(LocalDataCluster):
    """Local self-reset occupancy cluster for Aqara Motion Sensor P1."""

    cluster_id = 0xFCF0
    ep_attribute = "aqara_p1_occupancy"

    FALLBACK_DETECTION_INTERVAL: Final = 30

    class AttributeDefs(BaseAttributeDefs):
        """Aqara P1 local occupancy attributes."""

        occupancy: Final = ZCLAttributeDef(
            id=0x0000,
            type=t.Bool,
            access="rp",
            manufacturer_code=AQARA_MFG_CODE,
        )

        occupancy_timeout: Final = ZCLAttributeDef(
            id=0xF000,
            type=t.uint16_t,
            access="rwp",
            manufacturer_code=AQARA_MFG_CODE,
        )

    _DEFAULT_VALUES = {
        AttributeDefs.occupancy.id: False,
        AttributeDefs.occupancy_timeout.id: 2,
    }

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        """Init local occupancy timer."""
        super().__init__(*args, **kwargs)
        self._timer_handle: asyncio.TimerHandle | None = None
        self._loop = asyncio.get_running_loop()

    def motion_reported(self) -> None:
        """Update occupancy from motion report and restart reset timer."""
        self._update_attribute(
            self.AttributeDefs.occupancy.id,
            True,
        )
        self._restart_timer()

    def _get_occupancy_timeout(self) -> int:
        """Get effective occupancy timeout."""
        detection_interval = self.endpoint.aqara_p1_manu.get(
            AqaraP1ManuCluster.AttributeDefs.detection_interval.id,
            self.FALLBACK_DETECTION_INTERVAL,
        )
        occupancy_timeout = self.get(self.AttributeDefs.occupancy_timeout.id)

        return int(detection_interval) + int(occupancy_timeout)

    def _restart_timer(self) -> None:
        """Restart local occupancy reset timer."""
        if self._timer_handle:
            self._timer_handle.cancel()

        self._timer_handle = self._loop.call_later(
            self._get_occupancy_timeout(),
            self._turn_off,
        )

    def _turn_off(self) -> None:
        """Reset occupancy to off."""
        self._timer_handle = None
        self._update_attribute(
            self.AttributeDefs.occupancy.id,
            False,
        )


class AqaraP1IlluminanceCluster(LocalDataCluster):
    """Local illuminance cluster for Aqara Motion Sensor P1."""

    cluster_id = 0xFCF1
    ep_attribute = "illuminance"

    MOTION_ILLUMINANCE_OFFSET: Final = 65536

    class AttributeDefs(BaseAttributeDefs):
        """Aqara P1 local illuminance attributes."""

        illuminance: Final = ZCLAttributeDef(
            id=0x0000,
            type=t.uint32_t,
            access="rp",
            manufacturer_code=AQARA_MFG_CODE,
        )

        illuminance_calibration: Final = ZCLAttributeDef(
            id=0xF000,
            type=t.int16s,
            access="rwp",
            manufacturer_code=AQARA_MFG_CODE,
        )

    _DEFAULT_VALUES = {
        AttributeDefs.illuminance.id: 0,
        AttributeDefs.illuminance_calibration.id: 0,
    }

    def motion_illuminance_reported(self, value: int) -> None:
        """Update illuminance from motion-triggered raw illuminance report."""
        self._update_attribute(
            self.AttributeDefs.illuminance.id,
            int(value) - self.MOTION_ILLUMINANCE_OFFSET,
        )
    
    def _update_attribute(self, attrid: int, value: Any) -> None:
        """Apply calibration to illuminance updates."""
        if attrid == self.AttributeDefs.illuminance.id:
            calibration = self.get(self.AttributeDefs.illuminance_calibration.id)
            value = max(0, int(value) + int(calibration))
    
        super()._update_attribute(attrid, value)


(
    QuirkBuilder("LUMI", "lumi.motion.ac02")
    .friendly_name(manufacturer="Aqara", model="Motion Sensor P1")
    .replaces(AqaraP1PowerConfigurationCluster, endpoint_id=1)
    .adds(AqaraP1OccupancyCluster, endpoint_id=1)
    .adds(AqaraP1IlluminanceCluster, endpoint_id=1)
    .replaces(AqaraP1ManuCluster, endpoint_id=1)
    .removes(
        AqaraP1ManuCluster.cluster_id,
        endpoint_id=1,
        cluster_type=ClusterType.Client,
    )
    .binary_sensor(
        attribute_name=AqaraP1OccupancyCluster.AttributeDefs.occupancy.name,
        cluster_id=AqaraP1OccupancyCluster.cluster_id,
        endpoint_id=1,
        device_class=BinarySensorDeviceClass.OCCUPANCY,
        entity_type=EntityType.STANDARD,
        translation_key="occupancy",
        fallback_name="Occupancy",
    )
    .sensor(
        attribute_name=AqaraP1IlluminanceCluster.AttributeDefs.illuminance.name,
        cluster_id=AqaraP1IlluminanceCluster.cluster_id,
        endpoint_id=1,
        device_class=SensorDeviceClass.ILLUMINANCE,
        state_class=SensorStateClass.MEASUREMENT,
        unit="lx",
        entity_type=EntityType.STANDARD,
        translation_key="illuminance",
        fallback_name="Illuminance",
    )
    .number(
        attribute_name=AqaraP1IlluminanceCluster.AttributeDefs.illuminance_calibration.name,
        cluster_id=AqaraP1IlluminanceCluster.cluster_id,
        endpoint_id=1,
        entity_type=EntityType.CONFIG,
        min_value=-100.0,
        max_value=100.0,
        step=1.0,
        unit="lx",
        translation_key="illuminance_calibration",
        fallback_name="Illuminance calibration",
    )
    .number(
        attribute_name=AqaraP1OccupancyCluster.AttributeDefs.occupancy_timeout.name,
        cluster_id=AqaraP1OccupancyCluster.cluster_id,
        endpoint_id=1,
        device_class=NumberDeviceClass.DURATION,
        entity_type=EntityType.CONFIG,
        min_value=0.0,
        max_value=600.0,
        step=1.0,
        unit=UnitOfTime.SECONDS,
        translation_key="occupancy_timeout",
        fallback_name="Occupancy timeout",
    )
    .number(
        attribute_name=AqaraP1ManuCluster.AttributeDefs.detection_interval.name,
        cluster_id=AqaraP1ManuCluster.cluster_id,
        endpoint_id=1,
        device_class=NumberDeviceClass.DURATION,
        entity_type=EntityType.CONFIG,
        min_value=2.0,
        max_value=200.0,
        step=1.0,
        unit=UnitOfTime.SECONDS,
        translation_key="occupancy_detection_interval",
        fallback_name="Occupancy detection interval",
    )
    .enum(
        attribute_name=AqaraP1ManuCluster.AttributeDefs.motion_sensitivity.name,
        enum_class=MotionSensitivity,
        cluster_id=AqaraP1ManuCluster.cluster_id,
        endpoint_id=1,
        entity_type=EntityType.CONFIG,
        translation_key="motion_sensitivity",
        fallback_name="Motion sensitivity",
    )
    .switch(
        attribute_name=AqaraP1ManuCluster.AttributeDefs.trigger_indicator.name,
        cluster_id=AqaraP1ManuCluster.cluster_id,
        endpoint_id=1,
        entity_type=EntityType.CONFIG,
        off_value=0,
        on_value=1,
        translation_key="trigger_indicator",
        fallback_name="Trigger indicator",
    )
    .sensor(
        attribute_name="battery_voltage",
        cluster_id=AqaraP1PowerConfigurationCluster.cluster_id,
        endpoint_id=1,
        device_class=SensorDeviceClass.VOLTAGE,
        state_class=SensorStateClass.MEASUREMENT,
        unit=UnitOfElectricPotential.MILLIVOLT,
        entity_type=EntityType.DIAGNOSTIC,
        initially_disabled=True,
        translation_key="battery_voltage",
        fallback_name="Battery voltage",
    )
    .add_to_registry()
)
