"""Quirk for Aqara wall switches lumi.ctrl_neutral."""

from typing import Any, Final

from zigpy import types as t
from zigpy.profiles import zha
from zigpy.zcl import AttributeReportedEvent, ClusterType, foundation
from zigpy.zcl.clusters.general import (
    Basic,
    BinaryOutput,
    DeviceTemperature,
    Identify,
    OnOff,
    PowerConfiguration,
)
from zigpy.zcl.foundation import ZCLAttributeDef
from zigpy.zdo.types import NodeDescriptor

from zhaquirks import CustomCluster, LocalDataCluster
from zhaquirks.builder import QuirkBuilder
from zhaquirks.const import (
    BUTTON_1,
    BUTTON_2,
    COMMAND,
    COMMAND_DOUBLE,
    COMMAND_HOLD,
    COMMAND_RELEASE,
    COMMAND_SINGLE,
    DOUBLE_PRESS,
    ENDPOINT_ID,
    LONG_PRESS,
    LONG_RELEASE,
    SHORT_PRESS,
    ZHA_SEND_EVENT,
)
from zhaquirks.xiaomi import LUMI, OnOffCluster


AQARA_MFG_CODE: Final = 0x115F

AQARA_NODE_DESCRIPTOR: Final = NodeDescriptor(
    byte1=2,
    byte2=64,
    mac_capability_flags=132,
    manufacturer_code=4151,
    maximum_buffer_size=127,
    maximum_incoming_transfer_size=100,
    server_mask=0,
    maximum_outgoing_transfer_size=100,
    descriptor_capability_field=0,
)


class SingleRockerOperationMode(t.enum8):
    """Single-rocker operation mode."""

    Control_relay = 0x12
    Decoupled = 0xFE


class DoubleRockerOperationMode(t.enum8):
    """Double-rocker operation mode."""

    Control_left_relay = 0x12
    Control_right_relay = 0x22
    Decoupled = 0xFE


