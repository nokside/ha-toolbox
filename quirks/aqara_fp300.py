"""Quirk for Aqara Presence Multi-Sensor FP300 lumi.sensor_occupy.agl8.

The FP300 will only work correctly if the Zigbee coordinator's manufacturer
code is 0x115F. However, forcing this code for the entire Zigbee network may
break devices from other manufacturers.

To ensure correct operation, use coordinator firmware that reports
manufacturer code 0x115F for Aqara devices, like Koenkk's Z-Stack firmware.

Factory reset the FP300 before re-pairing it after switching Zigbee
platforms or quirk implementations.
"""

from typing import Any, Final

from zigpy import types as t
from zigpy.zcl import (
    AttributeReadEvent,
    AttributeReportedEvent,
    AttributeWrittenEvent,
    foundation,
)
from zigpy.zcl.clusters.general import PowerConfiguration
from zigpy.zcl.foundation import BaseAttributeDefs, DataTypeId, Status, ZCLAttributeDef

from zhaquirks import CustomCluster, LocalDataCluster
from zhaquirks.builder import (
    PERCENTAGE,
    BinarySensorDeviceClass,
    EntityType,
    NumberDeviceClass,
    QuirkBuilder,
    SensorDeviceClass,
    SensorStateClass,
    UnitOfLength,
    UnitOfTemperature,
    UnitOfTime,
)
from zhaquirks.const import BatterySize
from zhaquirks.xiaomi import XiaomiPowerConfigurationPercent

AQARA_MFG_CODE: Final = 0x115F


class PresenceSensitivity(t.enum8):
    """Presence sensitivity."""

    Low = 1
    Medium = 2
    High = 3


class PresenceDetectionMode(t.enum8):
    """Presence detection mode."""

    Hybrid = 0
    Radar_only = 1
    PIR_only = 2


class SamplingFrequency(t.enum8):
    """Sampling frequency."""

    Off = 0
    Low = 1
    Medium = 2
    High = 3
    Custom = 4


class ReportMode(t.enum8):
    """Report mode."""

    Threshold = 1
    Interval = 2
    Threshold_and_interval = 3


class FP300PowerConfigurationCluster(XiaomiPowerConfigurationPercent):
    """FP300 power configuration cluster."""

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        """Initialize the cluster."""
        super().__init__(*args, **kwargs)

        self._CONSTANT_ATTRIBUTES = {
            PowerConfiguration.AttributeDefs.battery_quantity.id: 2,
            PowerConfiguration.AttributeDefs.battery_size.id: BatterySize.CR2450,
        }

    def handle_cluster_general_request(
        self,
        hdr: foundation.ZCLHeader,
        args: list,
        *,
        dst_addressing: t.AddrMode | None = None,
    ) -> None:
        """Ignore reports from the device on this cluster."""


