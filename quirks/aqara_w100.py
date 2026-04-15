"""Quirk for Aqara Climate Sensor W100 (lumi.sensor_ht.agl001).

Link to recommended Blueprint:
https://github.com/nokside/ha-toolbox/blob/main/blueprints/automation/aqara_w100.yaml
"""

import os
import struct
import time
from typing import Any, Final

from zigpy import types as t
from zigpy.quirks.v2 import QuirkBuilder
from zigpy.quirks.v2.homeassistant import (
    PERCENTAGE,
    EntityPlatform,
    EntityType,
    UnitOfTemperature,
    UnitOfTime,
)
from zigpy.quirks.v2.homeassistant.number import NumberDeviceClass
from zigpy.typing import UNDEFINED, UndefinedType
from zigpy.zcl import foundation
from zigpy.zcl.clusters.general import MultistateInput
from zigpy.zcl.clusters.hvac import Fan, Thermostat
from zigpy.zcl.clusters.measurement import TemperatureMeasurement
from zigpy.zcl.foundation import BaseAttributeDefs, DataTypeId, ZCLAttributeDef

from zhaquirks import CustomCluster, LocalDataCluster
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
from zhaquirks.xiaomi import (
    BATTERY_PERCENTAGE_REMAINING_ATTRIBUTE,
    XiaomiAqaraE1Cluster,
    XiaomiPowerConfigurationPercent,
)

W100_ATTR_BATTERY_PERCENT: Final = "0xff01-102"
AQARA_MFG_CODE: Final = 0x115F
THERMOSTAT_ON_BIT: Final = 0x01
EXTERNAL_SENSOR_BIT: Final = 0x02


def _build_lumi_header(payload_len: int, command_id: int) -> bytes:
    """Build a 9-byte Lumi frame header with auto-calculated integrity."""
    header = [0xAA, 0x71, payload_len + 3, 0x44, os.urandom(1)[0]]
    integrity = (-sum(header)) & 0xFF
    return bytes([*header, integrity, command_id, 0x41, payload_len])


class SamplingFrequency(t.enum8):
    Low = 1
    Standard = 2
    High = 3
    Custom = 4


class ReportMode(t.enum8):
    Off = 0
    Threshold = 1
    Period = 2
    Threshold_period = 3


class AlertState(t.enum8):
    Clear = 0
    High = 1
    Low = 2


class AqaraW100ManuCluster(XiaomiAqaraE1Cluster):
    """Aqara W100 manufacturer cluster, routes command_raw to subsystems."""

    ep_attribute = "aqara_w100_manu"

    class AttributeDefs(XiaomiAqaraE1Cluster.AttributeDefs):
        high_temperature = ZCLAttributeDef(
            id=0x0167,
            type=t.int16s,
            access="rwp",
            manufacturer_code=AQARA_MFG_CODE,
        )
        low_temperature = ZCLAttributeDef(
            id=0x0166,
            type=t.int16s,
            access="rwp",
            manufacturer_code=AQARA_MFG_CODE,
        )
        high_humidity = ZCLAttributeDef(
            id=0x016E,
            type=t.int16s,
            access="rwp",
            manufacturer_code=AQARA_MFG_CODE,
        )
        low_humidity = ZCLAttributeDef(
            id=0x016D,
            type=t.int16s,
            access="rwp",
            manufacturer_code=AQARA_MFG_CODE,
        )
        temperature_alert = ZCLAttributeDef(
            id=0x0168,
            type=AlertState,
            zcl_type=DataTypeId.uint8,
            access="rp",
            manufacturer_code=AQARA_MFG_CODE,
        )
        humidity_alert = ZCLAttributeDef(
            id=0x016F,
            type=AlertState,
            zcl_type=DataTypeId.uint8,
            access="rp",
            manufacturer_code=AQARA_MFG_CODE,
        )
        temp_humidity_sampling = ZCLAttributeDef(
            id=0x0170,
            type=SamplingFrequency,
            zcl_type=DataTypeId.uint8,
            access="rwp",
            manufacturer_code=AQARA_MFG_CODE,
        )
        temp_humidity_sampling_period = ZCLAttributeDef(
            id=0x0162,
            type=t.uint32_t,
            access="rwp",
            manufacturer_code=AQARA_MFG_CODE,
        )
        temp_reporting_mode = ZCLAttributeDef(
            id=0x0165,
            type=ReportMode,
            zcl_type=DataTypeId.uint8,
            access="rwp",
            manufacturer_code=AQARA_MFG_CODE,
        )
        temp_reporting_interval = ZCLAttributeDef(
            id=0x0163,
            type=t.uint32_t,
            access="rwp",
            manufacturer_code=AQARA_MFG_CODE,
        )
        temp_reporting_threshold = ZCLAttributeDef(
            id=0x0164,
            type=t.uint16_t,
            access="rwp",
            manufacturer_code=AQARA_MFG_CODE,
        )
        humidity_reporting_mode = ZCLAttributeDef(
            id=0x016C,
            type=ReportMode,
            zcl_type=DataTypeId.uint8,
            access="rwp",
            manufacturer_code=AQARA_MFG_CODE,
        )
        humidity_reporting_interval = ZCLAttributeDef(
            id=0x016A,
            type=t.uint32_t,
            access="rwp",
            manufacturer_code=AQARA_MFG_CODE,
        )
        humidity_reporting_threshold = ZCLAttributeDef(
            id=0x016B,
            type=t.uint16_t,
            access="rwp",
            manufacturer_code=AQARA_MFG_CODE,
        )
        thermostat_line_auto_hide = ZCLAttributeDef(
            id=0x0173,
            type=t.Bool,
            access="rwp",
            manufacturer_code=AQARA_MFG_CODE,
        )
        command_raw = ZCLAttributeDef(
            id=0xFFF2,
            type=t.LVBytes,
            access="rwp",
            manufacturer_code=AQARA_MFG_CODE,
        )
        mode_flags = ZCLAttributeDef(
            id=0x0172,
            type=t.uint32_t,
            access="rp",
            manufacturer_code=AQARA_MFG_CODE,
        )

    def _parse_aqara_attributes(self, value: Any) -> dict[str, Any]:
        attributes = super()._parse_aqara_attributes(value)

        if W100_ATTR_BATTERY_PERCENT in attributes:
            attributes[BATTERY_PERCENTAGE_REMAINING_ATTRIBUTE] = attributes.pop(
                W100_ATTR_BATTERY_PERCENT
            )
        return attributes

    def _update_attribute(self, attrid: int, value: Any) -> None:
        super()._update_attribute(attrid, value)

        if attrid == self.AttributeDefs.mode_flags.id:
            self.endpoint.w100_thermostat_control_mode.apply_state(value)
            self.endpoint.w100_external_sensors.apply_state(value)
        elif attrid == self.AttributeDefs.command_raw.id:
            self._dispatch_raw_command(bytes(value))

    def _dispatch_raw_command(self, payload: bytes) -> None:
        if W100PmtsdCluster.PMTSD_REQUEST_MARKER in payload:
            self.endpoint.w100_pmtsd.handle_raw_thermostat(payload)
        elif any(
            marker in payload
            for marker in W100ExternalSensorsCluster._MEASUREMENT_MARKER.values()
        ):
            self.endpoint.w100_external_sensors.handle_raw_sensor(payload)