class CtrlNeutralBasicCluster(CustomCluster, Basic):
    """Basic cluster."""

    DEVICE_TEMPERATURE_TAG: Final = 0x03
    LEFT_RELAY_TAG: Final = 0x64
    RIGHT_RELAY_TAG: Final = 0x65

    class AttributeDefs(Basic.AttributeDefs):
        """Attribute definitions."""

        operation_mode_left: Final = ZCLAttributeDef(
            id=0xFF22,
            type=t.uint8_t,
            access="rwp",
            manufacturer_code=AQARA_MFG_CODE,
        )
        operation_mode_right: Final = ZCLAttributeDef(
            id=0xFF23,
            type=t.uint8_t,
            access="rwp",
            manufacturer_code=AQARA_MFG_CODE,
        )
        reset_request: Final = ZCLAttributeDef(
            id=0xFFF0,
            type=t.LVBytes,
            access="rwp",
            manufacturer_code=AQARA_MFG_CODE,
        )
        aqara_heartbeat: Final = ZCLAttributeDef(
            id=0xFF01,
            type=t.LVBytes,
            access="rp",
            manufacturer_code=AQARA_MFG_CODE,
        )

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        """Init."""
        super().__init__(*args, **kwargs)
        self.on_event(AttributeReportedEvent.event_type, self._handle_attribute_report)

    def deserialize(self, data):
        """Normalize Aqara heartbeat data type."""
        hdr, payload = foundation.ZCLHeader.deserialize(data)

        if (
            hdr.frame_control.frame_type == foundation.FrameType.GLOBAL_COMMAND
            and hdr.command_id == foundation.GeneralCommand.Report_Attributes
            and int.from_bytes(payload[:2], "little") == self.AttributeDefs.aqara_heartbeat.id
            and payload[2:3] == b"\x42"
        ):
            payload = payload[:2] + b"\x41" + payload[3:]

        return super().deserialize(hdr.serialize() + payload)

    async def apply_custom_configuration(self, *args: Any, **kwargs: Any) -> None:
        """Read current device state."""
        await self.read_attributes([self.AttributeDefs.operation_mode_left.id])
        await self.endpoint.device_temperature.read_attributes(
            [DeviceTemperature.AttributeDefs.current_temperature.id]
        )
        await self.endpoint.device.endpoints[2].on_off.read_attributes(
            [OnOff.AttributeDefs.on_off.id]
        )

        if self.endpoint.device.model == "lumi.ctrl_neutral2":
            await self.read_attributes([self.AttributeDefs.operation_mode_right.id])
            await self.endpoint.device.endpoints[3].on_off.read_attributes(
                [OnOff.AttributeDefs.on_off.id]
            )

    def _handle_attribute_report(self, event: AttributeReportedEvent) -> None:
        """Handle attribute report events."""
        # Prevent the device from resetting on a long button press.
        if event.attribute_id == self.AttributeDefs.reset_request.id and bytes(
            event.value
        ).startswith(bytes.fromhex("AA 10 05 41 87")):
            self.create_catching_task(
                self.write_attributes(
                    {
                        self.AttributeDefs.reset_request: bytes.fromhex(
                            "AA 10 05 41 47 01 01 10 01"
                        )
                    },
                    update_cache=False,
                )
            )

        if event.attribute_id == self.AttributeDefs.aqara_heartbeat.id:
            values = self._parse_heartbeat_report(event.value)

            if self.DEVICE_TEMPERATURE_TAG in values:
                self.endpoint.device_temperature.update_attribute(
                    DeviceTemperature.AttributeDefs.current_temperature.id,
                    values[self.DEVICE_TEMPERATURE_TAG],
                )

            if self.LEFT_RELAY_TAG in values:
                self.endpoint.device.endpoints[2].on_off.update_attribute(
                    OnOff.AttributeDefs.on_off.id,
                    values[self.LEFT_RELAY_TAG],
                )

            if self.RIGHT_RELAY_TAG in values and self.endpoint.device.model == "lumi.ctrl_neutral2":
                self.endpoint.device.endpoints[3].on_off.update_attribute(
                    OnOff.AttributeDefs.on_off.id,
                    values[self.RIGHT_RELAY_TAG],
                )

    def _parse_heartbeat_report(self, data: bytes) -> dict[int, Any]:
        """Parse Aqara heartbeat."""
        values: dict[int, Any] = {}

        while len(data) >= 2:
            tag = data[0]

            try:
                typed_value, data = foundation.TypeValue.deserialize(data[1:])
            except (KeyError, ValueError):
                self.debug("Failed to deserialize Aqara heartbeat tag 0x%02X from %r", tag, data)
                return values

            values[tag] = typed_value.value

        return values


class CtrlNeutralButtonOnOff(LocalDataCluster, OnOff):
    """Button OnOff cluster."""

    PRESS_TYPES: Final = {
        (0, 1): COMMAND_SINGLE,
        (2,): COMMAND_DOUBLE,
        (0,): COMMAND_HOLD,
        (1,): COMMAND_RELEASE,
    }

    def handle_cluster_general_request(
        self,
        hdr: foundation.ZCLHeader,
        args: Any,
        *,
        dst_addressing: t.AddrMode | None = None,
    ) -> None:
        """Handle cluster general requests."""
        if hdr.command_id == foundation.GeneralCommand.Report_Attributes:
            values = tuple(
                int(attr.value.value)
                for attr in args.attribute_reports
                if attr.attrid == OnOff.AttributeDefs.on_off.id
            )

            if command := self.PRESS_TYPES.get(values):
                self.listener_event(ZHA_SEND_EVENT, command, {})

        super().handle_cluster_general_request(hdr, args, dst_addressing=dst_addressing)


