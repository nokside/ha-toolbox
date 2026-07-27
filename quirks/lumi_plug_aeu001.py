"""Quirk v2 for Aqara Wall Outlet H2 EU lumi.plug.aeu001 / WP-P01D."""

import struct
from collections.abc import Iterator
from typing import Any, Final

from zha.application.helpers import safe_read, write_attributes_safe
from zha.application.platforms import (
    AttrConfig,
    BaseEntity,
    ClusterConfig,
)
from zha.application.platforms.number import BaseNumber
from zha.application.platforms.number.const import NumberMode
from zigpy import types as t
from zigpy.zcl import (
    AttributeReadEvent,
    AttributeReportedEvent,
    AttributeWrittenEvent,
    foundation,
)
from zigpy.zcl.clusters.general import AnalogInput, OnOff
from zigpy.zcl.clusters.homeautomation import ElectricalMeasurement
from zigpy.zcl.clusters.measurement import TemperatureMeasurement
from zigpy.zcl.clusters.smartenergy import Metering
from zigpy.zcl.foundation import BaseAttributeDefs, DataTypeId, ZCLAttributeDef

from zhaquirks import LocalDataCluster
from zhaquirks.builder import (
    EntityType,
    QuirkBuilder,
    SensorDeviceClass,
    SensorStateClass,
    UnitOfElectricCurrent,
    UnitOfElectricPotential,
    UnitOfEnergy,
    UnitOfPower,
    UnitOfTemperature,
)
from zhaquirks.builder.device import QuirkV2Device
from zhaquirks.clusters import CustomCluster

AQARA_MFG_CODE: Final = 0x115F


class PowerOnBehavior(t.enum8):
    """Power-on behavior after a power failure."""

    On = 0
    Previous = 1
    Off = 2
    Inverted = 3


class AqaraH2EUOutletManufacturerCluster(CustomCluster):
    """Aqara manufacturer cluster for the Wall Outlet H2 EU."""

    cluster_id = 0xFCC0
    ep_attribute = "aqara_h2eu_outlet_manufacturer"

    DEVICE_TEMPERATURE_TAG: Final = 0x03
    ENERGY_TAG: Final = 0x95
    VOLTAGE_TAG: Final = 0x96
    CURRENT_TAG: Final = 0x97

    class AttributeDefs(BaseAttributeDefs):
        """Attribute definitions."""

        aqara_lifeline: Final = ZCLAttributeDef(
            id=0x00F7,
            type=t.LVBytes,
            access="rp",
            manufacturer_code=AQARA_MFG_CODE,
        )
        button_lock: Final = ZCLAttributeDef(
            id=0x0200,
            type=t.uint8_t,
            access="rwp",
            manufacturer_code=AQARA_MFG_CODE,
        )
        charging_protection: Final = ZCLAttributeDef(
            id=0x0202,
            type=t.Bool,
            access="rwp",
            manufacturer_code=AQARA_MFG_CODE,
        )
        led_indicator: Final = ZCLAttributeDef(
            id=0x0203,
            type=t.Bool,
            access="rwp",
            manufacturer_code=AQARA_MFG_CODE,
        )
        charging_limit: Final = ZCLAttributeDef(
            id=0x0206,
            type=t.Single,
            access="rwp",
            manufacturer_code=AQARA_MFG_CODE,
        )
        overload_protection: Final = ZCLAttributeDef(
            id=0x020B,
            type=t.Single,
            access="rwp",
            manufacturer_code=AQARA_MFG_CODE,
        )
        power_on_behavior: Final = ZCLAttributeDef(
            id=0x0517,
            type=PowerOnBehavior,
            zcl_type=DataTypeId.uint8,
            access="rwp",
            manufacturer_code=AQARA_MFG_CODE,
        )

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        """Initialize the Aqara manufacturer cluster."""
        super().__init__(*args, **kwargs)
        self.on_event(
            AttributeReadEvent.event_type,
            self._handle_attribute_event,
        )
        self.on_event(
            AttributeReportedEvent.event_type,
            self._handle_attribute_event,
        )

    def _handle_attribute_event(
        self,
        event: AttributeReadEvent | AttributeReportedEvent,
    ) -> None:
        """Handle the Aqara lifeline attribute."""
        if event.attribute_id == self.AttributeDefs.aqara_lifeline.id:
            values = self._parse_lifeline_report(event.value)
            lifeline_cluster = self.endpoint.aqara_h2eu_outlet_lifeline

            if self.DEVICE_TEMPERATURE_TAG in values:
                lifeline_cluster.update_attribute(
                    AqaraH2EUOutletLifelineCluster.AttributeDefs.device_temperature.id,
                    values[self.DEVICE_TEMPERATURE_TAG],
                )

            if self.ENERGY_TAG in values:
                lifeline_cluster.update_attribute(
                    AqaraH2EUOutletLifelineCluster.AttributeDefs.energy.id,
                    values[self.ENERGY_TAG],
                )

            if self.VOLTAGE_TAG in values:
                lifeline_cluster.update_attribute(
                    AqaraH2EUOutletLifelineCluster.AttributeDefs.voltage.id,
                    values[self.VOLTAGE_TAG] / 10,
                )

            if self.CURRENT_TAG in values:
                lifeline_cluster.update_attribute(
                    AqaraH2EUOutletLifelineCluster.AttributeDefs.current.id,
                    values[self.CURRENT_TAG] / 1000,
                )

    async def apply_custom_configuration(
        self,
        *args: Any,
        **kwargs: Any,
    ) -> None:
        """Read the Aqara lifeline during device configuration."""
        try:
            await self.read_attributes(
                [self.AttributeDefs.aqara_lifeline.name],
                allow_cache=False,
            )
        except Exception as exc:
            self.debug("Failed to read Aqara lifeline: %r", exc)

    def _parse_lifeline_report(self, data: bytes) -> dict[int, Any]:
        """Parse an Aqara lifeline report."""
        values: dict[int, Any] = {}

        while len(data) >= 2:
            tag = data[0]

            try:
                typed_value, data = foundation.TypeValue.deserialize(data[1:])
            except ValueError:
                self.debug(
                    "Failed to deserialize Aqara outlet lifeline tag 0x%02X from %r",
                    tag,
                    data,
                )
                return values

            values[tag] = typed_value.value

        return values