class W100PmtsdCluster(LocalDataCluster):
    """PMTSD protocol bridge between HA and W100 thermostat display."""

    cluster_id = 0xFCF4
    ep_attribute = "w100_pmtsd"

    class AttributeDefs(BaseAttributeDefs):
        last_active_mode = ZCLAttributeDef(
            id=0x5000,
            type=Thermostat.SystemMode,
            manufacturer_code=AQARA_MFG_CODE,
        )
        pmtsd_d = ZCLAttributeDef(
            id=0x5001,
            type=t.uint8_t,
            manufacturer_code=AQARA_MFG_CODE,
        )
        thermostat_line_show_fan = ZCLAttributeDef(
            id=0x5002,
            type=t.Bool,
            manufacturer_code=AQARA_MFG_CODE,
        )

    PMTSD_REQUEST_MARKER: Final = bytes.fromhex("08000844")

    SYSTEM_MODE_TO_PMTSD_M: Final[dict[int, int]] = {
        Thermostat.SystemMode.Cool: 0,
        Thermostat.SystemMode.Heat: 1,
        Thermostat.SystemMode.Auto: 2,
    }

    PMTSD_M_TO_SYSTEM_MODE: Final[dict[int, int]] = {
        v: k for k, v in SYSTEM_MODE_TO_PMTSD_M.items()
    }

    FAN_MODE_TO_PMTSD_S: Final[dict[int, int]] = {
        Fan.FanMode.Auto: 0,
        Fan.FanMode.Low: 1,
        Fan.FanMode.Medium: 2,
        Fan.FanMode.High: 3,
    }

    PMTSD_S_TO_FAN_MODE: Final[dict[int, int]] = {
        v: k for k, v in FAN_MODE_TO_PMTSD_S.items()
    }

    SYSTEM_MODE_ATTR: Final = Thermostat.AttributeDefs.system_mode.id
    HEATING_SETPOINT_ATTR: Final = Thermostat.AttributeDefs.occupied_heating_setpoint.id
    COOLING_SETPOINT_ATTR: Final = Thermostat.AttributeDefs.occupied_cooling_setpoint.id
    FAN_MODE_ATTR: Final = Fan.AttributeDefs.fan_mode.id

    _DEFAULT_VALUES = {
        AttributeDefs.last_active_mode.id: Thermostat.SystemMode.Heat,
        AttributeDefs.pmtsd_d.id: 0,
        AttributeDefs.thermostat_line_show_fan.id: False,
    }

    def handle_raw_thermostat(self, payload: bytes) -> None:
        if payload.endswith(self.PMTSD_REQUEST_MARKER):
            self.create_catching_task(self._write_frame_to_w100(self._build_pmtsd_to_w100()))
        else:
            self._pmtsd_from_w100(payload)

    def _pmtsd_from_w100(self, payload: bytes) -> None:
        marker = self.PMTSD_REQUEST_MARKER
        idx = payload.find(marker)
        length_idx = idx + len(marker)
        data_len = payload[length_idx]
        start = length_idx + 1
        end = start + data_len

        if end > len(payload):
            self.debug(
                "PMTSD frame truncated: claimed=%d actual=%d",
                data_len,
                len(payload) - start,
            )
            return

        raw_str = payload[start:end].decode("ascii").rstrip("\x00")
        report: dict[str, int | float] = {}

        for part in raw_str.split("_"):
            if len(part) < 2:
                continue

            key = part[:1].lower()
            value = part[1:]

            if key == "p":
                report["p"] = int(value)
            elif key == "m":
                report["m"] = int(value)
            elif key == "t":
                report["t"] = float(value)
            elif key == "s":
                report["s"] = int(value)
            elif key == "d":
                report["d"] = int(value)
            else:
                self.debug("Unknown PMTSD key: %r in %r", key, raw_str)

        self._apply_pmtsd_from_w100(report)

    def _apply_pmtsd_from_w100(self, payload: dict[str, int | float]) -> None:
        thermostat = self.endpoint.thermostat
        was_off = thermostat.get(self.SYSTEM_MODE_ATTR) == Thermostat.SystemMode.Off
        needs_sync = False

        if "m" in payload:
            mode = self.PMTSD_M_TO_SYSTEM_MODE[int(payload["m"])]
            thermostat._update_attribute(self.SYSTEM_MODE_ATTR, mode)
            self._update_attribute(self.AttributeDefs.last_active_mode.id, mode)

        if "t" in payload:
            setpoint = int(float(payload["t"]) * 100)
            current_mode = thermostat.get(self.SYSTEM_MODE_ATTR)
            target_mode = (
                current_mode
                if current_mode != Thermostat.SystemMode.Off
                else self.get(self.AttributeDefs.last_active_mode.id)
            )
            attr = (
                self.COOLING_SETPOINT_ATTR
                if target_mode == Thermostat.SystemMode.Cool
                else self.HEATING_SETPOINT_ATTR
            )
            thermostat._update_attribute(attr, setpoint)

        if "s" in payload:
            fan_mode = self.PMTSD_S_TO_FAN_MODE[int(payload["s"])]
            self.endpoint.fan._update_attribute(self.FAN_MODE_ATTR, fan_mode)
            if not self.get(self.AttributeDefs.thermostat_line_show_fan.id):
                needs_sync = True

        if "p" in payload:
            if payload["p"] == 1:
                current_mode = thermostat.get(self.SYSTEM_MODE_ATTR)
                if current_mode != Thermostat.SystemMode.Off:
                    self._update_attribute(
                        self.AttributeDefs.last_active_mode.id, current_mode
                    )
                thermostat._update_attribute(
                    self.SYSTEM_MODE_ATTR, Thermostat.SystemMode.Off
                )
            elif payload["p"] == 0:
                if was_off:
                    thermostat._update_attribute(
                        self.SYSTEM_MODE_ATTR,
                        self.get(self.AttributeDefs.last_active_mode.id),
                    )
                    needs_sync = True

        if needs_sync:
            self.create_catching_task(self.sync_state_to_w100())

    def _build_frame_to_w100(self, ascii_str: str) -> bytes:
        ascii_payload = ascii_str.encode("ascii")
        hub_mac = self.endpoint.device.ieee.serialize()[::-1][:6]
        payload = (
            b"\x00\x00"
            + hub_mac
            + self.PMTSD_REQUEST_MARKER
            + bytes([len(ascii_payload)])
            + ascii_payload
            + b"\x00"
        )
        return _build_lumi_header(len(payload), 0x05) + payload

    def _build_pmtsd_to_w100(self) -> str:
        thermostat = self.endpoint.thermostat
        system_mode = thermostat.get(self.SYSTEM_MODE_ATTR)
        active_mode = (
            self.get(self.AttributeDefs.last_active_mode.id)
            if system_mode == Thermostat.SystemMode.Off
            else system_mode
        )

        p = 1 if system_mode == Thermostat.SystemMode.Off else 0
        m = self.SYSTEM_MODE_TO_PMTSD_M[active_mode]
        setpoint = thermostat.get(
            self.COOLING_SETPOINT_ATTR
            if active_mode == Thermostat.SystemMode.Cool
            else self.HEATING_SETPOINT_ATTR
        )

        parts = [f"P{p}", f"M{m}", f"T{setpoint / 100:g}"]
        if self.get(self.AttributeDefs.thermostat_line_show_fan.id):
            s = self.FAN_MODE_TO_PMTSD_S[self.endpoint.fan.get(self.FAN_MODE_ATTR)]
            parts.append(f"S{s}")
        return "_".join(parts)

    async def _write_frame_to_w100(self, ascii_str: str) -> None:
        frame = self._build_frame_to_w100(ascii_str)
        await self.endpoint.aqara_w100_manu.write_attributes(
            {
                self.endpoint.aqara_w100_manu.AttributeDefs.command_raw.id: t.LVBytes(
                    frame
                ),
            },
            manufacturer=AQARA_MFG_CODE,
        )

    async def sync_state_to_w100(self) -> None:
        if not (
            self.endpoint.aqara_w100_manu.get(
                AqaraW100ManuCluster.AttributeDefs.mode_flags.id
            )
            & THERMOSTAT_ON_BIT
        ):
            return

        mode = self.endpoint.thermostat.get(self.SYSTEM_MODE_ATTR)
        if mode != Thermostat.SystemMode.Off:
            self._update_attribute(self.AttributeDefs.last_active_mode.id, mode)

        await self._write_frame_to_w100(self._build_pmtsd_to_w100())

    async def write_attributes(
        self,
        attributes: dict[str | int | foundation.ZCLAttributeDef, Any],
        manufacturer: int | UndefinedType | None = UNDEFINED,
        **kwargs,
    ) -> list[list[foundation.WriteAttributesStatusRecord]]:
        resolved = {
            self.find_attribute(attr).id: value
            for attr, value in attributes.items()
        }

        for attrid, value in resolved.items():
            self._update_attribute(attrid, value)

        if self.AttributeDefs.thermostat_line_show_fan.id in resolved:
            await self.sync_state_to_w100()

        return [[foundation.WriteAttributesStatusRecord(
            foundation.Status.SUCCESS,
        )]]


