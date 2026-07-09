"""Aqara ctrl_neutral quirks."""

from typing import Any, Final

from zhaquirks import EventableCluster
from zhaquirks.builder import QuirkBuilder
from zhaquirks.clusters import CustomCluster
from zhaquirks.const import (
    ARGS,
    ATTRIBUTE_ID,
    ATTRIBUTE_NAME,
    BUTTON,
    BUTTON_1,
    BUTTON_2,
    CLUSTER_ID,
    COMMAND,
    COMMAND_ATTRIBUTE_UPDATED,
    COMMAND_DOUBLE,
    COMMAND_HOLD,
    COMMAND_RELEASE,
    ENDPOINT_ID,
    VALUE,
)
from zigpy import types as t
from zigpy.profiles import zha
from zigpy.zcl import ClusterType, foundation
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


class RelayOperationMode1(t.enum8):
    """Relay operation mode values for lumi.ctrl_neutral1."""

    Relay = 18
    Decoupled = 254


class RelayOperationMode2(t.enum8):
    """Relay operation mode values for lumi.ctrl_neutral2."""

    Left_relay = 18
    Right_relay = 34
    Decoupled = 254


AQARA_NODE_DESCRIPTOR: Final = NodeDescriptor(
    logical_type=2,
    complex_descriptor_available=0,
    user_descriptor_available=0,
    reserved=0,
    aps_flags=0,
    frequency_band=8,
    mac_capability_flags=132,
    manufacturer_code=4151,
    maximum_buffer_size=127,
    maximum_incoming_transfer_size=100,
    server_mask=0,
    maximum_outgoing_transfer_size=100,
    descriptor_capability_field=0,
)


class CtrlNeutralBasicCluster(CustomCluster, Basic):
    """Basic cluster with relay operation mode attributes."""

    class AttributeDefs(Basic.AttributeDefs):
        """Attribute definitions."""

        operation_mode_left: Final = ZCLAttributeDef(
            id=0xFF22,
            type=t.uint8_t,
            manufacturer_code=AQARA_MFG_CODE,
        )
        operation_mode_right: Final = ZCLAttributeDef(
            id=0xFF23,
            type=t.uint8_t,
            manufacturer_code=AQARA_MFG_CODE,
        )


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
        """Prevent remote configure reporting."""
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


class CtrlNeutralButtonOnOffCluster(EventableCluster, OnOff):
    """Button OnOff cluster used for device automation triggers."""

    async def _configure_reporting(  # pylint: disable=W0221
        self,
        *args: Any,
        **kwargs: Any,
    ) -> tuple[foundation.ConfigureReportingResponse]:
        """Prevent remote configure reporting."""
        return (foundation.ConfigureReportingResponse.deserialize(b"\x00")[0],)


def _attribute_updated_args(value: int) -> dict[str, Any]:
    """Build attribute_updated event args for OnOff button reports."""
    return {
        ATTRIBUTE_ID: OnOff.AttributeDefs.on_off.id,
        ATTRIBUTE_NAME: OnOff.AttributeDefs.on_off.name,
        VALUE: value,
    }


def _attribute_updated_trigger(endpoint_id: int, value: int) -> dict[str, Any]:
    """Build a device automation trigger for an OnOff attribute update."""
    return {
        ENDPOINT_ID: endpoint_id,
        CLUSTER_ID: OnOff.cluster_id,
        COMMAND: COMMAND_ATTRIBUTE_UPDATED,
        ARGS: _attribute_updated_args(value),
    }


CTRL_NEUTRAL_SINGLE_TRIGGERS: Final = {
    (COMMAND_HOLD, BUTTON): _attribute_updated_trigger(4, 0),
    (COMMAND_RELEASE, BUTTON): _attribute_updated_trigger(4, 1),
    (COMMAND_DOUBLE, BUTTON): _attribute_updated_trigger(4, 2),
}

CTRL_NEUTRAL_DOUBLE_TRIGGERS: Final = {
    (COMMAND_HOLD, BUTTON_1): _attribute_updated_trigger(4, 0),
    (COMMAND_RELEASE, BUTTON_1): _attribute_updated_trigger(4, 1),
    (COMMAND_DOUBLE, BUTTON_1): _attribute_updated_trigger(4, 2),
    (COMMAND_HOLD, BUTTON_2): _attribute_updated_trigger(5, 0),
    (COMMAND_RELEASE, BUTTON_2): _attribute_updated_trigger(5, 1),
    (COMMAND_DOUBLE, BUTTON_2): _attribute_updated_trigger(5, 2),
}


(
    QuirkBuilder("LUMI", "lumi.ctrl_neutral1")
    .applies_to("LUMI", "lumi.switch.b1lacn02")
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
    # .removes(Ota.cluster_id)
    # .removes(Ota.cluster_id, endpoint_id=1, cluster_type=ClusterType.Client)
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
    .applies_to("LUMI", "lumi.switch.b2lacn02")
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
    # .removes(Ota.cluster_id)
    # .removes(Ota.cluster_id, endpoint_id=1, cluster_type=ClusterType.Client)
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