class AqaraH2EUOutletLifelineCluster(LocalDataCluster):
    """Values decoded from the Aqara lifeline."""

    cluster_id = 0xFC02
    ep_attribute = "aqara_h2eu_outlet_lifeline"

    class AttributeDefs(BaseAttributeDefs):
        """Attribute definitions."""

        current: Final = ZCLAttributeDef(
            id=0x0001,
            type=t.Single,
            manufacturer_code=None,
        )
        voltage: Final = ZCLAttributeDef(
            id=0x0002,
            type=t.Single,
            manufacturer_code=None,
        )
        energy: Final = ZCLAttributeDef(
            id=0x0003,
            type=t.Single,
            manufacturer_code=None,
        )
        device_temperature: Final = ZCLAttributeDef(
            id=0x0004,
            type=t.int8s,
            manufacturer_code=None,
        )

    _VALID_ATTRIBUTES: set[int] = {
        AttributeDefs.current.id,
        AttributeDefs.voltage.id,
        AttributeDefs.energy.id,
        AttributeDefs.device_temperature.id,
    }


class AqaraH2EUOutletChargingLimitNumber(BaseNumber):
    """Charging limit number supporting floating-point values."""

    _attribute_name = (
        AqaraH2EUOutletManufacturerCluster.AttributeDefs.charging_limit.name
    )
    _attr_native_min_value: float = 0.1
    _attr_native_max_value: float = 2.0
    _attr_native_step: float = 0.1
    _attr_native_unit_of_measurement = UnitOfPower.WATT
    _attr_mode = NumberMode.SLIDER

    _server_cluster_config = {
        AqaraH2EUOutletManufacturerCluster.cluster_id: ClusterConfig(
            attributes={
                AqaraH2EUOutletManufacturerCluster.AttributeDefs.charging_limit: AttrConfig(
                    read_on_startup=False,
                ),
            },
        ),
    }

    def on_add(self) -> None:
        """Run when entity is added."""
        super().on_add()

        for event_type in (
            AttributeReadEvent,
            AttributeReportedEvent,
            AttributeWrittenEvent,
        ):
            self._on_remove_callbacks.append(
                self._cluster.on_event(
                    event_type.event_type,
                    self.handle_attribute_updated,
                )
            )

    def handle_attribute_updated(
        self,
        event: AttributeReadEvent | AttributeReportedEvent | AttributeWrittenEvent,
    ) -> None:
        """Handle charging limit updates."""
        if event.attribute_name == self._attribute_name:
            self.maybe_emit_state_changed_event()

    @property
    def native_value(self) -> float | None:
        value = self._cluster.get(self._attribute_name)

        if value is None:
            return None

        return round(value, 1)

    async def async_set_native_value(self, value: float) -> None:
        """Write the charging limit with correctly rounded float32 serialization."""
        # Zigpy truncates fractional bits when converting a Python float64 to
        # t.Single, so 0.6 would be written as 0.5999999642372131. Convert to
        # float32 first to use the nearest representation, 0.6000000238418579.
        value = struct.unpack("<f", struct.pack("<f", value))[0]

        await write_attributes_safe(
            self._cluster,
            {self._attribute_name: value},
        )
        self.maybe_emit_state_changed_event()

    async def async_update(self) -> None:
        """Read the charging limit from the device."""
        await safe_read(
            self._cluster,
            [self._attribute_name],
            allow_cache=False,
            only_cache=False,
        )
        self.maybe_emit_state_changed_event()