class FP300ManufacturerCluster(CustomCluster):
    """Aqara FP300 manufacturer cluster."""

    cluster_id = 0xFCC0
    ep_attribute = "fp300_manufacturer"

    BATTERY_VOLTAGE_TAG: Final = 0x17
    BATTERY_PERCENTAGE_TAG: Final = 0x18
    PRESENCE_TAG: Final = 0x64
    PIR_DETECTION_TAG: Final = 0x67

    class AttributeDefs(BaseAttributeDefs):
        """Attribute definitions."""

        presence: Final = ZCLAttributeDef(
            id=0x0142,
            type=t.Bool,
            zcl_type=DataTypeId.uint8,
            access="rp",
            manufacturer_code=AQARA_MFG_CODE,
        )
        presence_detection_mode: Final = ZCLAttributeDef(
            id=0x0199,
            type=PresenceDetectionMode,
            zcl_type=DataTypeId.uint8,
            access="rwp",
            manufacturer_code=AQARA_MFG_CODE,
        )
        absence_delay: Final = ZCLAttributeDef(
            id=0x0197,
            type=t.uint32_t,
            access="rwp",
            manufacturer_code=AQARA_MFG_CODE,
        )
        presence_sensitivity: Final = ZCLAttributeDef(
            id=0x010C,
            type=PresenceSensitivity,
            zcl_type=DataTypeId.uint8,
            access="rwp",
            manufacturer_code=AQARA_MFG_CODE,
        )
        detection_range: Final = ZCLAttributeDef(
            id=0x019A,
            type=t.LVBytes,
            access="rwp",
            manufacturer_code=AQARA_MFG_CODE,
        )
        pir_detection_interval: Final = ZCLAttributeDef(
            id=0x014F,
            type=t.uint16_t,
            access="rwp",
            manufacturer_code=AQARA_MFG_CODE,
        )
        pir_detection: Final = ZCLAttributeDef(
            id=0x014D,
            type=t.Bool,
            zcl_type=DataTypeId.uint8,
            access="rp",
            manufacturer_code=AQARA_MFG_CODE,
        )
        ai_interference_source_self_identification: Final = ZCLAttributeDef(
            id=0x015E,
            type=t.uint8_t,
            access="rwp",
            manufacturer_code=AQARA_MFG_CODE,
        )
        ai_adaptive_sensitivity: Final = ZCLAttributeDef(
            id=0x015D,
            type=t.uint8_t,
            access="rwp",
            manufacturer_code=AQARA_MFG_CODE,
        )
        ai_spatial_learning: Final = ZCLAttributeDef(
            id=0x0157,
            type=t.uint8_t,
            access="wp",
            manufacturer_code=AQARA_MFG_CODE,
        )
        light_report_threshold: Final = ZCLAttributeDef(
            id=0x0195,
            type=t.uint16_t,
            access="rwp",
            manufacturer_code=AQARA_MFG_CODE,
        )
        light_sampling: Final = ZCLAttributeDef(
            id=0x0192,
            type=SamplingFrequency,
            zcl_type=DataTypeId.uint8,
            access="rwp",
            manufacturer_code=AQARA_MFG_CODE,
        )
        light_report_mode: Final = ZCLAttributeDef(
            id=0x0196,
            type=ReportMode,
            zcl_type=DataTypeId.uint8,
            access="rwp",
            manufacturer_code=AQARA_MFG_CODE,
        )
        light_sampling_period: Final = ZCLAttributeDef(
            id=0x0193,
            type=t.uint32_t,
            access="rwp",
            manufacturer_code=AQARA_MFG_CODE,
        )
        light_report_interval: Final = ZCLAttributeDef(
            id=0x0194,
            type=t.uint32_t,
            access="rwp",
            manufacturer_code=AQARA_MFG_CODE,
        )
        temperature_humidity_sampling: Final = ZCLAttributeDef(
            id=0x0170,
            type=SamplingFrequency,
            zcl_type=DataTypeId.uint8,
            access="rwp",
            manufacturer_code=AQARA_MFG_CODE,
        )
        temperature_humidity_sampling_period: Final = ZCLAttributeDef(
            id=0x0162,
            type=t.uint32_t,
            access="rwp",
            manufacturer_code=AQARA_MFG_CODE,
        )
        temperature_report_mode: Final = ZCLAttributeDef(
            id=0x0165,
            type=ReportMode,
            zcl_type=DataTypeId.uint8,
            access="rwp",
            manufacturer_code=AQARA_MFG_CODE,
        )
        temperature_report_threshold: Final = ZCLAttributeDef(
            id=0x0164,
            type=t.uint16_t,
            access="rwp",
            manufacturer_code=AQARA_MFG_CODE,
        )
        temperature_report_interval: Final = ZCLAttributeDef(
            id=0x0163,
            type=t.uint32_t,
            access="rwp",
            manufacturer_code=AQARA_MFG_CODE,
        )
        humidity_report_mode: Final = ZCLAttributeDef(
            id=0x016C,
            type=ReportMode,
            zcl_type=DataTypeId.uint8,
            access="rwp",
            manufacturer_code=AQARA_MFG_CODE,
        )
        humidity_report_threshold: Final = ZCLAttributeDef(
            id=0x016B,
            type=t.uint16_t,
            access="rwp",
            manufacturer_code=AQARA_MFG_CODE,
        )
        humidity_report_interval: Final = ZCLAttributeDef(
            id=0x016A,
            type=t.uint32_t,
            access="rwp",
            manufacturer_code=AQARA_MFG_CODE,
        )
        led_indicator_off_period: Final = ZCLAttributeDef(
            id=0x0203,
            type=t.Bool,
            access="rwp",
            manufacturer_code=AQARA_MFG_CODE,
        )
        led_indicator_off_time: Final = ZCLAttributeDef(
            id=0x023E,
            type=t.uint32_t,
            access="rwp",
            manufacturer_code=AQARA_MFG_CODE,
        )
        target_distance: Final = ZCLAttributeDef(
            id=0x015F,
            type=t.uint32_t,
            access="rp",
            manufacturer_code=AQARA_MFG_CODE,
        )
        track_target_distance: Final = ZCLAttributeDef(
            id=0x0198,
            type=t.uint8_t,
            access="rwp",
            manufacturer_code=AQARA_MFG_CODE,
        )
        restart_device: Final = ZCLAttributeDef(
            id=0x00E8,
            type=t.Bool,
            access="rwp",
            manufacturer_code=AQARA_MFG_CODE,
        )
        aqara_heartbeat: Final = ZCLAttributeDef(
            id=0x00F7,
            type=t.LVBytes,
            access="rp",
            manufacturer_code=AQARA_MFG_CODE,
        )

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        """Initialize the FP300 manufacturer cluster."""
        super().__init__(*args, **kwargs)

        self.on_event(AttributeReportedEvent.event_type, self._handle_heartbeat_report)

        for event_type in (AttributeReadEvent, AttributeReportedEvent, AttributeWrittenEvent):
            self.on_event(event_type.event_type, self._handle_attribute_event)

    def _handle_heartbeat_report(self, event: AttributeReportedEvent) -> None:
        """Handle FP300 heartbeat report."""
        if event.attribute_id != self.AttributeDefs.aqara_heartbeat.id:
            return

        values = self._parse_heartbeat_report(event.value)

        if self.BATTERY_PERCENTAGE_TAG in values:
            self.endpoint.power.battery_percent_reported(
                values[self.BATTERY_PERCENTAGE_TAG]
            )

        if self.BATTERY_VOLTAGE_TAG in values:
            self.endpoint.power.battery_reported(
                values[self.BATTERY_VOLTAGE_TAG]
            )

        if self.PRESENCE_TAG in values:
            self.update_attribute(
                self.AttributeDefs.presence.id,
                values[self.PRESENCE_TAG],
            )

        if self.PIR_DETECTION_TAG in values:
            self.update_attribute(
                self.AttributeDefs.pir_detection.id,
                values[self.PIR_DETECTION_TAG],
            )

    def _handle_attribute_event(
        self,
        event: AttributeReadEvent | AttributeReportedEvent | AttributeWrittenEvent,
    ) -> None:
        """Handle attribute events."""
        if isinstance(event, AttributeWrittenEvent) and event.status != Status.SUCCESS:
            return

        if event.attribute_id == self.AttributeDefs.detection_range.id:
            self.endpoint.fp300_detection_range.update_range(event.value)

        if event.attribute_id == self.AttributeDefs.led_indicator_off_time.id:
            self.endpoint.fp300_led_indicator_off_time.update_time(event.value)

    def _parse_heartbeat_report(self, data: bytes) -> dict[int, Any]:
        """Parse FP300 heartbeat."""
        values: dict[int, Any] = {}

        while len(data) >= 2:
            tag = data[0]

            try:
                typed_value, data = foundation.TypeValue.deserialize(data[1:])
            except (KeyError, ValueError):
                self.debug("Failed to deserialize FP300 heartbeat tag 0x%02X from %r", tag, data)
                return values

            values[tag] = typed_value.value

        return values

    async def apply_custom_configuration(self, *args, **kwargs):
        """Read FP300 attributes."""
        await self.read_attributes(
            [
                self.AttributeDefs.presence_detection_mode.id,
                self.AttributeDefs.absence_delay.id,
                self.AttributeDefs.presence_sensitivity.id,
                self.AttributeDefs.detection_range.id,
                self.AttributeDefs.pir_detection_interval.id,
                self.AttributeDefs.ai_interference_source_self_identification.id,
                self.AttributeDefs.ai_adaptive_sensitivity.id,
                self.AttributeDefs.light_report_threshold.id,
                self.AttributeDefs.light_sampling.id,
                self.AttributeDefs.light_report_mode.id,
                self.AttributeDefs.light_sampling_period.id,
                self.AttributeDefs.light_report_interval.id,
                self.AttributeDefs.temperature_humidity_sampling.id,
                self.AttributeDefs.temperature_humidity_sampling_period.id,
                self.AttributeDefs.temperature_report_mode.id,
                self.AttributeDefs.temperature_report_threshold.id,
                self.AttributeDefs.temperature_report_interval.id,
                self.AttributeDefs.humidity_report_mode.id,
                self.AttributeDefs.humidity_report_threshold.id,
                self.AttributeDefs.humidity_report_interval.id,
                self.AttributeDefs.led_indicator_off_period.id,
                self.AttributeDefs.led_indicator_off_time.id,
                self.AttributeDefs.target_distance.id,
            ]
        )


