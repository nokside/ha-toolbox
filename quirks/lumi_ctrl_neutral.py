"""Aqara ctrl_neutral quirks."""

from typing import Final

from zigpy import types as t
from zigpy.profiles import zha
from zigpy.quirks.v2 import QuirkBuilder
from zigpy.zcl import ClusterType, foundation
from zigpy.zcl.clusters.general import (
    Basic,
    BinaryOutput,
    DeviceTemperature,
    Identify,
    OnOff,
    Ota,
    PowerConfiguration,
)
from zigpy.zcl.foundation import ZCLAttributeDef

from zhaquirks import EventableCluster
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
from zhaquirks.xiaomi import (
    XIAOMI_NODE_DESC,
    BasicCluster as XiaomiBasicCluster,
    OnOffCluster as XiaomiOnOffCluster,
)

AQARA_MFG_CODE: Final = 0x115F

CTRL_NEUTRAL_NODE_DESC = XIAOMI_NODE_DESC.replace(mac_capability_flags=132)

class RelayOperationMode1(t.enum8):
    """Relay operation mode values for Aqara wall switches lumi.ctrl_neutral1."""

    Relay = 18
    Decoupled = 254

class RelayOperationMode2(t.enum8):
    """Relay operation mode values for Aqara wall switches lumi.ctrl_neutral2."""

    Left_relay = 18
    Right_relay = 34
    Decoupled = 254


class CtrlNeutralBasicCluster(XiaomiBasicCluster):
    """Basic cluster with relay operation mode attributes."""

    class AttributeDefs(XiaomiBasicCluster.AttributeDefs):
        """Attribute definitions."""

        operation_mode_left: ZCLAttributeDef = ZCLAttributeDef(
            id=0xFF22,
            type=t.uint8_t,
            manufacturer_code=AQARA_MFG_CODE,
        )
        operation_mode_right: ZCLAttributeDef = ZCLAttributeDef(
            id=0xFF23,
            type=t.uint8_t,
            manufacturer_code=AQARA_MFG_CODE,
        )


class XiaomiOnOffClusterFakeReporting(XiaomiOnOffCluster):
    """OnOff cluster with fake reporting response to avoid reconfiguration issues."""

    async def _configure_reporting(self, *args, **kwargs):
        return (foundation.ConfigureReportingResponse.deserialize(b"\x00")[0],)


class WallSwitchOnOffCluster(EventableCluster, OnOff):
    """Button OnOff cluster with fake reporting response to avoid reconfiguration issues."""

    async def _configure_reporting(self, *args, **kwargs):
        return (foundation.ConfigureReportingResponse.deserialize(b"\x00")[0],)


ATTR_ON_OFF = OnOff.AttributeDefs.on_off.name
ATTR_ON_OFF_ID = OnOff.AttributeDefs.on_off.id


def _attribute_updated_args(value: int) -> dict:
    return {ATTRIBUTE_ID: ATTR_ON_OFF_ID, ATTRIBUTE_NAME: ATTR_ON_OFF, VALUE: value}


def _attribute_updated_trigger(endpoint_id: int, value: int) -> dict:
    return {
        ENDPOINT_ID: endpoint_id,
        CLUSTER_ID: OnOff.cluster_id,
        COMMAND: COMMAND_ATTRIBUTE_UPDATED,
        ARGS: _attribute_updated_args(value),
    }


CTRL_NEUTRAL_SINGLE_TRIGGERS = {
    (COMMAND_HOLD, BUTTON): _attribute_updated_trigger(4, 0),
    (COMMAND_RELEASE, BUTTON): _attribute_updated_trigger(4, 1),
    (COMMAND_DOUBLE, BUTTON): _attribute_updated_trigger(4, 2),
}