class W100ThermostatControlModeCluster(LocalDataCluster):
    """Thermostat control mode activation and deactivation."""

    cluster_id = 0xFCF1
    ep_attribute = "w100_thermostat_control_mode"

    class AttributeDefs(BaseAttributeDefs):
        thermostat_control_mode = ZCLAttributeDef(
            id=0x0000,
            type=t.Bool,
            manufacturer_code=AQARA_MFG_CODE,
        )

    MODE_ON_TAIL: Final = bytes.fromhex(
        "08000844150a0109e7a9bae8b083e58a9f000000000001012a40"
    )
    MODE_CONTROL: Final = b"\x18"

    def _build_thermostat_control_mode_command(self, enabled: bool) -> bytes:
        device_mac = self.endpoint.device.ieee.serialize()[::-1]
        if enabled:
            payload = (
                b"\x68\x91"
                + os.urandom(2)
                + self.MODE_CONTROL
                + device_mac
                + b"\x00\x00"
                + device_mac[:6]
                + self.MODE_ON_TAIL
            )
            return _build_lumi_header(len(payload), 0x02) + payload
        else:
            payload = (
                b"\x68\x91"
                + os.urandom(2)
                + self.MODE_CONTROL
                + device_mac
            ).ljust(25, b"\x00")
            return _build_lumi_header(len(payload), 0x04) + payload

    def apply_state(self, raw_flags: Any) -> None:
        state = bool(int(raw_flags) & THERMOSTAT_ON_BIT)
        self._update_attribute(self.AttributeDefs.thermostat_control_mode.id, state)

    async def write_attributes(
        self,
        attributes: dict[str | int | foundation.ZCLAttributeDef, Any],
        manufacturer: int | UndefinedType | None = UNDEFINED,
        **kwargs,
    ) -> list[list[foundation.WriteAttributesStatusRecord]]:
        resolved = {
            self.find_attribute(attr).id: value
            for attr, value in attributes.items()
        }

        desired = bool(resolved[self.AttributeDefs.thermostat_control_mode.id])
        frame = self._build_thermostat_control_mode_command(desired)

        return await self.endpoint.aqara_w100_manu.write_attributes(
            {AqaraW100ManuCluster.AttributeDefs.command_raw.id: frame},
            manufacturer=AQARA_MFG_CODE,
            **kwargs,
        )


