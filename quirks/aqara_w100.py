"""Quirk for Aqara Climate Sensor W100 (lumi.sensor_ht.agl001).

The W100 is a remote control, not an HVAC thermostat. The quirk exposes a
virtual climate entity and mirrors its state to and from the W100.

Climate state changes and external sensor values are mirrored to the W100
only while the corresponding Thermostat control or External sensor mode is
enabled. When a mode is disabled, changes are stored locally in Home Assistant
and used when the corresponding mode is enabled again.

When updating or replacing the quirk, or moving the W100 between Zigbee
platforms, perform a factory reset before pairing it again. Press the Reset
button 10 times to restore the W100 to factory default settings.

Fan mode Off is a virtual state that hides the fan indicator on the W100
display; it is not a native W100 fan mode.
"""

import functools
import struct
import time

from collections.abc import Iterator
from typing import Any, Final

from zha.application.helpers import safe_read
from zha.application.platforms import BaseEntity, EntityCategory, PlatformEntity
from zha.application.platforms.climate import BaseThermostat, ThermostatEntityInfo
from zha.application.platforms.climate.const import (
    ClimateEntityFeature,
    FAN_AUTO,
    FAN_HIGH,
    FAN_LOW,
    FAN_MEDIUM,
    FAN_OFF,
    HVACAction,
    HVACMode,
    PRECISION_TENTHS,
    ZCL_TEMP,
)
from zha.application.platforms.number.const import NumberMode
from zha.application.platforms.switch import BaseSwitch
from zha.exceptions import ZHAException
from zhaquirks import CustomCluster, LocalDataCluster
from zhaquirks.builder import (
    EntityPlatform,
    EntityType,
    NumberDeviceClass,
    PERCENTAGE,
    QuirkBuilder,
    UnitOfTemperature,
    UnitOfTime,
)
from zhaquirks.builder.device import QuirkV2Device
from zhaquirks.const import (
    ATTR_ID,
    COMMAND,
    COMMAND_DOUBLE,
    COMMAND_HOLD,
    COMMAND_RELEASE,
    COMMAND_SINGLE,
    DOUBLE_PRESS,
    ENDPOINT_ID,
    LONG_PRESS,
    LONG_RELEASE,
    PRESS_TYPE,
    SHORT_PRESS,
    VALUE,
    ZHA_SEND_EVENT,
)
from zigpy import types as t
from zigpy.zcl import (
    AttributeReadEvent,
    AttributeReportedEvent,
    AttributeUpdatedEvent,
    AttributeWrittenEvent,
    foundation,
)
from zigpy.zcl.clusters.general import MultistateInput, PowerConfiguration
from zigpy.zcl.clusters.hvac import Fan, Thermostat
from zigpy.zcl.clusters.measurement import TemperatureMeasurement
from zigpy.zcl.foundation import BaseAttributeDefs, DataTypeId, ZCLAttributeDef


AQARA_MFG_CODE: Final = 0x115F
THERMOSTAT_ON_BIT: Final = 0x01
EXTERNAL_SENSOR_ON_BIT: Final = 0x02


class SamplingFrequency(t.enum8):
    """Temperature and humidity sampling frequency."""

    Low = 1
    Medium = 2
    High = 3
    Custom = 4


class ReportMode(t.enum8):
    """Temperature or humidity report mode."""

    Off = 0
    Threshold = 1
    Interval = 2
    Threshold_and_interval = 3


class TempHumidityStatus(t.enum8):
    """Temperature or humidity status."""

    Normal = 0
    High = 1
    Low = 2


class W100PowerConfigurationCluster(PowerConfiguration, LocalDataCluster):
    """W100 power cluster."""

    def battery_percent_reported(self, value: int) -> None:
        """Update battery percentage from a 0-100 report."""
        self._update_attribute(
            self.AttributeDefs.battery_percentage_remaining.id,
            max(0, min(100, value)) * 2,
        )


