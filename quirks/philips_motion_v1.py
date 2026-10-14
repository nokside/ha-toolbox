"""Quirk for Philips Hue SML001/SML002 motion sensors."""

from typing import Final

from zigpy import types as t
from zigpy.zcl import ClusterType
from zigpy.zcl.clusters.general import Basic, OnOff
from zigpy.zcl.clusters.measurement import OccupancySensing
from zigpy.zcl.foundation import ZCLAttributeDef

from zhaquirks.builder import QuirkBuilder
from zhaquirks.clusters import CustomCluster
from zhaquirks.philips import PHILIPS, PhilipsOccupancySensing


PHILIPS_MFG_CODE: Final = 0x100B


class MotionSensitivity(t.enum8):
    """Hue motion sensitivity values."""

    Low = 0
    Medium = 1
    High = 2


class PhilipsMotionBasicCluster(CustomCluster, Basic):
    """Basic cluster."""

    class AttributeDefs(Basic.AttributeDefs):
        """Attribute definitions."""

        trigger_indicator: Final = ZCLAttributeDef(
            id=0x0033,
            type=t.Bool,
            access="rw",
            manufacturer_code=PHILIPS_MFG_CODE,
        )


base_quirk = (
    QuirkBuilder()
    .replaces(PhilipsMotionBasicCluster, endpoint_id=2)
    .replaces(PhilipsOccupancySensing, endpoint_id=2)
    # Duplicate motion entity
    .prevent_default_entity_creation(
        endpoint_id=1,
        cluster_id=OnOff.cluster_id,
    )
    .switch(
        attribute_name="trigger_indicator",
        cluster_id=Basic.cluster_id,
        endpoint_id=2,
        translation_key="trigger_indicator",
        fallback_name="LED trigger indicator",
    )
    .enum(
        attribute_name="sensitivity",
        cluster_id=OccupancySensing.cluster_id,
        endpoint_id=2,
        enum_class=MotionSensitivity,
        translation_key="motion_sensitivity",
        fallback_name="Motion sensitivity",
    )
)

(
    base_quirk.clone()
    .applies_to(PHILIPS, "SML001")
    .friendly_name(manufacturer="Philips", model="Hue Motion Sensor")
    .add_to_registry()
)

(
    base_quirk.clone()
    .applies_to(PHILIPS, "SML002")
    .friendly_name(manufacturer="Philips", model="Hue Outdoor Motion Sensor")
    .add_to_registry()
)