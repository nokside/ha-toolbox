"""Quirk v2 for Aqara wall switches lumi.ctrl_neutral."""

from typing import Any, Final

from zhaquirks import CustomCluster
from zhaquirks.builder import QuirkBuilder
from zhaquirks.const import (
    COMMAND,
    COMMAND_DOUBLE,
    COMMAND_HOLD,
    COMMAND_RELEASE,
    COMMAND_SINGLE,
    DOUBLE_PRESS,
    ENDPOINT_ID,
    LEFT,
    LONG_PRESS,
    LONG_RELEASE,
    RIGHT,
    SHORT_PRESS,
    ZHA_SEND_EVENT,
)
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


class RelayOperationMode1(t.enum8):
    """Single-rocker relay operation mode."""

    Control_relay = 0x12
    Decoupled = 0xFE


class RelayOperationMode2(t.enum8):
    """Double-rocker relay operation mode."""

    Control_left_relay = 0x12
    Control_right_relay = 0x22
    Decoupled = 0xFE


class CtrlNeutralBasicCluster(CustomCluster, Basic):
    """Basic cluster."""

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

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        """Initialize reset-request handling."""
        super().__init__(*args, **kwargs)
        self.on_event(
            AttributeReportedEvent.event_type,
            self._handle_attribute_report,
        )

    def _handle_attribute_report(
        self,
        event: AttributeReportedEvent,
    ) -> None:
        """Respond to an Aqara reset request."""
        if event.attribute_id == self.AttributeDefs.reset_request.id and bytes(
            event.value
        ).startswith(bytes.fromhex("AA 10 05 41 87")):
            self.create_catching_task(
                self.write_attributes(
                    {
                        self.AttributeDefs.reset_request: bytes.fromhex(
                            "AA 10 05 41 47 01 01 10 01"
                        ),
                    },
                    update_cache=False,
                )
            )

    async def apply_custom_configuration(self, *args: Any, **kwargs: Any) -> None:
        """Read relay operation modes during device configuration."""
        attributes = [self.AttributeDefs.operation_mode_left]

        if self.endpoint.device.model == "lumi.ctrl_neutral2":
            attributes.append(self.AttributeDefs.operation_mode_right)

        for attr_def in attributes:
            try:
                await self.read_attributes(
                    [attr_def],
                    allow_cache=False,
                )
            except Exception as exc:
                self.debug("Failed to read attr 0x%04X: %r", attr_def.id, exc)


class CtrlNeutralSwitchOnOffCluster(CustomCluster, OnOff):
    """OnOff cluster for Aqara no-neutral relay control."""

    ZHA_COORDINATOR_ENDPOINT: Final = 1
    CLUSTER_COMMAND_FRAME_CONTROL: Final = 0x01
    ON_OFF_COMMANDS: Final = (
        OnOff.ServerCommandDefs.off.id,
        OnOff.ServerCommandDefs.on.id,
        OnOff.ServerCommandDefs.toggle.id,
    )

    async def _configure_reporting(  # pylint: disable=W0221
        self,
        *args: Any,
        **kwargs: Any,
    ) -> tuple[foundation.ConfigureReportingResponse]:
        """Prevent remote reporting configuration."""
        return (foundation.ConfigureReportingResponse.deserialize(b"\x00")[0],)

    def command(
        self,
        command_id: foundation.GeneralCommand | int | t.uint8_t,
        *args: Any,
        manufacturer: int | t.uint16_t | None = None,
        expect_reply: bool = True,
        tsn: int | t.uint8_t | None = None,
        **kwargs: Any,
    ) -> Any:
        """Send raw OnOff commands required by Aqara no-neutral switches."""
        command_id = int(command_id)

        if command_id not in self.ON_OFF_COMMANDS or args:
            return super().command(
                command_id,
                *args,
                manufacturer=manufacturer,
                expect_reply=expect_reply,
                tsn=tsn,
                **kwargs,
            )

        if tsn is None:
            tsn = self.endpoint.device.application.get_sequence()

        return self.endpoint.device.request(
            zha.PROFILE_ID,
            self.cluster_id,
            self.ZHA_COORDINATOR_ENDPOINT,
            self.endpoint.endpoint_id,
            tsn,
            bytes(
                [
                    self.CLUSTER_COMMAND_FRAME_CONTROL,
                    int(tsn),
                    command_id,
                ]
            ),
            expect_reply=expect_reply,
        )