class AqaraH2EUOutletDevice(QuirkV2Device):
    """Aqara Wall Outlet H2 EU device with custom entities."""

    def discover_entities(self) -> Iterator[BaseEntity]:
        """Yield QuirkBuilder entities and the charging limit number."""
        yield from super().discover_entities()

        endpoint = self.endpoints[1]
        cluster = endpoint.zigpy_endpoint.in_clusters[
            AqaraH2EUOutletManufacturerCluster.cluster_id
        ]

        yield AqaraH2EUOutletChargingLimitNumber(
            endpoint=endpoint,
            device=self,
            cluster=cluster,
            from_quirk=True,
            entity_type=EntityType.CONFIG,
            translation_key="charging_limit",
            fallback_name="Charging limit",
        )


(
    QuirkBuilder("Aqara", "lumi.plug.aeu001")
    .friendly_name(manufacturer="Aqara", model="Wall Outlet H2 EU")
    .zha_device_class(AqaraH2EUOutletDevice)
    # Remove the duplicate relay cluster on endpoint 2.
    .removes(OnOff.cluster_id, endpoint_id=2)
    # Remove the unsupported standard temperature cluster.
    .removes(TemperatureMeasurement.cluster_id)
    # Remove the nonfunctional metering cluster, which always reports zero.
    .removes(Metering.cluster_id)
    # Remove the incomplete Electrical Measurement cluster.
    .removes(ElectricalMeasurement.cluster_id)
    .replaces(AqaraH2EUOutletManufacturerCluster)
    .adds(AqaraH2EUOutletLifelineCluster)
    .switch(
        attribute_name="button_lock",
        cluster_id=AqaraH2EUOutletManufacturerCluster.cluster_id,
        off_value=1,
        on_value=0,
        translation_key="button_lock",
        fallback_name="Button lock",
    )
    .enum(
        attribute_name="power_on_behavior",
        enum_class=PowerOnBehavior,
        cluster_id=AqaraH2EUOutletManufacturerCluster.cluster_id,
        translation_key="power_on_behavior",
        fallback_name="Power on behavior",
    )
    .number(
        attribute_name="overload_protection",
        cluster_id=AqaraH2EUOutletManufacturerCluster.cluster_id,
        min_value=100,
        max_value=3840,
        step=1,
        unit=UnitOfPower.WATT,
        translation_key="overload_protection",
        fallback_name="Overload protection",
    )
    .switch(
        attribute_name="led_indicator",
        cluster_id=AqaraH2EUOutletManufacturerCluster.cluster_id,
        translation_key="led_indicator",
        fallback_name="LED indicator",
    )
    .switch(
        attribute_name="charging_protection",
        cluster_id=AqaraH2EUOutletManufacturerCluster.cluster_id,
        translation_key="charging_protection",
        fallback_name="Charging protection",
    )
    .sensor(
        attribute_name="present_value",
        cluster_id=AnalogInput.cluster_id,
        endpoint_id=21,
        device_class=SensorDeviceClass.POWER,
        state_class=SensorStateClass.MEASUREMENT,
        unit=UnitOfPower.WATT,
        suggested_display_precision=1,
        translation_key="power",
        fallback_name="Power",
    )
    .sensor(
        attribute_name="current",
        cluster_id=AqaraH2EUOutletLifelineCluster.cluster_id,
        device_class=SensorDeviceClass.CURRENT,
        state_class=SensorStateClass.MEASUREMENT,
        unit=UnitOfElectricCurrent.AMPERE,
        suggested_display_precision=3,
        translation_key="current",
        fallback_name="Current",
    )
    .sensor(
        attribute_name="voltage",
        cluster_id=AqaraH2EUOutletLifelineCluster.cluster_id,
        device_class=SensorDeviceClass.VOLTAGE,
        state_class=SensorStateClass.MEASUREMENT,
        unit=UnitOfElectricPotential.VOLT,
        suggested_display_precision=1,
        translation_key="voltage",
        fallback_name="Voltage",
    )
    .sensor(
        attribute_name="energy",
        cluster_id=AqaraH2EUOutletLifelineCluster.cluster_id,
        device_class=SensorDeviceClass.ENERGY,
        state_class=SensorStateClass.TOTAL_INCREASING,
        unit=UnitOfEnergy.KILO_WATT_HOUR,
        suggested_display_precision=3,
        translation_key="energy",
        fallback_name="Energy",
    )
    .sensor(
        attribute_name="device_temperature",
        cluster_id=AqaraH2EUOutletLifelineCluster.cluster_id,
        entity_type=EntityType.DIAGNOSTIC,
        device_class=SensorDeviceClass.TEMPERATURE,
        state_class=SensorStateClass.MEASUREMENT,
        unit=UnitOfTemperature.CELSIUS,
        translation_key="device_temperature",
        fallback_name="Device temperature",
    )
    .add_to_registry()
)