class W100ExternalSensorsCluster(LocalDataCluster):
    """External temperature and humidity sensor management."""

    cluster_id = 0xFCF3
    ep_attribute = "w100_external_sensors"

    class AttributeDefs(BaseAttributeDefs):
        external_temperature = ZCLAttributeDef(
            id=0x0000,
            type=t.int16s,
            manufacturer_code=AQARA_MFG_CODE,
        )
        external_humidity = ZCLAttributeDef(
            id=0x0001,
            type=t.uint16_t,
            manufacturer_code=AQARA_MFG_CODE,
        )
        external_sensor = ZCLAttributeDef(
            id=0x0002,
            type=t.Bool,
            manufacturer_code=AQARA_MFG_CODE,
        )

    CHANNEL_HUMIDITY: Final = b"\x15"
    CHANNEL_TEMPERATURE: Final = b"\x14"

    EXTERNAL_SOURCE_HUMIDITY_TAIL: Final = bytes.fromhex(
        "00020055150a0100000106e6b9bfe5baa6000000000001020865"
    )
    EXTERNAL_SOURCE_TEMPERATURE_TAIL: Final = bytes.fromhex(
        "00010055150a0100000106e6b8a9e5baa6000000000001020763"
    )

    _MEASUREMENT_MARKER: Final[dict[int, bytes]] = {
        AttributeDefs.external_temperature.id: bytes.fromhex("00010055"),
        AttributeDefs.external_humidity.id: bytes.fromhex("00020055"),
    }

    _DEFAULT_VALUES = {
        AttributeDefs.external_temperature.id: 2000,
        AttributeDefs.external_humidity.id: 5000,
        AttributeDefs.external_sensor.id: False,
    }

    def _build_sensor_source_frames(
        self,
        external: bool,
    ) -> tuple[t.LVBytes, t.LVBytes]:
        device_mac = self.endpoint.device.ieee.serialize()[::-1]
        timestamp = int(time.time()).to_bytes(4, "big")

        if external:
            humidity_payload = (
                timestamp
                + self.CHANNEL_HUMIDITY
                + device_mac * 2
                + self.EXTERNAL_SOURCE_HUMIDITY_TAIL
            )
            temperature_payload = (
                timestamp
                + self.CHANNEL_TEMPERATURE
                + device_mac * 2
                + self.EXTERNAL_SOURCE_TEMPERATURE_TAIL
            )
            command_id = 0x02
        else:
            humidity_payload = (
                timestamp + self.CHANNEL_HUMIDITY + device_mac + bytes(12)
            )
            temperature_payload = (
                timestamp + self.CHANNEL_TEMPERATURE + device_mac + bytes(12)
            )
            command_id = 0x04

        return (
            t.LVBytes(
                _build_lumi_header(len(humidity_payload), command_id)
                + humidity_payload
            ),
            t.LVBytes(
                _build_lumi_header(len(temperature_payload), command_id)
                + temperature_payload
            ),
        )

    def _build_measurement_command(self, attrid: int, raw_value: int) -> t.LVBytes:
        encoded = struct.pack(">f", float(raw_value))
        device_mac = self.endpoint.device.ieee.serialize()[::-1]
        payload = device_mac + self._MEASUREMENT_MARKER[attrid] + encoded
        return t.LVBytes(_build_lumi_header(len(payload), 0x05) + payload)

    def apply_state(self, raw_flags: Any) -> None:
        state = bool(int(raw_flags) & EXTERNAL_SENSOR_BIT)
        self._update_attribute(self.AttributeDefs.external_sensor.id, state)

    def handle_raw_sensor(self, payload: bytes) -> None:
        for attrid, marker in self._MEASUREMENT_MARKER.items():
            if marker in payload:
                self.create_catching_task(self._send_cached_attr(attrid))

    async def _send_cached_attr(self, attrid: int) -> None:
        cmd = self._build_measurement_command(attrid, self.get(attrid))
        await self.endpoint.aqara_w100_manu.write_attributes(
            {AqaraW100ManuCluster.AttributeDefs.command_raw.id: cmd},
            manufacturer=AQARA_MFG_CODE,
        )

    async def write_attributes(
        self,
        attributes: dict[str | int | foundation.ZCLAttributeDef, Any],
        manufacturer: int | UndefinedType | None = UNDEFINED,
        **kwargs,
    ) -> list[list[foundation.WriteAttributesStatusRecord]]:
        resolved = {
            self.find_attribute(attr).id: value
            for attr, value in attributes.items()
        }

        if self.AttributeDefs.external_sensor.id in resolved:
            external = bool(resolved[self.AttributeDefs.external_sensor.id])
            for frame in self._build_sensor_source_frames(external):
                await self.endpoint.aqara_w100_manu.write_attributes(
                    {AqaraW100ManuCluster.AttributeDefs.command_raw.id: frame},
                    manufacturer=AQARA_MFG_CODE,
                    **kwargs,
                )

        is_external = bool(
            self.endpoint.aqara_w100_manu.get(
                AqaraW100ManuCluster.AttributeDefs.mode_flags.id
            )
            & EXTERNAL_SENSOR_BIT
        )

        for attrid in (
            self.AttributeDefs.external_temperature.id,
            self.AttributeDefs.external_humidity.id,
        ):
            if attrid in resolved:
                self._update_attribute(attrid, resolved[attrid])
                if is_external:
                    await self._send_cached_attr(attrid)

        return [[foundation.WriteAttributesStatusRecord(
            foundation.Status.SUCCESS,
        )]]


