"""Quirk for IKEA of Sweden TRADFRI open/close remote."""

from typing import Any, Final

from zigpy.zcl import ClusterType
from zigpy.zcl.clusters.general import Basic, LevelControl, OnOff, PowerConfiguration
from zigpy.zcl.clusters.lightlink import LightLink

from zhaquirks import CustomCluster
from zhaquirks.builder import QuirkBuilder
from zhaquirks.const import BatterySize
from zhaquirks.ikea import IKEA


class OpenCloseRemotePowerConfigurationCluster(CustomCluster, PowerConfiguration):
    """Power cluster with guarded IKEA open/close remote battery handling."""

    BATTERY_PERCENTAGE_REMAINING_ATTR_ID: Final = (
        PowerConfiguration.AttributeDefs.battery_percentage_remaining.id
    )
    BATTERY_QUANTITY_ATTR_ID: Final = (
        PowerConfiguration.AttributeDefs.battery_quantity.id
    )
    BATTERY_SIZE_ATTR_ID: Final = PowerConfiguration.AttributeDefs.battery_size.id
    SW_BUILD_ATTR_ID: Final = Basic.AttributeDefs.sw_build_id.id

    _VALID_ATTRIBUTES: set[int] = {
        BATTERY_PERCENTAGE_REMAINING_ATTR_ID,
    }

    _CONSTANT_ATTRIBUTES: dict[int, Any] = {
        BATTERY_QUANTITY_ATTR_ID: 1,
        BATTERY_SIZE_ATTR_ID: BatterySize.CR2032,
    }

    async def apply_custom_configuration(self, *args: Any, **kwargs: Any) -> None:
        """Read firmware for guarded battery handling."""
        try:
            await self.endpoint.basic.read_attributes([self.SW_BUILD_ATTR_ID])
        except Exception as exc:
            self.debug("Failed to read sw_build_id: %r", exc)

    def _needs_doubling(self) -> bool:
        """Check if firmware reports battery as 0-100."""
        sw_build_id = self.endpoint.basic.get(self.SW_BUILD_ATTR_ID)
        if sw_build_id is None:
            return False

        try:
            version = tuple(int(part) for part in sw_build_id.split("."))
        except (TypeError, ValueError):
            return False

        return version < (2, 4, 0)

    def _update_attribute(self, attrid: int, value: int | None) -> None:
        """Normalize IKEA open/close remote battery percentage."""
        if attrid == self.BATTERY_PERCENTAGE_REMAINING_ATTR_ID and value is not None:
            needs_doubling = self._needs_doubling()

            if value > (100 if needs_doubling else 200):
                self.debug("Ignoring invalid battery percentage value: %r", value)
                return

            if needs_doubling:
                value *= 2

        super()._update_attribute(attrid, value)


(
    QuirkBuilder(IKEA, "TRADFRI open/close remote")
    .applies_to("\x02KE", "TRADFRI open/close remote")
    .removes(OnOff.cluster_id, endpoint_id=1, cluster_type=ClusterType.Client)
    .removes(LevelControl.cluster_id, endpoint_id=1, cluster_type=ClusterType.Client)
    .removes(LightLink.cluster_id, endpoint_id=1, cluster_type=ClusterType.Server)
    .removes(LightLink.cluster_id, endpoint_id=1, cluster_type=ClusterType.Client)
    .replaces(OpenCloseRemotePowerConfigurationCluster, endpoint_id=1)
    .add_to_registry()
)
