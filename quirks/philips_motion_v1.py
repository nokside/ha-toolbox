"""Quirk v2 for Philips Hue SML001/SML002 motion sensors."""

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


(
    QuirkBuilder(PHILIPS, "SML001")
    .applies_to(PHILIPS, "SML002")
    .replaces(PhilipsMotionBasicCluster, endpoint_id=2)
    .replaces(PhilipsOccupancySensing, endpoint_id=2)
    # Duplicate motion entity
    .prevent_default_entity_creation(
        endpoint_id=1,
        cluster_id=OnOff.cluster_id,
        cluster_type=ClusterType.Client,
    )
    # ZHA matches SML002 with the native five-level HueV2MotionSensitivity
    # entity, but SML002 is a v1 sensor and uses only three sensitivity levels.
    .prevent_default_entity_creation(
        endpoint_id=2,
        cluster_id=OccupancySensing.cluster_id,
        unique_id_suffix="motion_sensitivity",
    )
    .enum(
        attribute_name="sensitivity",
        cluster_id=OccupancySensing.cluster_id,
        endpoint_id=2,
        enum_class=MotionSensitivity,
        translation_key="motion_sensitivity",
        fallback_name="Motion sensitivity",
    )
    .add_to_registry()
)