class CtrlNeutralButtonOnOffCluster(CustomCluster, OnOff):
    """Normalize Aqara button report frames into semantic ZHA events."""

    ON_OFF_ATTR_ID: Final = OnOff.AttributeDefs.on_off.id

    FRAME_COMMANDS: Final = {
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
        """Emit one semantic button event for each attribute-report frame."""
        if hdr.command_id == foundation.GeneralCommand.Report_Attributes:
            values = tuple(
                int(attribute.value.value)
                for attribute in args.attribute_reports
                if attribute.attrid == self.ON_OFF_ATTR_ID
            )

            if values:
                command = self.FRAME_COMMANDS.get(values)

                if command is not None:
                    self.listener_event(ZHA_SEND_EVENT, command, {})
                else:
                    self.debug(
                        "Ignoring unknown Aqara button frame: %s",
                        values,
                    )

        super().handle_cluster_general_request(
            hdr,
            args,
            dst_addressing=dst_addressing,
        )

    async def _configure_reporting(  # pylint: disable=W0221
        self,
        *args: Any,
        **kwargs: Any,
    ) -> tuple[foundation.ConfigureReportingResponse]:
        """Prevent remote reporting configuration."""
        return (foundation.ConfigureReportingResponse.deserialize(b"\x00")[0],)


COMMAND_TO_TRIGGER_TYPE: Final = {
    COMMAND_SINGLE: SHORT_PRESS,
    COMMAND_DOUBLE: DOUBLE_PRESS,
    COMMAND_HOLD: LONG_PRESS,
    COMMAND_RELEASE: LONG_RELEASE,
}

CTRL_NEUTRAL_SINGLE_TRIGGERS: Final = {
    (trigger_type, COMMAND_SINGLE): {
        COMMAND: command,
        ENDPOINT_ID: 4,
    }
    for command, trigger_type in COMMAND_TO_TRIGGER_TYPE.items()
}

CTRL_NEUTRAL_DOUBLE_TRIGGERS: Final = {
    (trigger_type, button): {
        COMMAND: command,
        ENDPOINT_ID: endpoint_id,
    }
    for endpoint_id, button in {
        4: LEFT,
        5: RIGHT,
    }.items()
    for command, trigger_type in COMMAND_TO_TRIGGER_TYPE.items()
}


(
    QuirkBuilder("LUMI", "lumi.ctrl_neutral1")
    .friendly_name(
        manufacturer="Aqara",
        model="Wall Switch (No Neutral, Single Rocker)",
    )
    .node_descriptor(AQARA_NODE_DESCRIPTOR)
    .prevent_default_entity_creation(endpoint_id=4, cluster_id=OnOff.cluster_id)
    .device_automation_triggers(CTRL_NEUTRAL_SINGLE_TRIGGERS)
    .replaces(CtrlNeutralBasicCluster)
    .replaces(CtrlNeutralSwitchOnOffCluster, endpoint_id=2)
    .replaces(CtrlNeutralButtonOnOffCluster, endpoint_id=4)
    .replaces_endpoint(2, device_type=zha.DeviceType.ON_OFF_SWITCH)
    .removes(
        PowerConfiguration.cluster_id, endpoint_id=1, cluster_type=ClusterType.Server
    )
    .removes(
        DeviceTemperature.cluster_id, endpoint_id=1, cluster_type=ClusterType.Server
    )
    .removes(Identify.cluster_id, endpoint_id=1, cluster_type=ClusterType.Server)
    .removes(BinaryOutput.cluster_id, endpoint_id=2, cluster_type=ClusterType.Server)
    .removes_endpoint(3)
    .removes_endpoint(5)
    .removes_endpoint(6)
    .removes_endpoint(8)
    .enum(
        attribute_name="operation_mode_left",
        enum_class=RelayOperationMode1,
        cluster_id=Basic.cluster_id,
        translation_key="relay_operation_mode",
        fallback_name="Operation mode",
    )
    .add_to_registry()
)

(
    QuirkBuilder("LUMI", "lumi.ctrl_neutral2")
    .friendly_name(
        manufacturer="Aqara",
        model="Wall Switch (No Neutral, Double Rocker)",
    )
    .node_descriptor(AQARA_NODE_DESCRIPTOR)
    .device_automation_triggers(CTRL_NEUTRAL_DOUBLE_TRIGGERS)
    .prevent_default_entity_creation(endpoint_id=4, cluster_id=OnOff.cluster_id)
    .prevent_default_entity_creation(endpoint_id=5, cluster_id=OnOff.cluster_id)
    .replaces(CtrlNeutralBasicCluster)
    .replaces(CtrlNeutralSwitchOnOffCluster, endpoint_id=2)
    .replaces(CtrlNeutralSwitchOnOffCluster, endpoint_id=3)
    .replaces(CtrlNeutralButtonOnOffCluster, endpoint_id=4)
    .replaces(CtrlNeutralButtonOnOffCluster, endpoint_id=5)
    .replaces_endpoint(2, device_type=zha.DeviceType.ON_OFF_SWITCH)
    .replaces_endpoint(3, device_type=zha.DeviceType.ON_OFF_SWITCH)
    .removes(
        PowerConfiguration.cluster_id, endpoint_id=1, cluster_type=ClusterType.Server
    )
    .removes(
        DeviceTemperature.cluster_id, endpoint_id=1, cluster_type=ClusterType.Server
    )
    .removes(Identify.cluster_id, endpoint_id=1, cluster_type=ClusterType.Server)
    .removes(BinaryOutput.cluster_id, endpoint_id=2, cluster_type=ClusterType.Server)
    .removes(BinaryOutput.cluster_id, endpoint_id=3, cluster_type=ClusterType.Server)
    .removes_endpoint(6)
    .removes_endpoint(8)
    .enum(
        attribute_name="operation_mode_left",
        enum_class=RelayOperationMode2,
        cluster_id=Basic.cluster_id,
        translation_key="relay_operation_mode_left",
        fallback_name="Operation mode left",
    )
    .enum(
        attribute_name="operation_mode_right",
        enum_class=RelayOperationMode2,
        cluster_id=Basic.cluster_id,
        translation_key="relay_operation_mode_right",
        fallback_name="Operation mode right",
    )
    .add_to_registry()
)
