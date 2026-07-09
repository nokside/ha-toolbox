"""Quirk v2 for IKEA blinds with guarded battery percentage handling."""

from typing import Any, Final

from zhaquirks import CustomCluster
from zhaquirks.builder import QuirkBuilder
from zhaquirks.ikea import IKEA
from zigpy.zcl.clusters.general import Basic, PowerConfiguration


class IkeaBlindsPowerConfigurationCluster(CustomCluster, PowerConfiguration):
    """Power cluster with guarded IKEA blind battery percentage handling."""

    BATTERY_PERCENTAGE_REMAINING_ATTR_ID: Final = (
        PowerConfiguration.AttributeDefs.battery_percentage_remaining.id
    )
    SW_BUILD_ID_ATTR_ID: Final = Basic.AttributeDefs.sw_build_id.id

    ZCL_BATTERY_PERCENTAGE_MAX: Final = 200
    PLAIN_BATTERY_PERCENTAGE_MAX: Final = 100

    FIXED_FIRMWARE_VERSION: Final = (2, 4, 0)
    TREDANSEN_FIXED_FIRMWARE_VERSION: Final = (24, 4, 13)
    TREDANSEN_MODEL: Final = "TREDANSEN block-out cellul blind"

    async def bind(self) -> Any:
        """Bind cluster and read firmware for guarded battery handling."""
        result = await super().bind()

        try:
            await self.endpoint.basic.read_attributes(
                [self.SW_BUILD_ID_ATTR_ID],
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
            self.debug("Unexpected IKEA sw_build_id format: %r", version)
            return None

        try:
            numbers = [int(part) for part in parts[:3]]
        except ValueError:
            self.debug("Unexpected IKEA sw_build_id format: %r", version)
            return None

        numbers += [0] * (3 - len(numbers))
        return numbers[0], numbers[1], numbers[2]

    def _fixed_firmware_version(self) -> tuple[int, int, int]:
        """Return the firmware version where ZCL battery reporting is fixed."""
        if getattr(self.endpoint.device, "model", None) == self.TREDANSEN_MODEL:
            return self.TREDANSEN_FIXED_FIRMWARE_VERSION

        return self.FIXED_FIRMWARE_VERSION

    def _reports_plain_percentage(self) -> bool:
        """Return if firmware reports battery as 0-100 instead of ZCL 0-200."""
        version = self._parse_version(self.endpoint.basic.get(self.SW_BUILD_ID_ATTR_ID))

        if version is None:
            return False

        return version < self._fixed_firmware_version()

    def _normalize_battery_percentage(self, value: int | None) -> int | None:
        """Normalize reported battery value to ZCL 0-200 format."""
        if value is None:
            return None

        if value > self.ZCL_BATTERY_PERCENTAGE_MAX:
            self.debug("Ignoring invalid battery percentage value: %r", value)
            return None

        if (
            self._reports_plain_percentage()
            and value <= self.PLAIN_BATTERY_PERCENTAGE_MAX
        ):
            return value * 2

        return value

    def _update_attribute(self, attrid: int, value: int | None) -> None:
        """Update battery percentage safely."""
        if attrid != self.BATTERY_PERCENTAGE_REMAINING_ATTR_ID:
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
    .replaces(IkeaBlindsPowerConfigurationCluster, endpoint_id=1)
    .add_to_registry()
)
