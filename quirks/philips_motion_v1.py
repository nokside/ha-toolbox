"""Quirk for Philips Hue motion sensors SML001/SML002.

Note:
    Older Philips Hue motion sensors may require unsecured rejoins to work
    reliably with ZHA on EZSP-based coordinators. If pairing or rejoining is
    unstable, add the following to Home Assistant configuration.yaml:

    zha:
      zigpy_config:
        ezsp_policies:
          TRUST_CENTER_POLICY: 0x0002  # ALLOW_UNSECURED_REJOINS
"""

from typing import Final

from zigpy.quirks import CustomCluster
from zigpy.quirks.v2 import EntityType, QuirkBuilder, ReportingConfig
from zigpy.quirks.v2.homeassistant import UnitOfTime
from zigpy.quirks.v2.homeassistant.binary_sensor import BinarySensorDeviceClass
from zigpy.quirks.v2.homeassistant.number import NumberDeviceClass, NumberMode
import zigpy.types as t
from zigpy.zcl import ClusterType
from zigpy.zcl.clusters.general import Basic, OnOff
from zigpy.zcl.clusters.measurement import Occupancy
from zigpy.zcl.foundation import BaseAttributeDefs, DataTypeId, ZCLAttributeDef

from zhaquirks.philips import PHILIPS


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

        led_indication: Final = ZCLAttributeDef(
            id=0x0033,
            type=t.Bool,
            access="rw",
            manufacturer_code=PHILIPS_MFG_CODE,
        )


class PhilipsMotionOccupancyCluster(CustomCluster):
    """Hue Motion Occupancy cluster."""

    cluster_id = 0x0406
    MIN_OCCUPANCY_TIMEOUT: Final = 10

    class AttributeDefs(BaseAttributeDefs):
        """Attribute definitions."""

        occupancy: Final = ZCLAttributeDef(
            id=0x0000,
            type=Occupancy,
            access="rp",
            mandatory=True,
        )

        occupancy_timeout: Final = ZCLAttributeDef(
            id=0x0010,
            type=t.uint16_t,
            access="rw",
        )

        motion_sensitivity: Final = ZCLAttributeDef(
            id=0x0030,
            type=MotionSensitivity,
            zcl_type=DataTypeId.uint8,
            access="rw",
            manufacturer_code=PHILIPS_MFG_CODE,
        )

    def _update_attribute(self, attrid, value):
        """Clamp reported occupancy timeout to the real device minimum."""
        if (
            attrid == self.AttributeDefs.occupancy_timeout.id
            and value is not None
            and value < self.MIN_OCCUPANCY_TIMEOUT
        ):
            value = self.MIN_OCCUPANCY_TIMEOUT

        super()._update_attribute(attrid, value)


(
    QuirkBuilder(PHILIPS, "SML001")
    .applies_to(PHILIPS, "SML002")
    .replaces(PhilipsMotionBasicCluster, endpoint_id=2)
    .replaces(PhilipsMotionOccupancyCluster, endpoint_id=2)

    # Endpoint 1 has a client OnOff cluster which creates a dead duplicate motion entity.
    .prevent_default_entity_creation(
        endpoint_id=1,
        cluster_id=OnOff.cluster_id,
        cluster_type=ClusterType.Client,
    )

    .binary_sensor(
        attribute_name=PhilipsMotionOccupancyCluster.AttributeDefs.occupancy.name,
        cluster_id=PhilipsMotionOccupancyCluster.cluster_id,
        endpoint_id=2,
        device_class=BinarySensorDeviceClass.OCCUPANCY,
        entity_type=EntityType.STANDARD,
        reporting_config=ReportingConfig(
            min_interval=0,
            max_interval=900,
            reportable_change=1,
        ),
        translation_key="occupancy",
        fallback_name="Occupancy",
    )

    .switch(
        attribute_name=PhilipsMotionBasicCluster.AttributeDefs.led_indication.name,
        cluster_id=PhilipsMotionBasicCluster.cluster_id,
        endpoint_id=2,
        entity_type=EntityType.CONFIG,
        translation_key="led_indication",
        fallback_name="LED indication",
    )

    .enum(
        attribute_name=PhilipsMotionOccupancyCluster.AttributeDefs.motion_sensitivity.name,
        enum_class=MotionSensitivity,
        cluster_id=PhilipsMotionOccupancyCluster.cluster_id,
        endpoint_id=2,
        entity_type=EntityType.CONFIG,
        translation_key="motion_sensitivity",
        fallback_name="Motion sensitivity",
    )

    .number(
        attribute_name=PhilipsMotionOccupancyCluster.AttributeDefs.occupancy_timeout.name,
        cluster_id=PhilipsMotionOccupancyCluster.cluster_id,
        endpoint_id=2,
        device_class=NumberDeviceClass.DURATION,
        entity_type=EntityType.CONFIG,
        min_value=10,
        max_value=65535,
        step=1,
        unit=UnitOfTime.SECONDS,
        mode=NumberMode.BOX,
        translation_key="occupancy_timeout",
        fallback_name="Occupancy timeout",
    )
    .add_to_registry()
)
