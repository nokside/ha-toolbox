"""Quirk for IKEA of Sweden TRADFRI Fyrtur blinds."""

from zigpy.quirks.v2 import QuirkBuilder
from zigpy.zcl.clusters.general import Basic, PowerConfiguration

from zhaquirks import CustomCluster
from zhaquirks.ikea import IKEA


class IkeaBlindsPowerConfigCluster(CustomCluster, PowerConfiguration):
    """PowerConfiguration cluster for IKEA blinds with guarded battery handling."""

    BATTERY_PERCENT_ATTR = PowerConfiguration.AttributeDefs.battery_percentage_remaining.id
    SW_BUILD_ID_ATTR = Basic.AttributeDefs.sw_build_id.id

    ZCL_BATTERY_PERCENT_MAX = 200
    PLAIN_BATTERY_PERCENT_MAX = 100

    FW_TREDANSEN_FIXED = (24, 4, 13)
    FW_IKEA_FIXED = (2, 4, 0)

    async def bind(self):
        """Bind cluster and read firmware version for later battery handling."""
        result = await super().bind()
    
        try:
            await self.endpoint.basic.read_attributes(
                [self.SW_BUILD_ID_ATTR],
                allow_cache=False,
            )
        except Exception as exc:
            self.debug("Failed to read sw_build_id: %r", exc)
    
        return result

    def _parse_version(self, version: str | None) -> tuple[int, int, int] | None:
        """Parse IKEA firmware version like '2.3.086' or '24.4.13'."""
        if not version:
            return None

        parts = version.split(".")
        if len(parts) < 2:
            self.debug("Unexpected IKEA sw_build_id format: %s", version)
            return None

        try:
            numbers = [int(part) for part in parts[:3]]
        except ValueError:
            self.debug("Unexpected IKEA sw_build_id format: %s", version)
            return None

        numbers += [0] * (3 - len(numbers))
        return tuple(numbers)

    def _reports_plain_percentage(self) -> bool:
        """Return True if firmware reports battery as 0-100 instead of ZCL 0-200."""
        version = self._parse_version(self.endpoint.basic.get(self.SW_BUILD_ID_ATTR))

        if version is None:
            return False

        if getattr(self.endpoint.device, "model", None) == "TREDANSEN block-out cellul blind":
            return version < self.FW_TREDANSEN_FIXED

        return version < self.FW_IKEA_FIXED

    def _normalize_battery_percentage(self, value: int | None) -> int | None:
        """Normalize reported battery value to ZCL 0-200 format."""
        if value is None or value > self.ZCL_BATTERY_PERCENT_MAX:
            return None

        if self._reports_plain_percentage() and value <= self.PLAIN_BATTERY_PERCENT_MAX:
            return value * 2

        return value

    def _update_attribute(self, attrid: int, value: int | None) -> None:
        """Update battery percentage safely."""
        if attrid != self.BATTERY_PERCENT_ATTR:
            super()._update_attribute(attrid, value)
            return

        normalized_value = self._normalize_battery_percentage(value)
        if normalized_value is None:
            return

        super()._update_attribute(attrid, normalized_value)


(
    QuirkBuilder(IKEA, "FYRTUR block-out roller blind")
    .applies_to(IKEA, "KADRILJ roller blind")
    .applies_to(IKEA, "TREDANSEN block-out cellul blind")
    .applies_to(IKEA, "PRAKTLYSING cellular blind")
    .replaces(IkeaBlindsPowerConfigCluster, endpoint_id=1)
    .add_to_registry()
)