class FP300DetectionRangeCluster(LocalDataCluster):
    """Local cluster for FP300 detection range."""

    cluster_id = 0xFC03
    ep_attribute = "fp300_detection_range"

    class AttributeDefs(BaseAttributeDefs):
        """Attribute definitions."""

        detection_range_slider: Final = ZCLAttributeDef(
            id=0x0000,
            type=t.uint8_t,
            manufacturer_code=None,
        )

    _DEFAULT_VALUES = {
        AttributeDefs.detection_range_slider.id: 24,
    }

    def update_range(self, value: bytes) -> None:
        """Update detection range from the real attribute."""
        mask = int.from_bytes(value[2:5], "little")
        self._update_attribute(self.AttributeDefs.detection_range_slider.id, mask.bit_length())

    async def write_attributes(
        self,
        attributes: dict[str | int | ZCLAttributeDef, Any],
        **kwargs,
    ) -> list:
        """Write detection range to the real attribute."""
        attr_id = FP300ManufacturerCluster.AttributeDefs.detection_range.id

        for value in attributes.values():
            mask = (1 << int(value)) - 1
            payload = t.LVBytes(b"\x00\x03" + mask.to_bytes(3, "little"))

        return await self.endpoint.fp300_manufacturer.write_attributes({attr_id: payload})