class CtrlNeutralDeviceTemperatureCluster(CustomCluster, DeviceTemperature):
    """Normalize device temperature values."""

    def _update_attribute(self, attrid, value):
        """Normalize temperature reports."""
        if attrid == self.AttributeDefs.current_temperature.id and value is not None:
            value *= 100
        super()._update_attribute(attrid, value)


base_quirk = (
    QuirkBuilder()
    .node_descriptor(AQARA_NODE_DESCRIPTOR)
    .replaces(CtrlNeutralBasicCluster, endpoint_id=1)
    .replaces(OnOffCluster, endpoint_id=2)
    .replaces(CtrlNeutralButtonOnOff, endpoint_id=4)
    .replaces(CtrlNeutralDeviceTemperatureCluster, endpoint_id=1)
    .prevent_default_entity_creation(endpoint_id=4, cluster_id=OnOff.cluster_id)
    .replaces_endpoint(2, device_type=zha.DeviceType.ON_OFF_SWITCH)
    .removes(Identify.cluster_id, endpoint_id=1)
    .removes_endpoint(6)
    .removes_endpoint(8)
    .skip_configuration()
    .device_automation_triggers(
        {
            (SHORT_PRESS, BUTTON_1): {ENDPOINT_ID: 4, COMMAND: COMMAND_SINGLE},
            (DOUBLE_PRESS, BUTTON_1): {ENDPOINT_ID: 4, COMMAND: COMMAND_DOUBLE},
            (LONG_PRESS, BUTTON_1): {ENDPOINT_ID: 4, COMMAND: COMMAND_HOLD},
            (LONG_RELEASE, BUTTON_1): {ENDPOINT_ID: 4, COMMAND: COMMAND_RELEASE},
        }
    )
)


(
    base_quirk.clone()
    .applies_to(LUMI, "lumi.ctrl_neutral1")
    .friendly_name(manufacturer="Aqara", model="Wall Switch (No Neutral, Single Rocker)")
    .removes_endpoint(3)
    .removes_endpoint(5)
    .enum(
        attribute_name="operation_mode_left",
        cluster_id=Basic.cluster_id,
        enum_class=SingleRockerOperationMode,
        translation_key="relay_operation_mode",
        fallback_name="Operation mode",
    )
    .add_to_registry()
)


(
    base_quirk.clone()
    .applies_to(LUMI, "lumi.ctrl_neutral2")
    .friendly_name(manufacturer="Aqara", model="Wall Switch (No Neutral, Double Rocker)")
    .prevent_default_entity_creation(endpoint_id=5, cluster_id=OnOff.cluster_id)
    .replaces(OnOffCluster, endpoint_id=3)
    .replaces(CtrlNeutralButtonOnOff, endpoint_id=5)
    .replaces_endpoint(3, device_type=zha.DeviceType.ON_OFF_SWITCH)
    .device_automation_triggers(
        {
            (SHORT_PRESS, BUTTON_2): {ENDPOINT_ID: 5, COMMAND: COMMAND_SINGLE},
            (DOUBLE_PRESS, BUTTON_2): {ENDPOINT_ID: 5, COMMAND: COMMAND_DOUBLE},
            (LONG_PRESS, BUTTON_2): {ENDPOINT_ID: 5, COMMAND: COMMAND_HOLD},
            (LONG_RELEASE, BUTTON_2): {ENDPOINT_ID: 5, COMMAND: COMMAND_RELEASE},
        }
    )
    .enum(
        attribute_name="operation_mode_left",
        cluster_id=Basic.cluster_id,
        enum_class=DoubleRockerOperationMode,
        translation_key="relay_operation_mode_left",
        fallback_name="Operation mode left",
    )
    .enum(
        attribute_name="operation_mode_right",
        cluster_id=Basic.cluster_id,
        enum_class=DoubleRockerOperationMode,
        translation_key="relay_operation_mode_right",
        fallback_name="Operation mode right",
    )
    .add_to_registry()
)