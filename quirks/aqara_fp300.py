"""Quirk for Aqara Presence Multi-Sensor FP300 lumi.sensor_occupy.agl8."""

import functools
import random

from collections.abc import Iterator
from typing import Any, Final, Literal

from zha.application.helpers import safe_read, write_attributes_safe
from zha.application.platforms import BaseEntity, PlatformEntity
from zha.application.platforms.number import BaseNumber
from zha.application.platforms.number.const import NumberMode
from zha.application.platforms.select import BaseSelectEntity, EnumSelectInfo
from zhaquirks import CustomCluster, LocalDataCluster
from zhaquirks.builder import (
    PERCENTAGE,
    BinarySensorDeviceClass,
    EntityType,
    NumberDeviceClass,
    QuirkBuilder,
    ReportingConfig,
    SensorDeviceClass,
    SensorStateClass,
    UnitOfElectricPotential,
    UnitOfLength,
    UnitOfTemperature,
    UnitOfTime,
)
from zhaquirks.builder.device import QuirkV2Device
from zigpy import types as t
from zigpy.zcl import (
    AttributeReadEvent,
    AttributeReportedEvent,
    AttributeWrittenEvent,
    foundation,
)
from zigpy.zcl.clusters.general import PowerConfiguration
from zigpy.zcl.foundation import BaseAttributeDefs, DataTypeId, ZCLAttributeDef


AQARA_MFG_CODE: Final = 0x115F


class PresenceSensitivity(t.enum8):
    Low = 1
    Medium = 2
    High = 3


class PresenceDetectionMode(t.enum8):
    PIR_and_mmWave = 0
    mmWave_only = 1
    PIR_only = 2


class SamplingFrequency(t.enum8):
    Off = 0
    Low = 1
    Medium = 2
    High = 3
    Custom = 4


class ReportMode(t.enum8):
    Threshold = 1
    Interval = 2
    Threshold_and_interval = 3


class FP300PowerConfigurationCluster(PowerConfiguration, LocalDataCluster):
    """FP300 power cluster with filtered standard battery reports."""

    BATTERY_VOLTAGE_ATTR_ID: Final = PowerConfiguration.AttributeDefs.battery_voltage.id
    BATTERY_PERCENTAGE_REMAINING_ATTR_ID: Final = (
        PowerConfiguration.AttributeDefs.battery_percentage_remaining.id
    )
    BATTERY_QUANTITY_ATTR_ID: Final = (
        PowerConfiguration.AttributeDefs.battery_quantity.id
    )
    BATTERY_SIZE_ATTR_ID: Final = PowerConfiguration.AttributeDefs.battery_size.id

    _VALID_ATTRIBUTES: set[int] = {
        BATTERY_VOLTAGE_ATTR_ID,
        BATTERY_PERCENTAGE_REMAINING_ATTR_ID,
    }

    _CONSTANT_ATTRIBUTES: dict[int, Any] = {
        BATTERY_QUANTITY_ATTR_ID: 2,
        BATTERY_SIZE_ATTR_ID: PowerConfiguration.BatterySize.Other,
    }

    def battery_voltage_reported(self, value: int) -> None:
        """Update battery voltage from Aqara millivolt report."""
        self._update_attribute(
            self.BATTERY_VOLTAGE_ATTR_ID,
            round(value / 100, 1),
        )

    def battery_percentage_reported(self, value: int) -> None:
        """Update battery percentage from Aqara 0-100 report."""
        if not 0 <= value <= 100:
            self.debug("Ignoring invalid FP300 battery percentage: %s", value)
            return

        self._update_attribute(
            self.BATTERY_PERCENTAGE_REMAINING_ATTR_ID,
            value * 2,
        )

    def handle_cluster_general_request(
        self,
        hdr: foundation.ZCLHeader,
        args: list[Any],
        *,
        dst_addressing: t.AddrMode | None = None,
    ) -> None:
        """Filter out standard battery reports."""
        if hdr.command_id == foundation.GeneralCommand.Report_Attributes:
            args.attribute_reports = [
                attr
                for attr in args.attribute_reports
                if attr.attrid not in self._VALID_ATTRIBUTES
            ]

            if not args.attribute_reports:
                return

        super().handle_cluster_general_request(
            hdr,
            args,
            dst_addressing=dst_addressing,
        )


