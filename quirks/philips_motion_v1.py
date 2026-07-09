"""Quirk for Philips Hue motion sensors."""

from typing import Final

from zhaquirks.builder import QuirkBuilder
from zhaquirks.clusters import CustomCluster
from zigpy import types as t
from zigpy.zcl import ClusterType
from zigpy.zcl.clusters.general import Basic, OnOff
from zigpy.zcl.clusters.measurement import OccupancySensing
from zigpy.zcl.foundation import DataTypeId, ZCLAttributeDef


PHILIPS_MFG_CODE: Final = 0x100B


class MotionSensitivity(t.enum8):
    """Hue motion sensitivity values."""

    Low = 0
    Medium = 1
    High = 2


class PhilipsMotionBasicCluster(CustomCluster, Basic):
    """Hue Motion Basic cluster."""

    class AttributeDefs(Basic.AttributeDefs):
        """Attribute definitions."""

        trigger_indicator: Final = ZCLAttributeDef(
            id=0x0033,
            type=t.Bool,
            access="rw",
            manufacturer_code=PHILIPS_MFG_CODE,
        )


class PhilipsMotionOccupancyCluster(CustomCluster, OccupancySensing):
    """Hue Motion Occupancy cluster."""

    class AttributeDefs(OccupancySensing.AttributeDefs):
        """Attribute definitions."""

        sensitivity: Final = ZCLAttributeDef(
            id=0x0030,
            type=MotionSensitivity,
            zcl_type=DataTypeId.uint8,
            access="rw",
            manufacturer_code=PHILIPS_MFG_CODE,
        )


(
    QuirkBuilder("Philips", "SML001")
    .applies_to("Philips", "SML002")
    .replaces(PhilipsMotionBasicCluster, endpoint_id=2)
    .replaces(PhilipsMotionOccupancyCluster, endpoint_id=2)
    # Endpoint 1 has a client OnOff cluster which creates a dead duplicate motion
    # entity.
    .prevent_default_entity_creation(
        endpoint_id=1,
        cluster_id=OnOff.cluster_id,
        cluster_type=ClusterType.Client,
    )
    # ZHA matches SML002 with the native five-level HueV2MotionSensitivity
    # entity, but SML002 is a v1 sensor and uses only three sensitivity levels.
    .prevent_default_entity_creation(
        endpoint_id=2,
        cluster_id=PhilipsMotionOccupancyCluster.cluster_id,
        unique_id_suffix="motion_sensitivity",
    )
    .enum(
        attribute_name="sensitivity",
        enum_class=MotionSensitivity,
        cluster_id=PhilipsMotionOccupancyCluster.cluster_id,
        endpoint_id=2,
        translation_key="motion_sensitivity",
        fallback_name="Motion sensitivity",
    )
    .add_to_registry()
)
