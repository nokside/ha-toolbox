"""Quirk for Aqara Door and Window Sensor E1 lumi.magnet.acn001 / MCCGQ14LM."""

from typing import Any, Final

from zigpy import types as t
from zigpy.zcl import AttributeReportedEvent, foundation
from zigpy.zcl.clusters.general import PowerConfiguration
from zigpy.zcl.clusters.security import IasZone
from zigpy.zcl.foundation import BaseAttributeDefs, ZCLAttributeDef

from zhaquirks import CustomCluster
from zhaquirks.builder import QuirkBuilder
from zhaquirks.const import BatterySize
from zhaquirks.xiaomi import XiaomiPowerConfiguration

AQARA_MFG_CODE: Final = 0x115F


class E1MagnetManufacturerCluster(CustomCluster):
    """Aqara Door and Window Sensor E1 manufacturer cluster."""

    cluster_id = 0xFCC0
    ep_attribute = "e1_manufacturer"

    BATTERY_VOLTAGE_TAG: Final = 0x01
    CONTACT_STATE_TAG: Final = 0x64

    class AttributeDefs(BaseAttributeDefs):
        """E1 manufacturer attributes."""

        aqara_heartbeat: Final = ZCLAttributeDef(
            id=0x00F7,
            type=t.LVBytes,
            access="rp",
            manufacturer_code=AQARA_MFG_CODE,
        )

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        """Init."""
        super().__init__(*args, **kwargs)
        self.on_event(
            AttributeReportedEvent.event_type,
            self._handle_attribute_event,
        )

    def _handle_attribute_event(
        self,
        event: AttributeReportedEvent,
    ) -> None:
        """Handle manufacturer attribute updates."""
        if event.attribute_id == self.AttributeDefs.aqara_heartbeat.id:
            values = self._parse_heartbeat_report(event.value)

            if self.BATTERY_VOLTAGE_TAG in values:
                self.endpoint.power.battery_reported(
                    values[self.BATTERY_VOLTAGE_TAG]
                )

            if self.CONTACT_STATE_TAG in values:
                self.endpoint.ias_zone.update_attribute(
                    IasZone.AttributeDefs.zone_status.id,
                    values[self.CONTACT_STATE_TAG],
                )

    def _parse_heartbeat_report(self, data: bytes) -> dict[int, Any]:
        """Parse Aqara E1 heartbeat report."""
        values: dict[int, Any] = {}

        while len(data) >= 2:
            tag = data[0]

            try:
                typed_value, data = foundation.TypeValue.deserialize(data[1:])
            except (KeyError, ValueError):
                self.debug(
                    "Failed to deserialize Aqara E1 heartbeat tag 0x%02X from %r",
                    tag,
                    data,
                )
                return values

            values[tag] = typed_value.value

        return values


class E1MagnetPowerConfiguration(XiaomiPowerConfiguration):
    """Power configuration for the Aqara Door and Window Sensor E1."""

    def __init__(self, *args, **kwargs) -> None:
        """Init."""
        super().__init__(*args, **kwargs)

        self._CONSTANT_ATTRIBUTES = {
            PowerConfiguration.AttributeDefs.battery_size.id: BatterySize.CR1632,
        }

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
    QuirkBuilder("LUMI", "lumi.magnet.acn001")
    .friendly_name(manufacturer="Aqara", model="Door and Window Sensor E1")
    .replaces(E1MagnetManufacturerCluster)
    .replaces(E1MagnetPowerConfiguration)
    .skip_configuration()
    .add_to_registry()
)