class W100CommandRawCodec:
    """W100 command_raw helpers."""

    THERMOSTAT_MARKER: Final[bytes] = bytes.fromhex("08000844")
    EXTERNAL_TEMPERATURE_MARKER: Final[bytes] = bytes.fromhex("00010055")
    EXTERNAL_HUMIDITY_MARKER: Final[bytes] = bytes.fromhex("00020055")

    SYSTEM_MODE_TO_W100_MODE: Final[dict[int, int]] = {
        Thermostat.SystemMode.Cool: 0,
        Thermostat.SystemMode.Heat: 1,
        Thermostat.SystemMode.Auto: 2,
    }

    W100_MODE_TO_SYSTEM_MODE: Final[dict[int, int]] = {
        value: key for key, value in SYSTEM_MODE_TO_W100_MODE.items()
    }

    FAN_MODE_TO_W100_FAN_MODE: Final[dict[int, int]] = {
        Fan.FanMode.Auto: 0,
        Fan.FanMode.Low: 1,
        Fan.FanMode.Medium: 2,
        Fan.FanMode.High: 3,
    }

    W100_FAN_MODE_TO_FAN_MODE: Final[dict[int, int]] = {
        value: key for key, value in FAN_MODE_TO_W100_FAN_MODE.items()
    }

    @classmethod
    def parse_thermostat_payload(
        cls,
        payload: bytes,
    ) -> dict[str, int | float]:
        """Parse thermostat updates from a W100 payload."""
        data = payload.split(cls.THERMOSTAT_MARKER, 1)[1]
        raw_value, _ = t.LVBytes.deserialize(data)
        raw_str = bytes(raw_value).decode("ascii").rstrip("\x00")

        updates: dict[str, int | float] = {}

        for part in raw_str.split("_"):
            if len(part) < 2:
                continue

            key = part[0].lower()
            value = part[1:]

            if key == "t":
                updates[key] = float(value)
            elif key in ("p", "m", "s"):
                updates[key] = int(value)

        return updates

    @classmethod
    def build_thermostat_update_frame(
        cls,
        *,
        p: int,
        m: Thermostat.SystemMode,
        t: float,
        s: Fan.FanMode | None,
        hub_mac: bytes,
    ) -> bytes:
        """Build a thermostat update command_raw frame."""
        parts = [
            f"P{p}",
            f"M{cls.SYSTEM_MODE_TO_W100_MODE[m]}",
            f"T{int(t)}",
        ]

        if s is not None:
            parts.append(f"S{cls.FAN_MODE_TO_W100_FAN_MODE[s]}")

        ascii_payload = "_".join(parts).encode("ascii")

        command_payload = (
            b"\x00\x00"
            + hub_mac
            + cls.THERMOSTAT_MARKER
            + bytes([len(ascii_payload)])
            + ascii_payload
            + b"\x00"
        )

        return cls._build_frame_header(len(command_payload), 0x05) + command_payload

    @classmethod
    def build_external_sensor_update_frame(
        cls,
        *,
        marker: bytes,
        raw_value: int,
        fictive_sensor_mac: bytes,
    ) -> bytes:
        """Build an external sensor update command_raw frame."""
        encoded = struct.pack(">f", float(raw_value))

        payload = fictive_sensor_mac + marker + encoded
        return cls._build_frame_header(len(payload), 0x05) + payload

    @classmethod
    def build_thermostat_control_frame(
        cls,
        *,
        enabled: bool,
        device_ieee: bytes,
    ) -> bytes:
        """Build a thermostat control command_raw frame."""
        command_prefix = bytes.fromhex("6891") + b"\x00\x00" + b"\x18"

        if enabled:
            hub_mac = device_ieee[:6]
            command_payload = (
                command_prefix
                + device_ieee
                + b"\x00\x00"
                + hub_mac
                + bytes.fromhex("08000844150a0109e7a9bae8b083e58a9f000000000001012a40")
            )
            return cls._build_frame_header(len(command_payload), 0x02) + command_payload

        command_payload = command_prefix + device_ieee + bytes(12)
        return cls._build_frame_header(len(command_payload), 0x04) + command_payload

    @classmethod
    def build_external_sensor_frame(
        cls,
        *,
        enabled: bool,
        device_ieee: bytes,
        timestamp: int,
    ) -> list[bytes]:
        """Build external sensor command_raw frames."""
        fictive_sensor_mac = device_ieee[:-1] + bytes([device_ieee[-1] ^ 0x01])
        timestamp_bytes = timestamp.to_bytes(4, "big")
        humidity_channel = b"\x15"
        temperature_channel = b"\x14"

        if enabled:
            humidity_payload = (
                timestamp_bytes
                + humidity_channel
                + device_ieee
                + fictive_sensor_mac
                + bytes.fromhex("00020055150a0100000106e6b9bfe5baa6000000000001020865")
            )
            temperature_payload = (
                timestamp_bytes
                + temperature_channel
                + device_ieee
                + fictive_sensor_mac
                + bytes.fromhex("00010055150a0100000106e6b8a9e5baa6000000000001020763")
            )
            action = 0x02
        else:
            humidity_payload = (
                timestamp_bytes + humidity_channel + device_ieee + bytes(12)
            )
            temperature_payload = (
                timestamp_bytes + temperature_channel + device_ieee + bytes(12)
            )
            action = 0x04

        humidity_command = (
            cls._build_frame_header(len(humidity_payload), action) + humidity_payload
        )
        temperature_command = (
            cls._build_frame_header(len(temperature_payload), action)
            + temperature_payload
        )

        return [humidity_command, temperature_command]

    @classmethod
    def _build_frame_header(cls, payload_len: int, action: int) -> bytes:
        """Build a W100-style command_raw frame header."""
        prefix = [0xAA, 0x71, payload_len + 3, 0x44, 0x00]
        checksum = (-sum(prefix)) & 0xFF
        return bytes([*prefix, checksum, action, 0x41, payload_len])


