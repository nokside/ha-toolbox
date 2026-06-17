"""Quirk v2 for Aqara Motion Sensor P1 lumi.motion.ac02 / RTCGQ14LM."""

import asyncio
from typing import Any, Final

from zigpy import types as t
from zigpy.quirks.v2 import QuirkBuilder
from zigpy.quirks.v2.homeassistant import (
    EntityType,
    LIGHT_LUX,
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
    """Power cluster for Aqara Motion Sensor P1."""

    BATTERY_100: Final = 2880
    BATTERY_0: Final = 2760

    def _update_battery_percentage(self, voltage_mv: int) -> None:
        """Update coarse battery percentage from battery voltage in mV."""
        if voltage_mv >= self.BATTERY_100:
            zcl_percentage = 100
        elif voltage_mv > self.BATTERY_0:
            zcl_percentage = 50
        else:
            zcl_percentage = 0

        self._update_attribute(
            self.BATTERY_PERCENTAGE_REMAINING,
            zcl_percentage * 2,
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
            self.endpoint.illuminance.illuminance_reported(value)
            self.endpoint.aqara_p1_occupancy.occupied_reported()


class AqaraP1OccupancyCluster(LocalDataCluster):
    """Local self-reset occupancy cluster for Aqara Motion Sensor P1."""

    cluster_id = 0xFCF0
    ep_attribute = "aqara_p1_occupancy"

    FALLBACK_DETECTION_INTERVAL: Final = 30
    # Small margin for reports that arrive after the configured detection interval.
    DETECTION_INTERVAL_MARGIN: Final = 2

    class AttributeDefs(BaseAttributeDefs):
        """Aqara P1 local occupancy attributes."""

        occupancy: Final = ZCLAttributeDef(
            id=0x0000,
            type=t.Bool,
            access="rp",
            manufacturer_code=AQARA_MFG_CODE,
        )

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        """Init local occupancy timer."""
        super().__init__(*args, **kwargs)
        self._timer_handle: asyncio.TimerHandle | None = None

    def occupied_reported(self) -> None:
        """Update occupancy from an occupied report."""
        self._update_attribute(
            self.AttributeDefs.occupancy.id,
            True,
        )
        self._restart_timer()

    def _get_occupancy_timeout(self) -> int:
        """Get effective occupancy reset timeout."""
        detection_interval = self.endpoint.aqara_p1_manu.get(
            AqaraP1ManuCluster.AttributeDefs.detection_interval.id,
            self.FALLBACK_DETECTION_INTERVAL,
        )
        return int(detection_interval) + self.DETECTION_INTERVAL_MARGIN

    def _restart_timer(self) -> None:
        """Restart local occupancy reset timer."""
        if self._timer_handle is not None:
            self._timer_handle.cancel()

        loop = asyncio.get_running_loop()
        self._timer_handle = loop.call_later(
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

    RAW_ILLUMINANCE_OFFSET: Final = 65536
    INVALID_ILLUMINANCE_VALUE: Final = 65000

    class AttributeDefs(BaseAttributeDefs):
        """Aqara P1 local illuminance attributes."""

        illuminance: Final = ZCLAttributeDef(
            id=0x0000,
            type=t.uint32_t,
            access="rp",
            manufacturer_code=AQARA_MFG_CODE,
        )

    def illuminance_reported(self, value: int) -> None:
        """Update illuminance from reported raw value."""
        illuminance = int(value) - self.RAW_ILLUMINANCE_OFFSET

        if illuminance > self.INVALID_ILLUMINANCE_VALUE:
            illuminance = 0

        self._update_attribute(
            self.AttributeDefs.illuminance.id,
            illuminance,
        )


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
        unit=LIGHT_LUX,
        entity_type=EntityType.STANDARD,
        translation_key="illuminance",
        fallback_name="Illuminance",
    )
    .number(
        attribute_name=AqaraP1ManuCluster.AttributeDefs.detection_interval.name,
        cluster_id=AqaraP1ManuCluster.cluster_id,
        endpoint_id=1,
        device_class=NumberDeviceClass.DURATION,
        entity_type=EntityType.CONFIG,
        min_value=2,
        max_value=200,
        step=1,
        unit=UnitOfTime.SECONDS,
        translation_key="detection_interval",
        fallback_name="Detection interval",
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
        unit=UnitOfElectricPotential.VOLT,
        multiplier=0.1,
        suggested_display_precision=2,
        entity_type=EntityType.DIAGNOSTIC,
        initially_disabled=True,
        translation_key="battery_voltage",
        fallback_name="Battery voltage",
    )
    .add_to_registry()
)