class W100ButtonCluster(CustomCluster, MultistateInput):
    """W100 button events for plus, center, and minus buttons."""

    STATUS_TYPE_ATTR: Final = MultistateInput.AttributeDefs.present_value.id

    PLUS_BUTTON: Final = "plus"
    CENTER_BUTTON: Final = "center"
    MINUS_BUTTON: Final = "minus"

    PRESS_TYPES: Final = {
        0: COMMAND_HOLD,
        1: COMMAND_SINGLE,
        2: COMMAND_DOUBLE,
        255: COMMAND_RELEASE,
    }

    BUTTON_NAMES: Final = {
        1: PLUS_BUTTON,
        2: CENTER_BUTTON,
        3: MINUS_BUTTON,
    }

    @classmethod
    def automation_triggers(cls) -> dict:
        return {
            (cls.PLUS_BUTTON, SHORT_PRESS): {COMMAND: COMMAND_SINGLE, ENDPOINT_ID: 1},
            (cls.PLUS_BUTTON, DOUBLE_PRESS): {COMMAND: COMMAND_DOUBLE, ENDPOINT_ID: 1},
            (cls.PLUS_BUTTON, LONG_PRESS): {COMMAND: COMMAND_HOLD, ENDPOINT_ID: 1},
            (cls.PLUS_BUTTON, LONG_RELEASE): {COMMAND: COMMAND_RELEASE, ENDPOINT_ID: 1},
            (cls.CENTER_BUTTON, SHORT_PRESS): {COMMAND: COMMAND_SINGLE, ENDPOINT_ID: 2},
            (cls.CENTER_BUTTON, DOUBLE_PRESS): {COMMAND: COMMAND_DOUBLE, ENDPOINT_ID: 2},
            (cls.CENTER_BUTTON, LONG_PRESS): {COMMAND: COMMAND_HOLD, ENDPOINT_ID: 2},
            (cls.CENTER_BUTTON, LONG_RELEASE): {COMMAND: COMMAND_RELEASE, ENDPOINT_ID: 2},
            (cls.MINUS_BUTTON, SHORT_PRESS): {COMMAND: COMMAND_SINGLE, ENDPOINT_ID: 3},
            (cls.MINUS_BUTTON, DOUBLE_PRESS): {COMMAND: COMMAND_DOUBLE, ENDPOINT_ID: 3},
            (cls.MINUS_BUTTON, LONG_PRESS): {COMMAND: COMMAND_HOLD, ENDPOINT_ID: 3},
            (cls.MINUS_BUTTON, LONG_RELEASE): {COMMAND: COMMAND_RELEASE, ENDPOINT_ID: 3},
        }

    def _update_attribute(self, attrid: int, value: Any) -> None:
        super()._update_attribute(attrid, value)

        if attrid == self.STATUS_TYPE_ATTR:
            press_type = self.PRESS_TYPES.get(value, f"unknown_{value}")
            button = self.BUTTON_NAMES.get(
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


class W100ThermostatCluster(LocalDataCluster, Thermostat):
    """Thermostat cluster, delegates state changes to W100 via PMTSD."""

    MIN_SETPOINT: Final = 450
    MAX_SETPOINT: Final = 3700
    _CONSTANT_ATTRIBUTES = {
        Thermostat.AttributeDefs.ctrl_sequence_of_oper.id:
            Thermostat.ControlSequenceOfOperation.Cooling_and_Heating,
    }
    _DEFAULT_VALUES = {
        Thermostat.AttributeDefs.system_mode.id: Thermostat.SystemMode.Off,
        Thermostat.AttributeDefs.occupied_heating_setpoint.id: 2000,
        Thermostat.AttributeDefs.occupied_cooling_setpoint.id: 2800,
        Thermostat.AttributeDefs.min_heat_setpoint_limit.id: MIN_SETPOINT,
        Thermostat.AttributeDefs.max_heat_setpoint_limit.id: MAX_SETPOINT,
        Thermostat.AttributeDefs.min_cool_setpoint_limit.id: MIN_SETPOINT,
        Thermostat.AttributeDefs.max_cool_setpoint_limit.id: MAX_SETPOINT,
    }

    async def write_attributes(
        self,
        attributes: dict[str | int | foundation.ZCLAttributeDef, Any],
        manufacturer: int | UndefinedType | None = UNDEFINED,
        **kwargs,
    ) -> list[list[foundation.WriteAttributesStatusRecord]]:
        resolved = {
            self.find_attribute(attr).id: value
            for attr, value in attributes.items()
        }
        for attrid, value in resolved.items():
            self._update_attribute(attrid, value)

        if (
            Thermostat.AttributeDefs.system_mode.id in resolved
            or self.get(Thermostat.AttributeDefs.system_mode.id)
            != Thermostat.SystemMode.Auto
        ):
            await self.endpoint.w100_pmtsd.sync_state_to_w100()

        return [[foundation.WriteAttributesStatusRecord(foundation.Status.SUCCESS)]]


class W100FanCluster(LocalDataCluster, Fan):
    """Fan cluster, delegates state changes to W100 via PMTSD."""

    _CONSTANT_ATTRIBUTES = {
        Fan.AttributeDefs.fan_mode_sequence.id:
            Fan.FanModeSequence.Low_Med_High_Auto,
    }
    _DEFAULT_VALUES = {
        Fan.AttributeDefs.fan_mode.id: Fan.FanMode.Auto,
    }

    async def write_attributes(
        self,
        attributes: dict[str | int | foundation.ZCLAttributeDef, Any],
        manufacturer: int | UndefinedType | None = UNDEFINED,
        **kwargs,
    ) -> list[list[foundation.WriteAttributesStatusRecord]]:
        resolved = {
            self.find_attribute(attr).id: value
            for attr, value in attributes.items()
        }
        for attrid, value in resolved.items():
            self._update_attribute(attrid, value)

        if self.endpoint.w100_pmtsd.get(
            W100PmtsdCluster.AttributeDefs.thermostat_line_show_fan.id
        ):
            await self.endpoint.w100_pmtsd.sync_state_to_w100()

        return [[foundation.WriteAttributesStatusRecord(foundation.Status.SUCCESS)]]


class W100TemperatureMeasurement(CustomCluster, TemperatureMeasurement):
    """TemperatureMeasurement with local_temperature sync to Thermostat."""

    def _update_attribute(self, attrid: int, value: Any) -> None:
        super()._update_attribute(attrid, value)
        if attrid == TemperatureMeasurement.AttributeDefs.measured_value.id:
            self.endpoint.thermostat._update_attribute(
                Thermostat.AttributeDefs.local_temperature.id,
                value,
            )


(
    QuirkBuilder("Aqara", "lumi.sensor_ht.agl001")
    .friendly_name(manufacturer="Aqara", model="Climate Sensor W100")
    .replaces(XiaomiPowerConfigurationPercent, endpoint_id=1)
    .replaces(AqaraW100ManuCluster, endpoint_id=1)
    .replaces(W100TemperatureMeasurement, endpoint_id=1)
    .replaces(W100ButtonCluster, endpoint_id=1)
    .replaces(W100ButtonCluster, endpoint_id=2)
    .replaces(W100ButtonCluster, endpoint_id=3)
    .device_automation_triggers(W100ButtonCluster.automation_triggers())
    .adds(W100PmtsdCluster, endpoint_id=1)
    .adds(W100ThermostatControlModeCluster, endpoint_id=1)
    .adds(W100ExternalSensorsCluster, endpoint_id=1)
    .adds(W100ThermostatCluster, endpoint_id=1)
    .adds(W100FanCluster, endpoint_id=1)
    .prevent_default_entity_creation(
        endpoint_id=1,
        cluster_id=Thermostat.cluster_id,
        function=lambda e: type(e).__name__ in (
            "ThermostatHVACAction",
            "SetpointChangeSourceTimestamp",
            "MaxHeatSetpointLimit",
            "MinHeatSetpointLimit",
        ),
    )
    .switch(
        attribute_name="thermostat_line_show_fan",
        cluster_id=W100PmtsdCluster.cluster_id,
        entity_type=EntityType.CONFIG,
        translation_key="thermostat_line_show_fan",
        fallback_name="Thermostat line: show fan",
    )
    .switch(
        attribute_name="thermostat_control_mode",
        cluster_id=W100ThermostatControlModeCluster.cluster_id,
        entity_type=EntityType.CONFIG,
        translation_key="thermostat_control_mode",
        fallback_name="Thermostat control mode",
    )
    .number(
        attribute_name="external_temperature",
        cluster_id=W100ExternalSensorsCluster.cluster_id,
        device_class=NumberDeviceClass.TEMPERATURE,
        entity_type=EntityType.STANDARD,
        min_value=-99.9,
        max_value=100.0,
        step=0.1,
        multiplier=0.01,
        unit=UnitOfTemperature.CELSIUS,
        mode="box",
        translation_key="external_temperature",
        fallback_name="External temperature",
    )
    .number(
        attribute_name="external_humidity",
        cluster_id=W100ExternalSensorsCluster.cluster_id,
        device_class=NumberDeviceClass.HUMIDITY,
        entity_type=EntityType.STANDARD,
        min_value=0.0,
        max_value=99.0,
        step=1.0,
        multiplier=0.01,
        unit=PERCENTAGE,
        mode="box",
        translation_key="external_humidity",
        fallback_name="External humidity",
    )
    .switch(
        attribute_name="external_sensor",
        cluster_id=W100ExternalSensorsCluster.cluster_id,
        entity_type=EntityType.CONFIG,
        translation_key="external_sensor",
        fallback_name="External sensor",
    )
    .number(
        attribute_name="high_temperature",
        cluster_id=AqaraW100ManuCluster.cluster_id,
        device_class=NumberDeviceClass.TEMPERATURE,
        entity_type=EntityType.CONFIG,
        min_value=26.0,
        max_value=60.0,
        step=0.5,
        multiplier=0.01,
        initially_disabled=True,
        unit=UnitOfTemperature.CELSIUS,
        translation_key="high_temperature",
        fallback_name="High temperature",
    )
    .number(
        attribute_name="low_temperature",
        cluster_id=AqaraW100ManuCluster.cluster_id,
        device_class=NumberDeviceClass.TEMPERATURE,
        entity_type=EntityType.CONFIG,
        min_value=-20.0,
        max_value=20.0,
        step=0.5,
        multiplier=0.01,
        initially_disabled=True,
        unit=UnitOfTemperature.CELSIUS,
        translation_key="low_temperature",
        fallback_name="Low temperature",
    )
    .number(
        attribute_name="high_humidity",
        cluster_id=AqaraW100ManuCluster.cluster_id,
        entity_type=EntityType.CONFIG,
        min_value=65.0,
        max_value=100.0,
        step=1.0,
        multiplier=0.01,
        initially_disabled=True,
        unit=PERCENTAGE,
        translation_key="high_humidity",
        fallback_name="High humidity",
    )
    .number(
        attribute_name="low_humidity",
        cluster_id=AqaraW100ManuCluster.cluster_id,
        entity_type=EntityType.CONFIG,
        min_value=0.0,
        max_value=30.0,
        step=1.0,
        multiplier=0.01,
        initially_disabled=True,
        unit=PERCENTAGE,
        translation_key="low_humidity",
        fallback_name="Low humidity",
    )
    .enum(
        attribute_name="temperature_alert",
        enum_class=AlertState,
        cluster_id=AqaraW100ManuCluster.cluster_id,
        entity_platform=EntityPlatform.SENSOR,
        entity_type=EntityType.DIAGNOSTIC,
        initially_disabled=True,
        translation_key="temperature_alert",
        fallback_name="Temperature alert",
    )
    .enum(
        attribute_name="humidity_alert",
        enum_class=AlertState,
        cluster_id=AqaraW100ManuCluster.cluster_id,
        entity_platform=EntityPlatform.SENSOR,
        entity_type=EntityType.DIAGNOSTIC,
        initially_disabled=True,
        translation_key="humidity_alert",
        fallback_name="Humidity alert",
    )
    .enum(
        attribute_name="temp_humidity_sampling",
        enum_class=SamplingFrequency,
        cluster_id=AqaraW100ManuCluster.cluster_id,
        entity_type=EntityType.CONFIG,
        translation_key="temp_humidity_sampling",
        fallback_name="Temperature and humidity sampling",
    )
    .number(
        attribute_name="temp_humidity_sampling_period",
        cluster_id=AqaraW100ManuCluster.cluster_id,
        device_class=NumberDeviceClass.DURATION,
        entity_type=EntityType.CONFIG,
        min_value=0.5,
        max_value=600.0,
        step=0.5,
        multiplier=0.001,
        initially_disabled=True,
        unit=UnitOfTime.SECONDS,
        translation_key="temp_humidity_sampling_period",
        fallback_name="Temperature and humidity sampling period",
    )
    .enum(
        attribute_name="temp_reporting_mode",
        enum_class=ReportMode,
        cluster_id=AqaraW100ManuCluster.cluster_id,
        entity_type=EntityType.CONFIG,
        initially_disabled=True,
        translation_key="temp_reporting_mode",
        fallback_name="Temperature reporting mode",
    )
    .number(
        attribute_name="temp_reporting_interval",
        cluster_id=AqaraW100ManuCluster.cluster_id,
        device_class=NumberDeviceClass.DURATION,
        entity_type=EntityType.CONFIG,
        min_value=1.0,
        max_value=600.0,
        step=1.0,
        multiplier=0.001,
        initially_disabled=True,
        unit=UnitOfTime.SECONDS,
        translation_key="temp_reporting_interval",
        fallback_name="Temperature reporting period",
    )
    .number(
        attribute_name="temp_reporting_threshold",
        cluster_id=AqaraW100ManuCluster.cluster_id,
        device_class=NumberDeviceClass.TEMPERATURE,
        entity_type=EntityType.CONFIG,
        min_value=0.2,
        max_value=3.0,
        step=0.1,
        multiplier=0.01,
        initially_disabled=True,
        unit=UnitOfTemperature.CELSIUS,
        translation_key="temp_reporting_threshold",
        fallback_name="Temperature reporting threshold",
    )
    .enum(
        attribute_name="humidity_reporting_mode",
        enum_class=ReportMode,
        cluster_id=AqaraW100ManuCluster.cluster_id,
        entity_type=EntityType.CONFIG,
        initially_disabled=True,
        translation_key="humidity_reporting_mode",
        fallback_name="Humidity reporting mode",
    )
    .number(
        attribute_name="humidity_reporting_interval",
        cluster_id=AqaraW100ManuCluster.cluster_id,
        device_class=NumberDeviceClass.DURATION,
        entity_type=EntityType.CONFIG,
        min_value=1.0,
        max_value=600.0,
        step=1.0,
        multiplier=0.001,
        initially_disabled=True,
        unit=UnitOfTime.SECONDS,
        translation_key="humidity_reporting_interval",
        fallback_name="Humidity reporting period",
    )
    .number(
        attribute_name="humidity_reporting_threshold",
        cluster_id=AqaraW100ManuCluster.cluster_id,
        entity_type=EntityType.CONFIG,
        min_value=2.0,
        max_value=10.0,
        step=0.5,
        multiplier=0.01,
        initially_disabled=True,
        unit=PERCENTAGE,
        translation_key="humidity_reporting_threshold",
        fallback_name="Humidity reporting threshold",
    )
    .switch(
        attribute_name="thermostat_line_auto_hide",
        cluster_id=AqaraW100ManuCluster.cluster_id,
        entity_type=EntityType.CONFIG,
        on_value=0,
        off_value=1,
        translation_key="thermostat_line_auto_hide",
        fallback_name="Thermostat line: auto hide",
    )
    .add_to_registry()
)