class FP300LedIndicatorOffTimeCluster(LocalDataCluster):
    """Local cluster for FP300 LED indicator off time."""

    cluster_id = 0xFC04
    ep_attribute = "fp300_led_indicator_off_time"

    class AttributeDefs(BaseAttributeDefs):
        """Attribute definitions."""

        led_indicator_off_start_time: Final = ZCLAttributeDef(
            id=0x0000,
            type=t.uint8_t,
            manufacturer_code=None,
        )
        led_indicator_off_end_time: Final = ZCLAttributeDef(
            id=0x0001,
            type=t.uint8_t,
            manufacturer_code=None,
        )

    _HOUR_SHIFTS = {
        AttributeDefs.led_indicator_off_start_time.id: 0,
        AttributeDefs.led_indicator_off_end_time.id: 16,
    }

    _DEFAULT_VALUES = {
        AttributeDefs.led_indicator_off_start_time.id: 21,
        AttributeDefs.led_indicator_off_end_time.id: 9,
    }

    def update_time(self, value: int) -> None:
        """Update LED indicator off time from the real attribute."""
        for attr_id, shift in self._HOUR_SHIFTS.items():
            self._update_attribute(attr_id, (value >> shift) & 0xFF)

    async def write_attributes(
        self,
        attributes: dict[str | int | ZCLAttributeDef, Any],
        **kwargs,
    ) -> list:
        """Write LED indicator off time to the real attribute."""
        attr_id = FP300ManufacturerCluster.AttributeDefs.led_indicator_off_time.id
        cache = self.endpoint.fp300_manufacturer.get(attr_id)

        if cache is None:
            cache = sum(
                default << self._HOUR_SHIFTS[default_id]
                for default_id, default in self._DEFAULT_VALUES.items()
            )

        for attr, value in attributes.items():
            shift = self._HOUR_SHIFTS[self.find_attribute(attr).id]
            payload = ((cache & ~(0xFF << shift)) | (int(value) << shift)) & 0x00FF00FF

        return await self.endpoint.fp300_manufacturer.write_attributes({attr_id: payload})