CTRL_NEUTRAL_DOUBLE_TRIGGERS = {
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
    .friendly_name(manufacturer="Aqara", model="Wall Switch (No Neutral, Single Rocker)")
    .node_descriptor(CTRL_NEUTRAL_NODE_DESC)
    .prevent_default_entity_creation(endpoint_id=4, cluster_id=OnOff.cluster_id)
    .device_automation_triggers(CTRL_NEUTRAL_SINGLE_TRIGGERS)
    .replaces(CtrlNeutralBasicCluster, endpoint_id=1)
    .replaces(XiaomiOnOffClusterFakeReporting, endpoint_id=2)
    .replaces(WallSwitchOnOffCluster, endpoint_id=4)
    .replaces_endpoint(2, device_type=zha.DeviceType.ON_OFF_SWITCH)
    .removes(PowerConfiguration.cluster_id, endpoint_id=1, cluster_type=ClusterType.Server)
    .removes(DeviceTemperature.cluster_id, endpoint_id=1, cluster_type=ClusterType.Server)
    .removes(Identify.cluster_id, endpoint_id=1, cluster_type=ClusterType.Server)
    .removes(Ota.cluster_id, endpoint_id=1, cluster_type=ClusterType.Server)
    .removes(Ota.cluster_id, endpoint_id=1, cluster_type=ClusterType.Client)
    .removes(BinaryOutput.cluster_id, endpoint_id=2, cluster_type=ClusterType.Server)
    .removes_endpoint(3)
    .removes_endpoint(5)
    .removes_endpoint(6)
    .removes_endpoint(8)
    .enum(
        CtrlNeutralBasicCluster.AttributeDefs.operation_mode_left.name,
        RelayOperationMode1,
        Basic.cluster_id,
        endpoint_id=1,
        translation_key="relay_operation_mode",
        fallback_name="Operation mode",
    )
    .add_to_registry()
)

(
    QuirkBuilder("LUMI", "lumi.ctrl_neutral2")
    .applies_to("LUMI", "lumi.switch.b2lacn02")
    .friendly_name(manufacturer="Aqara", model="Wall Switch (No Neutral, Double Rocker)")
    .node_descriptor(CTRL_NEUTRAL_NODE_DESC)
    .device_automation_triggers(CTRL_NEUTRAL_DOUBLE_TRIGGERS)
    .prevent_default_entity_creation(endpoint_id=4, cluster_id=OnOff.cluster_id)
    .prevent_default_entity_creation(endpoint_id=5, cluster_id=OnOff.cluster_id)
    .replaces(CtrlNeutralBasicCluster, endpoint_id=1)
    .replaces(XiaomiOnOffClusterFakeReporting, endpoint_id=2)
    .replaces(XiaomiOnOffClusterFakeReporting, endpoint_id=3)
    .replaces(WallSwitchOnOffCluster, endpoint_id=4)
    .replaces(WallSwitchOnOffCluster, endpoint_id=5)
    .replaces_endpoint(2, device_type=zha.DeviceType.ON_OFF_SWITCH)
    .replaces_endpoint(3, device_type=zha.DeviceType.ON_OFF_SWITCH)
    .removes(PowerConfiguration.cluster_id, endpoint_id=1, cluster_type=ClusterType.Server)
    .removes(DeviceTemperature.cluster_id, endpoint_id=1, cluster_type=ClusterType.Server)
    .removes(Identify.cluster_id, endpoint_id=1, cluster_type=ClusterType.Server)
    .removes(Ota.cluster_id, endpoint_id=1, cluster_type=ClusterType.Server)
    .removes(Ota.cluster_id, endpoint_id=1, cluster_type=ClusterType.Client)
    .removes(BinaryOutput.cluster_id, endpoint_id=2, cluster_type=ClusterType.Server)
    .removes(BinaryOutput.cluster_id, endpoint_id=3, cluster_type=ClusterType.Server)
    .removes_endpoint(6)
    .removes_endpoint(8)
    .enum(
        CtrlNeutralBasicCluster.AttributeDefs.operation_mode_left.name,
        RelayOperationMode2,
        Basic.cluster_id,
        endpoint_id=1,
        translation_key="relay_operation_mode_left",
        fallback_name="Operation mode left",
    )
    .enum(
        CtrlNeutralBasicCluster.AttributeDefs.operation_mode_right.name,
        RelayOperationMode2,
        Basic.cluster_id,
        endpoint_id=1,
        translation_key="relay_operation_mode_right",
        fallback_name="Operation mode right",
    )
    .add_to_registry()
)
