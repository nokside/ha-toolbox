"""Quirk for Aqara Light Sensor T1 (lumi.sen_ill.agl01)."""

import math
from typing import Any, Final

from zigpy import types as t
from zigpy.zcl import ClusterType
from zigpy.zcl.clusters.general import Ota, PowerConfiguration
from zigpy.zcl.foundation import ZCLAttributeDef
from zigpy.zdo.types import NodeDescriptor

from zhaquirks.builder import QuirkBuilder, UnitOfTime
from zhaquirks.const import BatterySize
from zhaquirks.xiaomi import (
    ILLUMINANCE_MEASUREMENT,
    XiaomiAqaraE1Cluster,
    XiaomiPowerConfiguration,
)

AQARA_MFG_CODE = 0x115F


class LightSensorT1Cluster(XiaomiAqaraE1Cluster):
    """Aqara Light Sensor T1 manufacturer cluster."""

    class AttributeDefs(XiaomiAqaraE1Cluster.AttributeDefs):
        """Manufacturer-specific attributes."""

        light_sampling_period: Final = ZCLAttributeDef(
            id=0x0000,
            type=t.uint16_t,
            access="rw",
            manufacturer_code=AQARA_MFG_CODE,
        )

    def _parse_aqara_attributes(self, value: Any) -> dict[str, Any]:
        """Parse illuminance from the Aqara heartbeat."""
        attributes = super()._parse_aqara_attributes(value)

        if "0xff01-100" in attributes:
            lux = attributes.pop("0xff01-100")
            attributes[ILLUMINANCE_MEASUREMENT] = (
                round(10000 * math.log10(lux) + 1) if lux > 0 else 0
            )

        return attributes

    async def apply_custom_configuration(self, *args, **kwargs):
        """Read light sampling period and initialize OTA."""
        await self.read_attributes([self.AttributeDefs.light_sampling_period.id])

        ota = self.endpoint.out_clusters[Ota.cluster_id]
        await ota.read_attributes([Ota.AttributeDefs.current_file_version.name])

        try:
            await ota.image_notify(
                payload_type=Ota.ImageNotifyCommand.PayloadType.QueryJitter,
                query_jitter=100,
            )
        except Exception:  # noqa: BLE001
            self.debug("OTA image_notify failed during initialization", exc_info=True)


class LightSensorT1PowerConfiguration(XiaomiPowerConfiguration):
    """Aqara Light Sensor T1 power configuration cluster."""

    def __init__(self, *args, **kwargs):
        """Init."""
        super().__init__(*args, **kwargs)
        self._CONSTANT_ATTRIBUTES[PowerConfiguration.AttributeDefs.battery_size.id] = (
            BatterySize.CR2450
        )

    def _update_battery_percentage(self, voltage_mv: int) -> None:
        """Update battery percentage from voltage."""
        # Aqara voltage curve.
        curve_value = 0.00045 * voltage_mv**2 - 2.277 * voltage_mv + 2880

        # Remap [33, 100] curve range to [20, 100]
        percentage = 20 + (curve_value - 33) * (100 - 20) / (100 - 33)

        # Clamp between 0 and 100
        percentage = max(0, min(100, percentage))

        self._update_attribute(
            self.BATTERY_PERCENTAGE_REMAINING,
            round(percentage * 2),
        )


(
    QuirkBuilder("LUMI", "lumi.sen_ill.agl01")
    .node_descriptor(
        NodeDescriptor(0x02, 0x40, 0x80, 0x126E, 0x7F, 0x0064, 0x2C00, 0x0064, 0x00)
    )
    .friendly_name(manufacturer="Aqara", model="Light Sensor T1")
    .replaces(LightSensorT1PowerConfiguration)
    .replaces(LightSensorT1Cluster)
    .adds(Ota.cluster_id, cluster_type=ClusterType.Client)
    .number(
        attribute_name="light_sampling_period",
        cluster_id=LightSensorT1Cluster.cluster_id,
        min_value=1,
        max_value=59,
        step=1,
        unit=UnitOfTime.SECONDS,
        translation_key="light_sampling_period",
        fallback_name="Light sampling period",
    )
    .skip_configuration()
    .add_to_registry()
)