(
    QuirkBuilder("Aqara", "lumi.sensor_occupy.agl8")
    .friendly_name(manufacturer="Aqara", model="Presence Multi-Sensor FP300")
    .replaces(FP300ManufacturerCluster)
    .replaces(FP300PowerConfigurationCluster)
    .adds(FP300DetectionRangeCluster)
    .adds(FP300LedIndicatorOffTimeCluster)
    .binary_sensor(
        attribute_name="presence",
        cluster_id=FP300ManufacturerCluster.cluster_id,
        device_class=BinarySensorDeviceClass.OCCUPANCY,
        entity_type=EntityType.STANDARD,
        primary=True,
        fallback_name="Occupancy",
    )
    .enum(
        attribute_name="presence_detection_mode",
        enum_class=PresenceDetectionMode,
        cluster_id=FP300ManufacturerCluster.cluster_id,
        translation_key="presence_detection_mode",
        fallback_name="Presence detection mode",
    )
    .number(
        attribute_name="absence_delay",
        cluster_id=FP300ManufacturerCluster.cluster_id,
        device_class=NumberDeviceClass.DURATION,
        min_value=1,
        max_value=300,
        step=1,
        unit=UnitOfTime.SECONDS,
        translation_key="absence_delay",
        fallback_name="Absence delay",
    )
    .enum(
        attribute_name="presence_sensitivity",
        enum_class=PresenceSensitivity,
        cluster_id=FP300ManufacturerCluster.cluster_id,
        translation_key="presence_sensitivity",
        fallback_name="Presence sensitivity",
    )
    .number(
        attribute_name="detection_range_slider",
        cluster_id=FP300DetectionRangeCluster.cluster_id,
        device_class=NumberDeviceClass.DISTANCE,
        min_value=0.0,
        max_value=6.0,
        step=0.25,
        multiplier=0.25,
        unit=UnitOfLength.METERS,
        mode="slider",
        translation_key="detection_range",
        fallback_name="Detection range",
    )
    .number(
        attribute_name="pir_detection_interval",
        cluster_id=FP300ManufacturerCluster.cluster_id,
        device_class=NumberDeviceClass.DURATION,
        min_value=2,
        max_value=300,
        step=1,
        unit=UnitOfTime.SECONDS,
        translation_key="pir_detection_interval",
        fallback_name="PIR detection interval",
    )
    .binary_sensor(
        attribute_name="pir_detection",
        cluster_id=FP300ManufacturerCluster.cluster_id,
        device_class=BinarySensorDeviceClass.MOTION,
        initially_disabled=True,
        fallback_name="PIR detection",
    )
    .switch(
        attribute_name="ai_interference_source_self_identification",
        cluster_id=FP300ManufacturerCluster.cluster_id,
        translation_key="ai_interference_source_self_identification",
        fallback_name="AI interference source self-identification",
    )
    .switch(
        attribute_name="ai_adaptive_sensitivity",
        cluster_id=FP300ManufacturerCluster.cluster_id,
        translation_key="ai_adaptive_sensitivity",
        fallback_name="AI adaptive sensitivity",
    )
    .write_attr_button(
        attribute_name="ai_spatial_learning",
        attribute_value=1,
        cluster_id=FP300ManufacturerCluster.cluster_id,
        translation_key="ai_spatial_learning",
        fallback_name="AI spatial learning",
    )
    .number(
        attribute_name="light_report_threshold",
        cluster_id=FP300ManufacturerCluster.cluster_id,
        min_value=3.0,
        max_value=20.0,
        step=0.5,
        multiplier=0.01,
        unit=PERCENTAGE,
        translation_key="light_report_threshold",
        fallback_name="Light report threshold",
    )
    .enum(
        attribute_name="light_sampling",
        enum_class=SamplingFrequency,
        cluster_id=FP300ManufacturerCluster.cluster_id,
        translation_key="light_sampling",
        fallback_name="Light sampling",
    )
    .enum(
        attribute_name="light_report_mode",
        enum_class=ReportMode,
        cluster_id=FP300ManufacturerCluster.cluster_id,
        translation_key="light_report_mode",
        fallback_name="Light report mode",
    )
    .number(
        attribute_name="light_sampling_period",
        cluster_id=FP300ManufacturerCluster.cluster_id,
        device_class=NumberDeviceClass.DURATION,
        min_value=0.5,
        max_value=3600,
        step=0.5,
        multiplier=0.001,
        unit=UnitOfTime.SECONDS,
        translation_key="light_sampling_period",
        fallback_name="Light sampling period",
    )
    .number(
        attribute_name="light_report_interval",
        cluster_id=FP300ManufacturerCluster.cluster_id,
        device_class=NumberDeviceClass.DURATION,
        min_value=20,
        max_value=3600,
        step=1,
        multiplier=0.001,
        unit=UnitOfTime.SECONDS,
        translation_key="light_report_interval",
        fallback_name="Light report interval",
    )
    .enum(
        attribute_name="temperature_humidity_sampling",
        enum_class=SamplingFrequency,
        cluster_id=FP300ManufacturerCluster.cluster_id,
        translation_key="temperature_humidity_sampling",
        fallback_name="Temperature and humidity sampling",
    )
    .number(
        attribute_name="temperature_humidity_sampling_period",
        cluster_id=FP300ManufacturerCluster.cluster_id,
        device_class=NumberDeviceClass.DURATION,
        min_value=0.5,
        max_value=3600,
        step=0.5,
        multiplier=0.001,
        unit=UnitOfTime.SECONDS,
        translation_key="temperature_humidity_sampling_period",
        fallback_name="Temperature and humidity sampling period",
    )
    .enum(
        attribute_name="temperature_report_mode",
        enum_class=ReportMode,
        cluster_id=FP300ManufacturerCluster.cluster_id,
        translation_key="temperature_report_mode",
        fallback_name="Temperature report mode",
    )
    .number(
        attribute_name="temperature_report_threshold",
        cluster_id=FP300ManufacturerCluster.cluster_id,
        device_class=NumberDeviceClass.TEMPERATURE,
        min_value=0.2,
        max_value=3.0,
        step=0.1,
        multiplier=0.01,
        unit=UnitOfTemperature.CELSIUS,
        translation_key="temperature_report_threshold",
        fallback_name="Temperature report threshold",
    )
    .number(
        attribute_name="temperature_report_interval",
        cluster_id=FP300ManufacturerCluster.cluster_id,
        device_class=NumberDeviceClass.DURATION,
        min_value=600,
        max_value=3600,
        step=1,
        multiplier=0.001,
        unit=UnitOfTime.SECONDS,
        translation_key="temperature_report_interval",
        fallback_name="Temperature report interval",
    )
    .enum(
        attribute_name="humidity_report_mode",
        enum_class=ReportMode,
        cluster_id=FP300ManufacturerCluster.cluster_id,
        translation_key="humidity_report_mode",
        fallback_name="Humidity report mode",
    )
    .number(
        attribute_name="humidity_report_threshold",
        cluster_id=FP300ManufacturerCluster.cluster_id,
        device_class=NumberDeviceClass.HUMIDITY,
        min_value=2.0,
        max_value=15.0,
        step=0.5,
        multiplier=0.01,
        unit=PERCENTAGE,
        translation_key="humidity_report_threshold",
        fallback_name="Humidity report threshold",
    )
    .number(
        attribute_name="humidity_report_interval",
        cluster_id=FP300ManufacturerCluster.cluster_id,
        device_class=NumberDeviceClass.DURATION,
        min_value=600,
        max_value=3600,
        step=1,
        multiplier=0.001,
        unit=UnitOfTime.SECONDS,
        translation_key="humidity_report_interval",
        fallback_name="Humidity report interval",
    )
    .switch(
        attribute_name="led_indicator_off_period",
        cluster_id=FP300ManufacturerCluster.cluster_id,
        translation_key="led_indicator_off_period",
        fallback_name="LED indicator off period",
    )
    .number(
        attribute_name="led_indicator_off_start_time",
        cluster_id=FP300LedIndicatorOffTimeCluster.cluster_id,
        min_value=0,
        max_value=23,
        step=1,
        unit=UnitOfTime.HOURS,
        mode="box",
        translation_key="led_indicator_off_start_time",
        fallback_name="LED indicator off start time",
    )
    .number(
        attribute_name="led_indicator_off_end_time",
        cluster_id=FP300LedIndicatorOffTimeCluster.cluster_id,
        min_value=0,
        max_value=23,
        step=1,
        unit=UnitOfTime.HOURS,
        mode="box",
        translation_key="led_indicator_off_end_time",
        fallback_name="LED indicator off end time",
    )
    .sensor(
        attribute_name="target_distance",
        cluster_id=FP300ManufacturerCluster.cluster_id,
        device_class=SensorDeviceClass.DISTANCE,
        state_class=SensorStateClass.MEASUREMENT,
        unit=UnitOfLength.METERS,
        divisor=100,
        entity_type=EntityType.DIAGNOSTIC,
        translation_key="target_distance",
        fallback_name="Target distance",
    )
    .write_attr_button(
        attribute_name="track_target_distance",
        attribute_value=1,
        cluster_id=FP300ManufacturerCluster.cluster_id,
        translation_key="track_target_distance",
        fallback_name="Track target distance",
    )
    .write_attr_button(
        attribute_name="restart_device",
        attribute_value=1,
        cluster_id=FP300ManufacturerCluster.cluster_id,
        translation_key="restart",
        fallback_name="Restart",
    )
    .skip_configuration()
    .add_to_registry()
)