class AqaraFP300ManufacturerCluster(CustomCluster):
    """Aqara FP300 manufacturer cluster."""

    cluster_id = 0xFCC0
    ep_attribute = "aqara_fp300_manufacturer"

    BATTERY_VOLTAGE_TAG: Final = 0x17
    BATTERY_PERCENTAGE_TAG: Final = 0x18

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
        pir_detection_interval: Final = ZCLAttributeDef(
            id=0x014F,
            type=t.uint16_t,
            access="rwp",
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
        humidity_report_mode: Final = ZCLAttributeDef(
            id=0x016C,
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
        temp_humidity_sampling: Final = ZCLAttributeDef(
            id=0x0170,
            type=SamplingFrequency,
            zcl_type=DataTypeId.uint8,
            access="rwp",
            manufacturer_code=AQARA_MFG_CODE,
        )
        humidity_report_interval: Final = ZCLAttributeDef(
            id=0x016A,
            type=t.uint32_t,
            access="rwp",
            manufacturer_code=AQARA_MFG_CODE,
        )
        temp_humidity_sampling_period: Final = ZCLAttributeDef(
            id=0x0162,
            type=t.uint32_t,
            access="rwp",
            manufacturer_code=AQARA_MFG_CODE,
        )
        temperature_report_interval: Final = ZCLAttributeDef(
            id=0x0163,
            type=t.uint32_t,
            access="rwp",
            manufacturer_code=AQARA_MFG_CODE,
        )
        humidity_report_threshold: Final = ZCLAttributeDef(
            id=0x016B,
            type=t.uint16_t,
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
        led_indicator_off_schedule: Final = ZCLAttributeDef(
            id=0x0203,
            type=t.Bool,
            access="rwp",
            manufacturer_code=AQARA_MFG_CODE,
        )
        ai_spatial_learning: Final = ZCLAttributeDef(
            id=0x0157,
            type=t.uint8_t,
            access="w",
            manufacturer_code=AQARA_MFG_CODE,
        )
        restart_device: Final = ZCLAttributeDef(
            id=0x00E8,
            type=t.Bool,
            access="w",
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
            access="w",
            manufacturer_code=AQARA_MFG_CODE,
        )
        pir_detection: Final = ZCLAttributeDef(
            id=0x014D,
            type=t.Bool,
            zcl_type=DataTypeId.uint8,
            access="rp",
            manufacturer_code=AQARA_MFG_CODE,
        )
        init_token: Final = ZCLAttributeDef(
            id=0x00FF,
            type=t.LVBytes,
            access="w",
            manufacturer_code=AQARA_MFG_CODE,
        )
        detection_range_raw: Final = ZCLAttributeDef(
            id=0x019A,
            type=t.LVBytes,
            access="rwp",
            manufacturer_code=AQARA_MFG_CODE,
        )
        led_indicator_off_times_raw: Final = ZCLAttributeDef(
            id=0x023E,
            type=t.uint32_t,
            access="rwp",
            manufacturer_code=AQARA_MFG_CODE,
        )
        aqara_lifeline: Final = ZCLAttributeDef(
            id=0x00F7,
            type=t.LVBytes,
            access="rp",
            manufacturer_code=AQARA_MFG_CODE,
        )

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        """Initialize the FP300 manufacturer cluster."""
        super().__init__(*args, **kwargs)

        self.on_event(
            AttributeReportedEvent.event_type,
            self._handle_attribute_event,
        )

    def _handle_attribute_event(self, event: AttributeReportedEvent) -> None:
        """Handle FP300 manufacturer attribute reports."""
        attrid = event.attribute_id
        value = event.value

        if attrid == self.AttributeDefs.aqara_lifeline.id:
            values = self._parse_lifeline_report(value)
            power = self.endpoint.power

            if self.BATTERY_VOLTAGE_TAG in values:
                power.battery_voltage_reported(values[self.BATTERY_VOLTAGE_TAG])

            if self.BATTERY_PERCENTAGE_TAG in values:
                power.battery_percentage_reported(values[self.BATTERY_PERCENTAGE_TAG])

    def _parse_lifeline_report(self, data: bytes) -> dict[int, Any]:
        """Parse FP300 lifeline report."""
        values: dict[int, Any] = {}

        while len(data) >= 2:
            tag = data[0]

            try:
                typed_value, data = foundation.TypeValue.deserialize(data[1:])
            except ValueError:
                self.debug(
                    "Failed to deserialize FP300 lifeline tag 0x%02X from %r",
                    tag,
                    data,
                )
                return values

            values[tag] = typed_value.value

        return values

    @staticmethod
    def _generate_init_token() -> t.LVBytes:
        """Generate Aqara-style 16-byte BCD-like init token."""
        token = bytearray()

        for _ in range(16):
            high_decimal = random.randrange(10)
            low_decimal = random.randrange(10)
            token.append((high_decimal << 4) | low_decimal)

        return t.LVBytes(bytes(token))

    async def apply_custom_configuration(self, *args: Any, **kwargs: Any) -> None:
        """Apply FP300 custom configuration and populate raw attribute cache."""
        # 0x00FF is accepted by FP300, possibly part of Aqara init,
        # but no proven functional effect yet.
        try:
            await self.write_attributes(
                {self.AttributeDefs.init_token: self._generate_init_token()},
            )
        except Exception as exc:
            self.debug("Failed to write init token: %r", exc)

        for attr_def in (
            self.AttributeDefs.detection_range_raw,
            self.AttributeDefs.led_indicator_off_times_raw,
        ):
            try:
                await self.read_attributes(
                    [attr_def],
                    allow_cache=False,
                )
            except Exception as exc:
                self.debug("Failed to read attr 0x%04X: %r", attr_def.id, exc)


class FP300DetectionRangeNumber(BaseNumber):
    """Detection range number backed directly by detection_range_raw."""

    _attribute_name = (
        AqaraFP300ManufacturerCluster.AttributeDefs.detection_range_raw.name
    )
    _attr_native_min_value: float = 0.0
    _attr_native_max_value: float = 6.0
    _attr_native_step: float = 0.25
    _attr_native_unit_of_measurement = UnitOfLength.METERS
    _attr_device_class = NumberDeviceClass.DISTANCE
    _attr_mode = NumberMode.SLIDER

    def on_add(self) -> None:
        """Run when entity is added."""
        super().on_add()

        for event_type in (
            AttributeReadEvent,
            AttributeReportedEvent,
            AttributeWrittenEvent,
        ):
            self._on_remove_callbacks.append(
                self._cluster.on_event(
                    event_type.event_type,
                    self.handle_attribute_updated,
                )
            )

    def handle_attribute_updated(
        self,
        event: (AttributeReadEvent | AttributeReportedEvent | AttributeWrittenEvent),
    ) -> None:
        """Handle detection_range_raw value updates."""
        if event.attribute_name == self._attribute_name:
            self.maybe_emit_state_changed_event()

    @classmethod
    def _decode(cls, raw: bytes) -> float | None:
        """Decode raw detection range value into meters."""
        if len(raw) != 5:
            return None

        mask = int.from_bytes(raw[2:5], "little")
        return mask.bit_length() * cls._attr_native_step

    @classmethod
    def _encode(cls, value: float) -> t.LVBytes:
        """Encode detection range in meters into raw value."""
        max_steps = round(cls._attr_native_max_value / cls._attr_native_step)
        steps = max(0, min(max_steps, round(value / cls._attr_native_step)))
        mask = (1 << steps) - 1

        return t.LVBytes(b"\x00\x03" + mask.to_bytes(3, "little"))

    @property
    def native_value(self) -> float | None:
        """Return detection range in meters."""
        raw = self._cluster.get(self._attribute_name)

        if raw is None:
            return self._attr_native_max_value

        return self._decode(bytes(raw))

    async def async_set_native_value(self, value: float) -> None:
        """Write detection range through detection_range_raw."""
        await write_attributes_safe(
            self._cluster,
            {self._attribute_name: self._encode(value)},
        )
        self.maybe_emit_state_changed_event()

    async def async_update(self) -> None:
        """Read detection_range_raw from the device."""
        await safe_read(
            self._cluster,
            [self._attribute_name],
            allow_cache=False,
            only_cache=False,
        )
        self.maybe_emit_state_changed_event()


class FP300LedIndicatorOffTimeSelect(BaseSelectEntity, PlatformEntity):
    """LED trigger indicator off time select backed by led_indicator_off_times_raw."""

    _DEFAULT_START_HOUR: Final = 21
    _DEFAULT_END_HOUR: Final = 9

    _attribute_name = (
        AqaraFP300ManufacturerCluster.AttributeDefs.led_indicator_off_times_raw.name
    )
    _attr_options = [f"{hour:02d}:00" for hour in range(24)]

    def __init__(
        self,
        *args: Any,
        time_field: Literal["start", "end"],
        **kwargs: Any,
    ) -> None:
        """Initialize the LED trigger indicator off time select."""
        super().__init__(*args, **kwargs)
        self._time_field = time_field

    def on_add(self) -> None:
        """Run when entity is added."""
        super().on_add()

        for event_type in (
            AttributeReadEvent,
            AttributeReportedEvent,
            AttributeWrittenEvent,
        ):
            self._on_remove_callbacks.append(
                self._cluster.on_event(
                    event_type.event_type,
                    self.handle_attribute_updated,
                )
            )

    def handle_attribute_updated(
        self,
        event: (AttributeReadEvent | AttributeReportedEvent | AttributeWrittenEvent),
    ) -> None:
        """Handle led_indicator_off_times_raw value updates."""
        if event.attribute_name == self._attribute_name:
            self.maybe_emit_state_changed_event()

    def restore_external_state_attributes(
        self,
        *,
        state: str | None = None,
        **kwargs: Any,
    ) -> None:
        """Do not restore select state outside the ZCL cache."""

    @functools.cached_property
    def info_object(self) -> EnumSelectInfo:
        """Return a representation of the select."""
        return EnumSelectInfo(
            **super().info_object.__dict__,
            enum="FP300LedIndicatorOffTime",
            options=self.options,
        )

    @staticmethod
    def _decode(raw: int) -> tuple[int, int]:
        """Decode raw LED trigger indicator off time into start and end hours."""
        return raw & 0xFF, (raw >> 16) & 0xFF

    @staticmethod
    def _encode(start: int, end: int) -> int:
        """Encode start and end hours with both minute fields set to 00."""
        return start | (end << 16)

    @property
    def current_option(self) -> str | None:
        """Return this LED trigger indicator off time as a select option."""
        raw = self._cluster.get(self._attribute_name)

        if raw is None:
            hour = (
                self._DEFAULT_START_HOUR
                if self._time_field == "start"
                else self._DEFAULT_END_HOUR
            )
            return self.options[hour]

        start, end = self._decode(raw)
        hour = start if self._time_field == "start" else end

        if 0 <= hour < len(self.options):
            return self.options[hour]

        return None

    async def async_select_option(self, option: str) -> None:
        """Write this LED trigger indicator off time through the raw attribute."""
        hour = self.options.index(option)
        raw = self._cluster.get(self._attribute_name)

        if raw is None:
            start = self._DEFAULT_START_HOUR
            end = self._DEFAULT_END_HOUR
        else:
            start, end = self._decode(raw)

        if self._time_field == "start":
            start = hour
        else:
            end = hour

        await write_attributes_safe(
            self._cluster,
            {self._attribute_name: self._encode(start, end)},
        )
        self.maybe_emit_state_changed_event()


class AqaraFP300Device(QuirkV2Device):
    """Aqara FP300 QuirkBuilder device with direct raw-backed entities."""

    def discover_entities(self) -> Iterator[BaseEntity]:
        """Yield QuirkBuilder entities and direct raw-backed FP300 entities."""
        yield from super().discover_entities()

        endpoint = self.endpoints[1]
        cluster = endpoint.zigpy_endpoint.in_clusters[
            AqaraFP300ManufacturerCluster.cluster_id
        ]

        yield FP300DetectionRangeNumber(
            endpoint=endpoint,
            device=self,
            cluster=cluster,
            from_quirk=True,
            entity_type=EntityType.CONFIG,
            unique_id_suffix="detection_range",
            translation_key="detection_range",
            fallback_name="Detection range",
        )
        yield FP300LedIndicatorOffTimeSelect(
            endpoint=endpoint,
            device=self,
            cluster=cluster,
            from_quirk=True,
            entity_type=EntityType.CONFIG,
            unique_id_suffix="led_indicator_off_start_time",
            translation_key="led_trigger_indicator_off_start_time",
            fallback_name="LED trigger indicator off start time",
            time_field="start",
        )
        yield FP300LedIndicatorOffTimeSelect(
            endpoint=endpoint,
            device=self,
            cluster=cluster,
            from_quirk=True,
            entity_type=EntityType.CONFIG,
            unique_id_suffix="led_indicator_off_end_time",
            translation_key="led_trigger_indicator_off_end_time",
            fallback_name="LED trigger indicator off end time",
            time_field="end",
        )


(
    QuirkBuilder("Aqara", "lumi.sensor_occupy.agl8")
    .friendly_name(manufacturer="Aqara", model="Presence Multi-Sensor FP300")
    .zha_device_class(AqaraFP300Device)
    .replaces(AqaraFP300ManufacturerCluster)
    .replaces(FP300PowerConfigurationCluster)
    .binary_sensor(
        attribute_name="presence",
        cluster_id=AqaraFP300ManufacturerCluster.cluster_id,
        device_class=BinarySensorDeviceClass.OCCUPANCY,
        entity_type=EntityType.STANDARD,
        primary=True,
        reporting_config=ReportingConfig(
            min_interval=0,
            max_interval=900,
            reportable_change=1,
        ),
        translation_key="occupancy",
        fallback_name="Occupancy",
    )
    .enum(
        attribute_name="presence_detection_mode",
        enum_class=PresenceDetectionMode,
        cluster_id=AqaraFP300ManufacturerCluster.cluster_id,
        translation_key="presence_detection_mode",
        fallback_name="Presence detection mode",
    )
    .number(
        attribute_name="absence_delay",
        cluster_id=AqaraFP300ManufacturerCluster.cluster_id,
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
        cluster_id=AqaraFP300ManufacturerCluster.cluster_id,
        translation_key="presence_sensitivity",
        fallback_name="Presence sensitivity",
    )
    .number(
        attribute_name="pir_detection_interval",
        cluster_id=AqaraFP300ManufacturerCluster.cluster_id,
        device_class=NumberDeviceClass.DURATION,
        min_value=2,
        max_value=300,
        step=1,
        unit=UnitOfTime.SECONDS,
        translation_key="pir_detection_interval",
        fallback_name="PIR detection interval",
    )
    .switch(
        attribute_name="ai_interference_source_self_identification",
        cluster_id=AqaraFP300ManufacturerCluster.cluster_id,
        translation_key="ai_interference_source_self_identification",
        fallback_name="AI interference source self-identification",
    )
    .switch(
        attribute_name="ai_adaptive_sensitivity",
        cluster_id=AqaraFP300ManufacturerCluster.cluster_id,
        translation_key="ai_adaptive_sensitivity",
        fallback_name="AI adaptive sensitivity",
    )
    .number(
        attribute_name="light_report_threshold",
        cluster_id=AqaraFP300ManufacturerCluster.cluster_id,
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
        cluster_id=AqaraFP300ManufacturerCluster.cluster_id,
        translation_key="light_sampling",
        fallback_name="Light sampling",
    )
    .enum(
        attribute_name="light_report_mode",
        enum_class=ReportMode,
        cluster_id=AqaraFP300ManufacturerCluster.cluster_id,
        translation_key="light_report_mode",
        fallback_name="Light report mode",
    )
    .number(
        attribute_name="light_sampling_period",
        cluster_id=AqaraFP300ManufacturerCluster.cluster_id,
        device_class=NumberDeviceClass.DURATION,
        min_value=0.5,
        max_value=3600,
        step=0.5,
        multiplier=1 / 1000,
        unit=UnitOfTime.SECONDS,
        translation_key="light_sampling_period",
        fallback_name="Light sampling period",
    )
    .number(
        attribute_name="light_report_interval",
        cluster_id=AqaraFP300ManufacturerCluster.cluster_id,
        device_class=NumberDeviceClass.DURATION,
        min_value=20,
        max_value=3600,
        step=1,
        multiplier=1 / 1000,
        unit=UnitOfTime.SECONDS,
        translation_key="light_report_interval",
        fallback_name="Light report interval",
    )
    .enum(
        attribute_name="humidity_report_mode",
        enum_class=ReportMode,
        cluster_id=AqaraFP300ManufacturerCluster.cluster_id,
        translation_key="humidity_report_mode",
        fallback_name="Humidity report mode",
    )
    .number(
        attribute_name="temperature_report_threshold",
        cluster_id=AqaraFP300ManufacturerCluster.cluster_id,
        device_class=NumberDeviceClass.TEMPERATURE,
        min_value=0.2,
        max_value=3.0,
        step=0.1,
        multiplier=0.01,
        unit=UnitOfTemperature.CELSIUS,
        translation_key="temperature_report_threshold",
        fallback_name="Temperature report threshold",
    )
    .enum(
        attribute_name="temp_humidity_sampling",
        enum_class=SamplingFrequency,
        cluster_id=AqaraFP300ManufacturerCluster.cluster_id,
        translation_key="temp_humidity_sampling",
        fallback_name="Temperature and humidity sampling",
    )
    .number(
        attribute_name="humidity_report_interval",
        cluster_id=AqaraFP300ManufacturerCluster.cluster_id,
        device_class=NumberDeviceClass.DURATION,
        min_value=600,
        max_value=3600,
        step=1,
        multiplier=1 / 1000,
        unit=UnitOfTime.SECONDS,
        translation_key="humidity_report_interval",
        fallback_name="Humidity report interval",
    )
    .number(
        attribute_name="temp_humidity_sampling_period",
        cluster_id=AqaraFP300ManufacturerCluster.cluster_id,
        device_class=NumberDeviceClass.DURATION,
        min_value=0.5,
        max_value=3600,
        step=0.5,
        multiplier=1 / 1000,
        unit=UnitOfTime.SECONDS,
        translation_key="temp_humidity_sampling_period",
        fallback_name="Temperature and humidity sampling period",
    )
    .number(
        attribute_name="temperature_report_interval",
        cluster_id=AqaraFP300ManufacturerCluster.cluster_id,
        device_class=NumberDeviceClass.DURATION,
        min_value=600,
        max_value=3600,
        step=1,
        multiplier=1 / 1000,
        unit=UnitOfTime.SECONDS,
        translation_key="temperature_report_interval",
        fallback_name="Temperature report interval",
    )
    .number(
        attribute_name="humidity_report_threshold",
        cluster_id=AqaraFP300ManufacturerCluster.cluster_id,
        device_class=NumberDeviceClass.HUMIDITY,
        min_value=2.0,
        max_value=15.0,
        step=0.5,
        multiplier=0.01,
        unit=PERCENTAGE,
        translation_key="humidity_report_threshold",
        fallback_name="Humidity report threshold",
    )
    .enum(
        attribute_name="temperature_report_mode",
        enum_class=ReportMode,
        cluster_id=AqaraFP300ManufacturerCluster.cluster_id,
        translation_key="temperature_report_mode",
        fallback_name="Temperature report mode",
    )
    .switch(
        attribute_name="led_indicator_off_schedule",
        cluster_id=AqaraFP300ManufacturerCluster.cluster_id,
        translation_key="led_trigger_indicator_off_schedule",
        fallback_name="LED trigger indicator off schedule",
    )
    .write_attr_button(
        attribute_name="ai_spatial_learning",
        attribute_value=1,
        cluster_id=AqaraFP300ManufacturerCluster.cluster_id,
        translation_key="ai_spatial_learning",
        fallback_name="AI spatial learning",
    )
    .write_attr_button(
        attribute_name="restart_device",
        attribute_value=1,
        cluster_id=AqaraFP300ManufacturerCluster.cluster_id,
        initially_disabled=True,
        translation_key="restart_device",
        fallback_name="Restart",
    )
    .sensor(
        attribute_name="target_distance",
        cluster_id=AqaraFP300ManufacturerCluster.cluster_id,
        device_class=SensorDeviceClass.DISTANCE,
        state_class=SensorStateClass.MEASUREMENT,
        unit=UnitOfLength.METERS,
        multiplier=0.01,
        entity_type=EntityType.DIAGNOSTIC,
        translation_key="target_distance",
        fallback_name="Target distance",
    )
    .write_attr_button(
        attribute_name="track_target_distance",
        attribute_value=1,
        cluster_id=AqaraFP300ManufacturerCluster.cluster_id,
        translation_key="track_target_distance",
        fallback_name="Track target distance",
    )
    .binary_sensor(
        attribute_name="pir_detection",
        cluster_id=AqaraFP300ManufacturerCluster.cluster_id,
        device_class=BinarySensorDeviceClass.MOTION,
        initially_disabled=True,
        reporting_config=ReportingConfig(
            min_interval=0,
            max_interval=900,
            reportable_change=1,
        ),
        translation_key="pir_detection",
        fallback_name="PIR detection",
    )
    .sensor(
        attribute_name="battery_voltage",
        cluster_id=FP300PowerConfigurationCluster.cluster_id,
        device_class=SensorDeviceClass.VOLTAGE,
        state_class=SensorStateClass.MEASUREMENT,
        unit=UnitOfElectricPotential.VOLT,
        multiplier=0.1,
        entity_type=EntityType.DIAGNOSTIC,
        initially_disabled=True,
        translation_key="battery_voltage",
        fallback_name="Battery voltage",
    )
    .add_to_registry()
)