class W100ManuCluster(CustomCluster):
    """Aqara W100 manufacturer cluster."""

    cluster_id = 0xFCC0
    ep_attribute = "w100_manu"

    BATTERY_PERCENTAGE_TAG: Final = 102

    class AttributeDefs(BaseAttributeDefs):
        """Attribute definitions."""

        low_temperature: Final = ZCLAttributeDef(
            id=0x0166,
            type=t.int16s,
            access="rwp",
            manufacturer_code=AQARA_MFG_CODE,
        )
        high_temperature: Final = ZCLAttributeDef(
            id=0x0167,
            type=t.int16s,
            access="rwp",
            manufacturer_code=AQARA_MFG_CODE,
        )
        low_humidity: Final = ZCLAttributeDef(
            id=0x016D,
            type=t.int16s,
            access="rwp",
            manufacturer_code=AQARA_MFG_CODE,
        )
        high_humidity: Final = ZCLAttributeDef(
            id=0x016E,
            type=t.int16s,
            access="rwp",
            manufacturer_code=AQARA_MFG_CODE,
        )
        temperature_status: Final = ZCLAttributeDef(
            id=0x0168,
            type=TempHumidityStatus,
            zcl_type=DataTypeId.uint8,
            access="rp",
            manufacturer_code=AQARA_MFG_CODE,
        )
        humidity_status: Final = ZCLAttributeDef(
            id=0x016F,
            type=TempHumidityStatus,
            zcl_type=DataTypeId.uint8,
            access="rp",
            manufacturer_code=AQARA_MFG_CODE,
        )
        temp_humidity_sampling: Final = ZCLAttributeDef(
            id=0x0170,
            type=SamplingFrequency,
            zcl_type=DataTypeId.uint8,
            access="rwp",
            manufacturer_code=AQARA_MFG_CODE,
        )
        temp_humidity_sampling_period: Final = ZCLAttributeDef(
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
        temperature_report_interval: Final = ZCLAttributeDef(
            id=0x0163,
            type=t.uint32_t,
            access="rwp",
            manufacturer_code=AQARA_MFG_CODE,
        )
        temperature_report_threshold: Final = ZCLAttributeDef(
            id=0x0164,
            type=t.uint16_t,
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
        humidity_report_interval: Final = ZCLAttributeDef(
            id=0x016A,
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
        thermostat_line_auto_hide: Final = ZCLAttributeDef(
            id=0x0173,
            type=t.Bool,
            access="rwp",
            manufacturer_code=AQARA_MFG_CODE,
        )
        mode_flags: Final = ZCLAttributeDef(
            id=0x0172,
            type=t.uint32_t,
            access="rp",
            manufacturer_code=AQARA_MFG_CODE,
        )
        command_raw: Final = ZCLAttributeDef(
            id=0xFFF2,
            type=t.LVBytes,
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
        """Initialize the W100 manufacturer cluster."""
        super().__init__(*args, **kwargs)
        self.on_event(
            AttributeReportedEvent.event_type,
            self._handle_attribute_event,
        )

    def _handle_attribute_event(
        self,
        event: AttributeReportedEvent,
    ) -> None:
        """Route W100 manufacturer attribute reports."""
        if event.attribute_id == self.AttributeDefs.command_raw.id:
            self.create_catching_task(
                self._handle_command_raw_report(bytes(event.value))
            )
            return

        if event.attribute_id == self.AttributeDefs.aqara_lifeline.id:
            values = self._parse_lifeline_report(event.value)

            if self.BATTERY_PERCENTAGE_TAG in values:
                self.endpoint.power.battery_percent_reported(
                    values[self.BATTERY_PERCENTAGE_TAG]
                )

    async def _handle_command_raw_report(self, payload: bytes) -> None:
        """Process a command_raw report."""
        if W100CommandRawCodec.THERMOSTAT_MARKER in payload:
            if payload.endswith(W100CommandRawCodec.THERMOSTAT_MARKER):
                await self.sync_thermostat()
            else:
                try:
                    updates = W100CommandRawCodec.parse_thermostat_payload(payload)
                except (ValueError, UnicodeDecodeError) as exc:
                    self.debug(
                        "Failed to parse W100 thermostat payload %s: %s",
                        payload.hex(),
                        exc,
                    )
                else:
                    if updates:
                        self.endpoint.w100_thermostat.update_from_w100(updates)

        # W100 reliably requests humidity but may skip temperature requests.
        # Send both cached external values on humidity request.
        if W100CommandRawCodec.EXTERNAL_HUMIDITY_MARKER in payload:
            await self.sync_external_sensor(
                W100ExternalSensorCluster.AttributeDefs.external_humidity.id,
                W100ExternalSensorCluster.AttributeDefs.external_temperature.id,
            )

    async def sync_thermostat(self) -> None:
        """Sync the cached thermostat state to the W100."""
        thermostat = self.endpoint.w100_thermostat
        device_ieee = self.endpoint.device.ieee.serialize()[::-1]

        system_mode = thermostat.get(W100ThermostatCluster.AttributeDefs.system_mode.id)

        if system_mode == Thermostat.SystemMode.Off:
            p = 1
            m = thermostat.get(W100ThermostatCluster.AttributeDefs.last_active_mode.id)
        else:
            p = 0
            m = system_mode

        t = thermostat.get(W100ThermostatCluster.AttributeDefs.target_temperature.id)

        s = thermostat.get(W100ThermostatCluster.AttributeDefs.fan_mode.id)

        if s == Fan.FanMode.Off:
            s = None

        command = W100CommandRawCodec.build_thermostat_update_frame(
            p=p,
            m=m,
            t=t,
            s=s,
            hub_mac=device_ieee[:6],
        )

        await self.write_command_raw(command)

    async def sync_external_sensor(self, *attrids: int) -> None:
        """Sync selected cached external sensor values to the W100."""
        external_sensor = self.endpoint.w100_external_sensor
        device_ieee = self.endpoint.device.ieee.serialize()[::-1]
        fictive_sensor_mac = device_ieee[:-1] + bytes([device_ieee[-1] ^ 0x01])

        for attrid in attrids:
            if attrid == W100ExternalSensorCluster.AttributeDefs.external_humidity.id:
                marker = W100CommandRawCodec.EXTERNAL_HUMIDITY_MARKER
            if (
                attrid
                == W100ExternalSensorCluster.AttributeDefs.external_temperature.id
            ):
                marker = W100CommandRawCodec.EXTERNAL_TEMPERATURE_MARKER

            command = W100CommandRawCodec.build_external_sensor_update_frame(
                marker=marker,
                raw_value=external_sensor.get(attrid),
                fictive_sensor_mac=fictive_sensor_mac,
            )

            await self.write_command_raw(command)

    async def write_command_raw(
        self,
        value: bytes,
    ) -> list[list[foundation.WriteAttributesStatusRecord]]:
        """Write command_raw with raw ZCL to bypass the 50-byte value limit."""
        attr_def = self.AttributeDefs.command_raw

        zcl_attr = foundation.Attribute(attr_def.id, foundation.TypeValue())
        zcl_attr.value.type = attr_def.zcl_type
        zcl_attr.value.value = attr_def.type(value)

        result = await self.write_attributes_raw(
            [zcl_attr],
            manufacturer_code=AQARA_MFG_CODE,
        )

        records = result[0]

        if isinstance(records, list):
            return [records]

        return [[foundation.WriteAttributesStatusRecord(records)]]

    def _parse_lifeline_report(self, data: bytes) -> dict[int, Any]:
        """Parse W100 lifeline report."""
        values: dict[int, Any] = {}

        while len(data) >= 2:
            tag = data[0]

            try:
                typed_value, data = foundation.TypeValue.deserialize(data[1:])
            except ValueError:
                self.debug(
                    "Failed to deserialize W100 lifeline tag 0x%02X from %r",
                    tag,
                    data,
                )
                return values

            values[tag] = typed_value.value

        return values

    async def apply_custom_configuration(self, *args: Any, **kwargs: Any) -> None:
        """Read mode flags during device configuration."""
        attr_def = self.AttributeDefs.mode_flags

        try:
            await self.read_attributes(
                [attr_def],
                allow_cache=False,
            )
        except Exception as exc:
            self.debug("Failed to read attr 0x%04X: %r", attr_def.id, exc)


class W100ThermostatCluster(LocalDataCluster):
    """W100 thermostat local state cluster."""

    cluster_id = 0xFCF5
    ep_attribute = "w100_thermostat"

    class AttributeDefs(BaseAttributeDefs):
        """Attribute definitions."""

        system_mode: Final = ZCLAttributeDef(
            id=0x5001,
            type=Thermostat.SystemMode,
            manufacturer_code=None,
        )
        target_temperature: Final = ZCLAttributeDef(
            id=0x5007,
            type=t.Single,
            manufacturer_code=None,
        )
        fan_mode: Final = ZCLAttributeDef(
            id=0x5005,
            type=Fan.FanMode,
            manufacturer_code=None,
        )
        last_active_mode: Final = ZCLAttributeDef(
            id=0x5006,
            type=Thermostat.SystemMode,
            manufacturer_code=None,
        )

    _DEFAULT_VALUES: Final = {
        AttributeDefs.system_mode.id: Thermostat.SystemMode.Off,
        AttributeDefs.target_temperature.id: 20.0,
        AttributeDefs.fan_mode.id: Fan.FanMode.Off,
        AttributeDefs.last_active_mode.id: Thermostat.SystemMode.Heat,
    }

    _TARGET_TEMPERATURE_SYNC_MODES = {
        Thermostat.SystemMode.Heat,
        Thermostat.SystemMode.Cool,
    }

    def update_from_w100(self, updates: dict[str, int | float]) -> None:
        """Apply W100 thermostat updates to local attributes."""
        if "m" in updates:
            m = W100CommandRawCodec.W100_MODE_TO_SYSTEM_MODE[updates["m"]]
            self._update_attribute(self.AttributeDefs.system_mode.id, m)
            self._update_attribute(self.AttributeDefs.last_active_mode.id, m)

        if "t" in updates:
            t = round(float(updates["t"]), 1)
            self._update_attribute(self.AttributeDefs.target_temperature.id, t)

        if "s" in updates:
            s = W100CommandRawCodec.W100_FAN_MODE_TO_FAN_MODE[updates["s"]]
            self._update_attribute(self.AttributeDefs.fan_mode.id, s)

        if "p" in updates:
            p = updates["p"]

            if p == 1:
                self._update_attribute(
                    self.AttributeDefs.system_mode.id,
                    Thermostat.SystemMode.Off,
                )

            elif p == 0:
                self._update_attribute(
                    self.AttributeDefs.system_mode.id,
                    self.get(self.AttributeDefs.last_active_mode.id),
                )

    async def write_attributes(
        self,
        attributes: dict[str | int | foundation.ZCLAttributeDef, Any],
        **kwargs: Any,
    ) -> list[list[foundation.WriteAttributesStatusRecord]]:
        """Write local thermostat attributes and sync the W100."""
        attrids = {self.find_attribute(attr).id for attr in attributes}
        result = await super().write_attributes(attributes, **kwargs)

        system_mode_id = self.AttributeDefs.system_mode.id
        system_mode = self.get(system_mode_id)

        if system_mode_id in attrids and system_mode != Thermostat.SystemMode.Off:
            self._update_attribute(
                self.AttributeDefs.last_active_mode.id,
                system_mode,
            )

        if (
            system_mode_id in attrids
            or (
                self.AttributeDefs.target_temperature.id in attrids
                and system_mode in self._TARGET_TEMPERATURE_SYNC_MODES
            )
            or (
                self.AttributeDefs.fan_mode.id in attrids
                and system_mode != Thermostat.SystemMode.Off
            )
        ):
            mode_flags = self.endpoint.w100_manu.get(
                W100ManuCluster.AttributeDefs.mode_flags.id
            )

            if mode_flags is not None and (mode_flags & THERMOSTAT_ON_BIT):
                self.create_catching_task(self.endpoint.w100_manu.sync_thermostat())

        return result


class W100ExternalSensorCluster(LocalDataCluster):
    """W100 external sensor local state cluster."""

    cluster_id = 0xFCF6
    ep_attribute = "w100_external_sensor"

    class AttributeDefs(BaseAttributeDefs):
        """Attribute definitions."""

        external_temperature: Final = ZCLAttributeDef(
            id=0x0000,
            type=t.int16s,
            manufacturer_code=None,
        )
        external_humidity: Final = ZCLAttributeDef(
            id=0x0001,
            type=t.uint16_t,
            manufacturer_code=None,
        )

    _DEFAULT_VALUES = {
        AttributeDefs.external_temperature.id: 2000,
        AttributeDefs.external_humidity.id: 5000,
    }

    async def write_attributes(
        self,
        attributes: dict[str | int | foundation.ZCLAttributeDef, Any],
        **kwargs: Any,
    ) -> list[list[foundation.WriteAttributesStatusRecord]]:
        """Write local external sensor attributes and sync written values."""
        result = await super().write_attributes(attributes, **kwargs)

        mode_flags = self.endpoint.w100_manu.get(
            W100ManuCluster.AttributeDefs.mode_flags.id
        )

        if mode_flags is None or not (mode_flags & EXTERNAL_SENSOR_ON_BIT):
            return result

        for attr in attributes:
            attrid = self.find_attribute(attr).id

            if attrid in (
                self.AttributeDefs.external_temperature.id,
                self.AttributeDefs.external_humidity.id,
            ):
                self.create_catching_task(
                    self.endpoint.w100_manu.sync_external_sensor(attrid)
                )

        return result


class W100ButtonCluster(CustomCluster, MultistateInput):
    """W100 button events for plus, center, and minus buttons."""

    PRESENT_VALUE_ATTR_ID: Final = MultistateInput.AttributeDefs.present_value.id

    PLUS_BUTTON: Final = "plus"
    CENTER_BUTTON: Final = "center"
    MINUS_BUTTON: Final = "minus"

    PRESS_TYPES: Final = {
        0: COMMAND_HOLD,
        1: COMMAND_SINGLE,
        2: COMMAND_DOUBLE,
        255: COMMAND_RELEASE,
    }

    ENDPOINT_BUTTONS: Final = {
        1: PLUS_BUTTON,
        2: CENTER_BUTTON,
        3: MINUS_BUTTON,
    }

    @classmethod
    def automation_triggers(cls) -> dict:
        """Return W100 button automation triggers."""
        return {
            (SHORT_PRESS, cls.PLUS_BUTTON): {COMMAND: COMMAND_SINGLE, ENDPOINT_ID: 1},
            (DOUBLE_PRESS, cls.PLUS_BUTTON): {COMMAND: COMMAND_DOUBLE, ENDPOINT_ID: 1},
            (LONG_PRESS, cls.PLUS_BUTTON): {COMMAND: COMMAND_HOLD, ENDPOINT_ID: 1},
            (LONG_RELEASE, cls.PLUS_BUTTON): {COMMAND: COMMAND_RELEASE, ENDPOINT_ID: 1},
            (SHORT_PRESS, cls.CENTER_BUTTON): {COMMAND: COMMAND_SINGLE, ENDPOINT_ID: 2},
            (DOUBLE_PRESS, cls.CENTER_BUTTON): {
                COMMAND: COMMAND_DOUBLE,
                ENDPOINT_ID: 2,
            },
            (LONG_PRESS, cls.CENTER_BUTTON): {COMMAND: COMMAND_HOLD, ENDPOINT_ID: 2},
            (LONG_RELEASE, cls.CENTER_BUTTON): {
                COMMAND: COMMAND_RELEASE,
                ENDPOINT_ID: 2,
            },
            (SHORT_PRESS, cls.MINUS_BUTTON): {COMMAND: COMMAND_SINGLE, ENDPOINT_ID: 3},
            (DOUBLE_PRESS, cls.MINUS_BUTTON): {COMMAND: COMMAND_DOUBLE, ENDPOINT_ID: 3},
            (LONG_PRESS, cls.MINUS_BUTTON): {COMMAND: COMMAND_HOLD, ENDPOINT_ID: 3},
            (LONG_RELEASE, cls.MINUS_BUTTON): {
                COMMAND: COMMAND_RELEASE,
                ENDPOINT_ID: 3,
            },
        }

    def _update_attribute(self, attrid: int, value: Any) -> None:
        """Emit button events from present_value updates."""
        super()._update_attribute(attrid, value)

        if attrid == self.PRESENT_VALUE_ATTR_ID:
            press_type = self.PRESS_TYPES.get(value, f"unknown_{value}")
            button = self.ENDPOINT_BUTTONS.get(
                self.endpoint.endpoint_id,
                f"ep{self.endpoint.endpoint_id}",
            )

            self.listener_event(
                ZHA_SEND_EVENT,
                press_type,
                {
                    "button": button,
                    PRESS_TYPE: press_type,
                    ENDPOINT_ID: self.endpoint.endpoint_id,
                    ATTR_ID: attrid,
                    VALUE: value,
                },
            )


class W100ThermostatControlSwitch(PlatformEntity, BaseSwitch):
    """W100 thermostat control switch."""

    _attribute_name = W100ManuCluster.AttributeDefs.mode_flags.name
    _attr_entity_category = EntityCategory.CONFIG

    def on_add(self) -> None:
        """Run when entity is added."""
        super().on_add()

        for event_type in (
            AttributeReadEvent,
            AttributeReportedEvent,
            AttributeUpdatedEvent,
            AttributeWrittenEvent,
        ):
            self._on_remove_callbacks.append(
                self._cluster.on_event(
                    event_type.event_type,
                    self._handle_mode_flags_event,
                )
            )

    @property
    def is_on(self) -> bool:
        """Return if thermostat control is enabled on the device."""
        mode_flags = self._cluster.get(self._attribute_name)
        return bool(mode_flags and mode_flags & THERMOSTAT_ON_BIT)

    async def async_turn_on(self) -> None:
        """Turn thermostat control on."""
        result = await self._cluster.write_command_raw(
            W100CommandRawCodec.build_thermostat_control_frame(
                enabled=True,
                device_ieee=self._cluster.endpoint.device.ieee.serialize()[::-1],
            )
        )
        status = result[0][0].status

        if status is not foundation.Status.SUCCESS:
            raise ZHAException(f"Failed to turn thermostat control on: {status}")

    async def async_turn_off(self) -> None:
        """Turn thermostat control off."""
        result = await self._cluster.write_command_raw(
            W100CommandRawCodec.build_thermostat_control_frame(
                enabled=False,
                device_ieee=self._cluster.endpoint.device.ieee.serialize()[::-1],
            )
        )
        status = result[0][0].status

        if status is not foundation.Status.SUCCESS:
            raise ZHAException(f"Failed to turn thermostat control off: {status}")

    def _handle_mode_flags_event(
        self,
        event: AttributeReadEvent
        | AttributeReportedEvent
        | AttributeUpdatedEvent
        | AttributeWrittenEvent,
    ) -> None:
        """Handle mode_flags attribute events."""
        if event.attribute_name == self._attribute_name:
            self.maybe_emit_state_changed_event()

    async def async_update(self) -> None:
        """Retrieve latest state."""
        self._cluster.debug("polling current state")
        await safe_read(
            self._cluster,
            [self._attribute_name],
            allow_cache=False,
            only_cache=False,
        )
        self.maybe_emit_state_changed_event()


class W100ExternalSensorSwitch(PlatformEntity, BaseSwitch):
    """W100 external sensor switch."""

    _attribute_name = W100ManuCluster.AttributeDefs.mode_flags.name
    _attr_entity_category = EntityCategory.CONFIG

    def on_add(self) -> None:
        """Run when entity is added."""
        super().on_add()

        for event_type in (
            AttributeReadEvent,
            AttributeReportedEvent,
            AttributeUpdatedEvent,
            AttributeWrittenEvent,
        ):
            self._on_remove_callbacks.append(
                self._cluster.on_event(
                    event_type.event_type,
                    self._handle_mode_flags_event,
                )
            )

    @property
    def is_on(self) -> bool:
        """Return if external sensor mode is enabled on the device."""
        mode_flags = self._cluster.get(self._attribute_name)
        return bool(mode_flags and mode_flags & EXTERNAL_SENSOR_ON_BIT)

    async def async_turn_on(self) -> None:
        """Turn external sensor mode on."""
        for command in W100CommandRawCodec.build_external_sensor_frame(
            enabled=True,
            device_ieee=self._cluster.endpoint.device.ieee.serialize()[::-1],
            timestamp=int(time.time()),
        ):
            result = await self._cluster.write_command_raw(command)
            status = result[0][0].status

            if status is not foundation.Status.SUCCESS:
                raise ZHAException(f"Failed to turn on external sensor: {status}")

    async def async_turn_off(self) -> None:
        """Turn external sensor mode off."""
        for command in W100CommandRawCodec.build_external_sensor_frame(
            enabled=False,
            device_ieee=self._cluster.endpoint.device.ieee.serialize()[::-1],
            timestamp=int(time.time()),
        ):
            result = await self._cluster.write_command_raw(command)
            status = result[0][0].status

            if status is not foundation.Status.SUCCESS:
                raise ZHAException(f"Failed to turn off external sensor: {status}")

    def _handle_mode_flags_event(
        self,
        event: AttributeReadEvent
        | AttributeReportedEvent
        | AttributeUpdatedEvent
        | AttributeWrittenEvent,
    ) -> None:
        """Handle mode_flags attribute events."""
        if event.attribute_name == self._attribute_name:
            self.maybe_emit_state_changed_event()

    async def async_update(self) -> None:
        """Retrieve latest state."""
        self._cluster.debug("polling current state")
        await safe_read(
            self._cluster,
            [self._attribute_name],
            allow_cache=False,
            only_cache=False,
        )
        self.maybe_emit_state_changed_event()


class W100ClimateEntity(BaseThermostat):
    """W100 climate entity backed by the W100 thermostat cluster."""

    DEFAULT_MIN_TEMP: Final = 4.5
    DEFAULT_MAX_TEMP: Final = 37

    _attr_primary_weight = 10
    _attr_precision = PRECISION_TENTHS
    _attr_temperature_unit = UnitOfTemperature.CELSIUS
    _attr_translation_key: str = "thermostat"
    _enable_turn_on_off_backwards_compatibility = False

    HVAC_MODES: Final[list[HVACMode]] = [
        HVACMode.OFF,
        HVACMode.HEAT,
        HVACMode.COOL,
        HVACMode.AUTO,
    ]

    FAN_MODES: Final[list[str]] = [
        FAN_OFF,
        FAN_AUTO,
        FAN_LOW,
        FAN_MEDIUM,
        FAN_HIGH,
    ]

    SYSTEM_MODE_TO_HVAC: Final = {
        Thermostat.SystemMode.Off: HVACMode.OFF,
        Thermostat.SystemMode.Heat: HVACMode.HEAT,
        Thermostat.SystemMode.Cool: HVACMode.COOL,
        Thermostat.SystemMode.Auto: HVACMode.AUTO,
    }

    HVAC_TO_SYSTEM_MODE: Final = {
        value: key for key, value in SYSTEM_MODE_TO_HVAC.items()
    }

    FAN_MODE_TO_ZCL: Final = {
        FAN_OFF: Fan.FanMode.Off,
        FAN_AUTO: Fan.FanMode.Auto,
        FAN_LOW: Fan.FanMode.Low,
        FAN_MEDIUM: Fan.FanMode.Medium,
        FAN_HIGH: Fan.FanMode.High,
    }

    ZCL_TO_FAN_MODE: Final = {value: key for key, value in FAN_MODE_TO_ZCL.items()}

    def on_add(self) -> None:
        """Run when entity is added."""
        super().on_add()

        for event_type in (
            AttributeReadEvent,
            AttributeReportedEvent,
            AttributeUpdatedEvent,
            AttributeWrittenEvent,
        ):
            self._on_remove_callbacks.append(
                self._cluster.on_event(
                    event_type.event_type,
                    self.handle_attribute_updated,
                )
            )
            self._on_remove_callbacks.append(
                self._temperature_cluster.on_event(
                    event_type.event_type,
                    self.handle_attribute_updated,
                )
            )

    def handle_attribute_updated(
        self,
        event: AttributeReadEvent
        | AttributeReportedEvent
        | AttributeUpdatedEvent
        | AttributeWrittenEvent,
    ) -> None:
        """Handle W100 thermostat or temperature update."""
        self.maybe_emit_state_changed_event()

    @functools.cached_property
    def info_object(self) -> ThermostatEntityInfo:
        """Return a representation of the thermostat."""
        return ThermostatEntityInfo(
            **super().info_object.__dict__,
            max_temp=self.max_temp,
            min_temp=self.min_temp,
            supported_features=self.supported_features,
            fan_modes=self.fan_modes,
            preset_modes=self.preset_modes,
            hvac_modes=self.hvac_modes,
        )

    @property
    def available(self) -> bool:
        """Return entity availability."""
        return True

    @property
    def _temperature_cluster(self) -> TemperatureMeasurement:
        """Return temperature measurement cluster."""
        return self.endpoint.zigpy_endpoint.in_clusters[
            TemperatureMeasurement.cluster_id
        ]

    @property
    def _local_temperature(self) -> int | None:
        """Return measured temperature in centi-degrees."""
        return self._temperature_cluster.get(
            TemperatureMeasurement.AttributeDefs.measured_value.name
        )

    @property
    def _system_mode(self) -> Thermostat.SystemMode | None:
        """Return cached W100 system mode."""
        return self._cluster.get(W100ThermostatCluster.AttributeDefs.system_mode.name)

    @property
    def _target_temperature(self) -> float | None:
        """Return cached target temperature in degrees Celsius."""
        return self._cluster.get(
            W100ThermostatCluster.AttributeDefs.target_temperature.name
        )

    @property
    def _fan_mode(self) -> Fan.FanMode | None:
        """Return cached fan mode."""
        return self._cluster.get(W100ThermostatCluster.AttributeDefs.fan_mode.name)

    @property
    def current_temperature(self) -> float | None:
        """Return the current temperature."""
        temperature = self._local_temperature

        if temperature is None:
            return None

        return temperature / ZCL_TEMP

    @property
    def target_temperature(self) -> float | None:
        """Return the temperature we try to reach."""
        return self._target_temperature

    @property
    def target_temperature_high(self) -> float | None:
        """Return the upper bound temperature we try to reach."""
        return None

    @property
    def target_temperature_low(self) -> float | None:
        """Return the lower bound temperature we try to reach."""
        return None

    @property
    def outdoor_temperature(self) -> float | None:
        """Return the outdoor temperature."""
        return None

    @property
    def hvac_mode(self) -> HVACMode | None:
        """Return HVAC operation mode."""
        return self.SYSTEM_MODE_TO_HVAC.get(self._system_mode)

    @property
    def hvac_modes(self) -> list[HVACMode]:
        """Return the list of available HVAC operation modes."""
        return self.HVAC_MODES

    @property
    def hvac_action(self) -> HVACAction | None:
        """Return the current HVAC action."""
        return None

    @property
    def fan_mode(self) -> str | None:
        """Return current FAN mode."""
        return self.ZCL_TO_FAN_MODE.get(self._fan_mode, FAN_OFF)

    @property
    def fan_modes(self) -> list[str]:
        """Return supported FAN modes."""
        return self.FAN_MODES

    @property
    def preset_mode(self) -> str | None:
        """Return current preset mode."""
        return None

    @property
    def preset_modes(self) -> list[str] | None:
        """Return supported preset modes."""
        return None

    @property
    def max_temp(self) -> float:
        """Return the maximum temperature."""
        return self.DEFAULT_MAX_TEMP

    @property
    def min_temp(self) -> float:
        """Return the minimum temperature."""
        return self.DEFAULT_MIN_TEMP

    @property
    def supported_features(self) -> ClimateEntityFeature:
        """Return the list of supported features."""
        return (
            ClimateEntityFeature.TARGET_TEMPERATURE
            | ClimateEntityFeature.FAN_MODE
            | ClimateEntityFeature.TURN_OFF
            | ClimateEntityFeature.TURN_ON
        )

    async def async_set_hvac_mode(self, hvac_mode: HVACMode) -> None:
        """Set new target operation mode."""
        system_mode = self.HVAC_TO_SYSTEM_MODE.get(hvac_mode)

        if system_mode is None:
            self.warning(
                "can't set '%s' mode. Supported modes are: %s",
                hvac_mode,
                self.hvac_modes,
            )
            return

        await self._cluster.write_attributes(
            {
                W100ThermostatCluster.AttributeDefs.system_mode.name: system_mode,
            }
        )

    async def async_set_temperature(
        self,
        target_temp_low: float | None = None,
        target_temp_high: float | None = None,
        temperature: float | None = None,
        hvac_mode: HVACMode | None = None,
    ) -> None:
        """Set new target operation mode and/or temperature in one write."""
        attributes: dict[str, Any] = {}

        if hvac_mode is not None:
            system_mode = self.HVAC_TO_SYSTEM_MODE.get(hvac_mode)

            if system_mode is None:
                self.warning(
                    "can't set '%s' mode. Supported modes are: %s",
                    hvac_mode,
                    self.hvac_modes,
                )
                return

            attributes[W100ThermostatCluster.AttributeDefs.system_mode.name] = (
                system_mode
            )

        if temperature is not None:
            attributes[W100ThermostatCluster.AttributeDefs.target_temperature.name] = (
                temperature
            )

        if not attributes:
            self._cluster.debug(
                "incorrect temperature setting for '%s' mode", self.hvac_mode
            )
            return

        await self._cluster.write_attributes(attributes)

    async def async_set_fan_mode(self, fan_mode: str) -> None:
        """Set fan mode."""
        zcl_fan_mode = self.FAN_MODE_TO_ZCL.get(fan_mode)

        if zcl_fan_mode is None:
            self.warning(
                "Unsupported '%s' fan mode. Supported modes are: %s",
                fan_mode,
                self.fan_modes,
            )
            return

        await self._cluster.write_attributes(
            {
                W100ThermostatCluster.AttributeDefs.fan_mode.name: zcl_fan_mode,
            }
        )

    async def async_set_preset_mode(self, preset_mode: str) -> None:
        """Set new preset mode."""
        self._cluster.debug("Preset mode '%s' is not supported", preset_mode)


class W100ZhaDevice(QuirkV2Device):
    """ZHA device class that exposes the W100 climate entity."""

    def discover_entities(self) -> Iterator[BaseEntity]:
        """Yield default entities plus the W100 climate entity."""
        yield from super().discover_entities()

        endpoint = self.endpoints[1]
        thermostat_cluster = endpoint.zigpy_endpoint.in_clusters[
            W100ThermostatCluster.cluster_id
        ]
        manufacturer_cluster = endpoint.zigpy_endpoint.in_clusters[
            W100ManuCluster.cluster_id
        ]

        yield W100ClimateEntity(
            endpoint=endpoint,
            device=self,
            cluster=thermostat_cluster,
            from_quirk=True,
            entity_type=EntityType.STANDARD,
            unique_id_suffix="w100_climate",
            fallback_name="Thermostat",
            translation_key="thermostat",
            primary=True,
        )

        yield W100ThermostatControlSwitch(
            endpoint=endpoint,
            device=self,
            cluster=manufacturer_cluster,
            from_quirk=True,
            entity_type=EntityType.CONFIG,
            unique_id_suffix="thermostat_control",
            fallback_name="Thermostat control",
            translation_key="thermostat_control",
            primary=False,
        )

        yield W100ExternalSensorSwitch(
            endpoint=endpoint,
            device=self,
            cluster=manufacturer_cluster,
            from_quirk=True,
            entity_type=EntityType.CONFIG,
            unique_id_suffix="external_sensor",
            fallback_name="External sensor",
            translation_key="external_sensor",
            primary=False,
        )


(
    QuirkBuilder("Aqara", "lumi.sensor_ht.agl001")
    .friendly_name(manufacturer="Aqara", model="Climate Sensor W100")
    .replaces(W100PowerConfigurationCluster, endpoint_id=1)
    .replaces(W100ManuCluster, endpoint_id=1)
    .replaces(W100ButtonCluster, endpoint_id=1)
    .replaces(W100ButtonCluster, endpoint_id=2)
    .replaces(W100ButtonCluster, endpoint_id=3)
    .device_automation_triggers(W100ButtonCluster.automation_triggers())
    .adds(W100ThermostatCluster, endpoint_id=1)
    .adds(W100ExternalSensorCluster, endpoint_id=1)
    .zha_device_class(W100ZhaDevice)
    .switch(
        attribute_name="thermostat_line_auto_hide",
        cluster_id=W100ManuCluster.cluster_id,
        on_value=0,
        off_value=1,
        translation_key="thermostat_line_auto_hide",
        fallback_name="Thermostat line auto-hide",
    )
    .number(
        attribute_name="external_temperature",
        cluster_id=W100ExternalSensorCluster.cluster_id,
        device_class=NumberDeviceClass.TEMPERATURE,
        entity_type=EntityType.STANDARD,
        min_value=-99.9,
        max_value=100.0,
        step=0.1,
        multiplier=0.01,
        unit=UnitOfTemperature.CELSIUS,
        mode=NumberMode.BOX,
        translation_key="external_temperature",
        fallback_name="External temperature",
    )
    .number(
        attribute_name="external_humidity",
        cluster_id=W100ExternalSensorCluster.cluster_id,
        device_class=NumberDeviceClass.HUMIDITY,
        entity_type=EntityType.STANDARD,
        min_value=0.0,
        max_value=99.0,
        step=1.0,
        multiplier=0.01,
        unit=PERCENTAGE,
        mode=NumberMode.BOX,
        translation_key="external_humidity",
        fallback_name="External humidity",
    )
    .number(
        attribute_name="high_temperature",
        cluster_id=W100ManuCluster.cluster_id,
        device_class=NumberDeviceClass.TEMPERATURE,
        min_value=23.0,
        max_value=60.0,
        step=0.5,
        multiplier=0.01,
        unit=UnitOfTemperature.CELSIUS,
        translation_key="high_temperature",
        fallback_name="High temperature",
    )
    .number(
        attribute_name="low_temperature",
        cluster_id=W100ManuCluster.cluster_id,
        device_class=NumberDeviceClass.TEMPERATURE,
        min_value=-20.0,
        max_value=22.0,
        step=0.5,
        multiplier=0.01,
        unit=UnitOfTemperature.CELSIUS,
        translation_key="low_temperature",
        fallback_name="Low temperature",
    )
    .number(
        attribute_name="high_humidity",
        cluster_id=W100ManuCluster.cluster_id,
        device_class=NumberDeviceClass.HUMIDITY,
        min_value=65.0,
        max_value=99.99,
        step=1.0,
        multiplier=0.01,
        unit=PERCENTAGE,
        translation_key="high_humidity",
        fallback_name="High humidity",
    )
    .number(
        attribute_name="low_humidity",
        cluster_id=W100ManuCluster.cluster_id,
        device_class=NumberDeviceClass.HUMIDITY,
        min_value=0.0,
        max_value=30.0,
        step=1.0,
        multiplier=0.01,
        unit=PERCENTAGE,
        translation_key="low_humidity",
        fallback_name="Low humidity",
    )
    .enum(
        attribute_name="temperature_status",
        enum_class=TempHumidityStatus,
        cluster_id=W100ManuCluster.cluster_id,
        entity_platform=EntityPlatform.SENSOR,
        entity_type=EntityType.DIAGNOSTIC,
        translation_key="temperature_status",
        fallback_name="Temperature status",
    )
    .enum(
        attribute_name="humidity_status",
        enum_class=TempHumidityStatus,
        cluster_id=W100ManuCluster.cluster_id,
        entity_platform=EntityPlatform.SENSOR,
        entity_type=EntityType.DIAGNOSTIC,
        translation_key="humidity_status",
        fallback_name="Humidity status",
    )
    .enum(
        attribute_name="temp_humidity_sampling",
        enum_class=SamplingFrequency,
        cluster_id=W100ManuCluster.cluster_id,
        translation_key="temp_humidity_sampling",
        fallback_name="Temperature and humidity sampling",
    )
    .number(
        attribute_name="temp_humidity_sampling_period",
        cluster_id=W100ManuCluster.cluster_id,
        device_class=NumberDeviceClass.DURATION,
        min_value=0.5,
        max_value=600.0,
        step=0.5,
        multiplier=0.001,
        unit=UnitOfTime.SECONDS,
        translation_key="temp_humidity_sampling_period",
        fallback_name="Temperature and humidity sampling period",
    )
    .enum(
        attribute_name="temperature_report_mode",
        enum_class=ReportMode,
        cluster_id=W100ManuCluster.cluster_id,
        translation_key="temperature_report_mode",
        fallback_name="Temperature report mode",
    )
    .number(
        attribute_name="temperature_report_interval",
        cluster_id=W100ManuCluster.cluster_id,
        device_class=NumberDeviceClass.DURATION,
        min_value=1.0,
        max_value=600.0,
        step=1.0,
        multiplier=0.001,
        unit=UnitOfTime.SECONDS,
        translation_key="temperature_report_interval",
        fallback_name="Temperature report interval",
    )
    .number(
        attribute_name="temperature_report_threshold",
        cluster_id=W100ManuCluster.cluster_id,
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
        attribute_name="humidity_report_mode",
        enum_class=ReportMode,
        cluster_id=W100ManuCluster.cluster_id,
        translation_key="humidity_report_mode",
        fallback_name="Humidity report mode",
    )
    .number(
        attribute_name="humidity_report_interval",
        cluster_id=W100ManuCluster.cluster_id,
        device_class=NumberDeviceClass.DURATION,
        min_value=1.0,
        max_value=600.0,
        step=1.0,
        multiplier=0.001,
        unit=UnitOfTime.SECONDS,
        translation_key="humidity_report_interval",
        fallback_name="Humidity report interval",
    )
    .number(
        attribute_name="humidity_report_threshold",
        cluster_id=W100ManuCluster.cluster_id,
        device_class=NumberDeviceClass.HUMIDITY,
        min_value=2.0,
        max_value=10.0,
        step=0.5,
        multiplier=0.01,
        unit=PERCENTAGE,
        translation_key="humidity_report_threshold",
        fallback_name="Humidity report threshold",
    )
    .add_to_registry()
)
