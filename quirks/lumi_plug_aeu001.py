"""Quirk for Aqara Wall Outlet H2 EU lumi.plug.aeu001 / WP-P01D."""

import struct
from typing import Any, Final

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
from zigpy.zcl.foundation import BaseAttributeDefs, DataTypeId, Status, ZCLAttributeDef

from zhaquirks import CustomCluster, LocalDataCluster
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

AQARA_MFG_CODE: Final = 0x115F


class PowerOnBehavior(t.enum8):
    """Power-on behavior."""

    On = 0
    Previous = 1
    Off = 2
    Inverted = 3


class H2EUOutletManufacturerCluster(CustomCluster):
    """Aqara manufacturer cluster for the Wall Outlet H2 EU."""

    cluster_id = 0xFCC0
    ep_attribute = "h2eu_manufacturer"

    DEVICE_TEMPERATURE_TAG: Final = 0x03
    ENERGY_CONSUMPTION_TAG: Final = 0x95
    AC_VOLTAGE_TAG: Final = 0x96
    AC_CURRENT_TAG: Final = 0x97
    RELAY_STATE_TAG: Final = 0x64

    class AttributeDefs(BaseAttributeDefs):
        """Attribute definitions."""

        aqara_heartbeat: Final = ZCLAttributeDef(
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
        charging_protection_limit: Final = ZCLAttributeDef(
            id=0x0206,
            type=t.Single,
            access="rwp",
            manufacturer_code=AQARA_MFG_CODE,
        )
        led_indicator: Final = ZCLAttributeDef(
            id=0x0203,
            type=t.Bool,
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
        """Init."""
        super().__init__(*args, **kwargs)
        self.on_event(AttributeReportedEvent.event_type, self._handle_heartbeat_report)

        for event_type in (AttributeReadEvent, AttributeReportedEvent, AttributeWrittenEvent):
            self.on_event(event_type.event_type, self._handle_attribute_event)

    def _handle_attribute_event(
        self,
        event: AttributeReadEvent | AttributeReportedEvent | AttributeWrittenEvent,
    ) -> None:
        """Synchronize Charging protection limit with the local cluster."""
        if isinstance(event, AttributeWrittenEvent) and event.status != Status.SUCCESS:
            return

        if event.attribute_id == self.AttributeDefs.charging_protection_limit.id and event.value is not None:
            self.endpoint.charging_protection_limit.update_charging_protection_limit(event.value)

    def _handle_heartbeat_report(self, event: AttributeReportedEvent) -> None:
        """Update H2 EU measurements from heartbeat reports."""
        if event.attribute_id != self.AttributeDefs.aqara_heartbeat.id:
            return

        values = self._parse_heartbeat_report(event.value)

        if self.DEVICE_TEMPERATURE_TAG in values:
            self.endpoint.heartbeat.update_attribute(
                H2EUOutletHeartbeatCluster.AttributeDefs.device_temperature.id,
                values[self.DEVICE_TEMPERATURE_TAG],
            )

        if self.ENERGY_CONSUMPTION_TAG in values:
            self.endpoint.heartbeat.update_attribute(
                H2EUOutletHeartbeatCluster.AttributeDefs.energy.id,
                values[self.ENERGY_CONSUMPTION_TAG],
            )

        if self.AC_VOLTAGE_TAG in values:
            self.endpoint.heartbeat.update_attribute(
                H2EUOutletHeartbeatCluster.AttributeDefs.voltage.id,
                values[self.AC_VOLTAGE_TAG] / 10,
            )

        if self.AC_CURRENT_TAG in values:
            self.endpoint.heartbeat.update_attribute(
                H2EUOutletHeartbeatCluster.AttributeDefs.current.id,
                values[self.AC_CURRENT_TAG] / 1000,
            )
        if self.RELAY_STATE_TAG in values:
            self.endpoint.on_off.update_attribute(
                OnOff.AttributeDefs.on_off.id,
                values[self.RELAY_STATE_TAG],
            )

    def _parse_heartbeat_report(self, data: bytes) -> dict[int, Any]:
        """Parse typed values from an Aqara heartbeat."""
        values: dict[int, Any] = {}

        while len(data) >= 2:
            tag = data[0]

            try:
                typed_value, data = foundation.TypeValue.deserialize(data[1:])
            except (KeyError, ValueError):
                self.debug("Failed to deserialize H2 EU heartbeat tag 0x%02X from %r", tag, data)
                return values

            values[tag] = typed_value.value

        return values

    async def apply_custom_configuration(self, *args: Any, **kwargs: Any) -> None:
        """Read Aqara settings and EP21 power."""
        await self.read_attributes(
            [
                self.AttributeDefs.button_lock.id,
                self.AttributeDefs.charging_protection.id,
                self.AttributeDefs.led_indicator.id,
                self.AttributeDefs.charging_protection_limit.id,
                self.AttributeDefs.overload_protection.id,
                self.AttributeDefs.power_on_behavior.id,
            ]
        )
        await self.endpoint.device.endpoints[21].analog_input.read_attributes(
            [AnalogInput.AttributeDefs.present_value.id]
        )


class H2EUOutletChargingLimitCluster(LocalDataCluster):
    """Charging Limit cluster for the Wall Outlet H2 EU."""

    cluster_id = 0xFC03
    ep_attribute = "charging_protection_limit"

    class AttributeDefs(BaseAttributeDefs):
        """Local value: 10 = 0.1 W, 200 = 2.0 W."""

        charging_protection_limit: Final = ZCLAttributeDef(
            id=0x0000,
            type=t.uint16_t,
            manufacturer_code=None,
        )

    _VALID_ATTRIBUTES: set[int] = {AttributeDefs.charging_protection_limit.id}

    def update_charging_protection_limit(self, value: float) -> None:
        """Update the local Charging protection limit from the real attribute."""
        self._update_attribute(self.AttributeDefs.charging_protection_limit.id, round(value * 100))

    async def write_attributes(
        self,
        attributes: dict[str | int | ZCLAttributeDef, Any],
        **kwargs,
    ) -> list:
        """Write the Charging protection limit to the real attribute as rounded binary32."""
        attr_id = H2EUOutletManufacturerCluster.AttributeDefs.charging_protection_limit.id

        for value in attributes.values():
            value = struct.unpack("<f", struct.pack("<f", int(value) / 100))[0]

        return await self.endpoint.h2eu_manufacturer.write_attributes({attr_id: value})


class H2EUOutletHeartbeatCluster(LocalDataCluster):
    """Heartbeat cluster for the Wall Outlet H2 EU."""

    cluster_id = 0xFC02
    ep_attribute = "heartbeat"

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
            type=t.Single,
            manufacturer_code=None,
        )

    _VALID_ATTRIBUTES: set[int] = {
        AttributeDefs.current.id,
        AttributeDefs.voltage.id,
        AttributeDefs.energy.id,
        AttributeDefs.device_temperature.id,
    }


(
    QuirkBuilder("Aqara", "lumi.plug.aeu001")
    .friendly_name(manufacturer="Aqara", model="Wall Outlet H2 EU")
    .removes(TemperatureMeasurement.cluster_id)
    .removes(Metering.cluster_id)
    .removes(ElectricalMeasurement.cluster_id)
    .replaces(H2EUOutletManufacturerCluster)
    .adds(H2EUOutletHeartbeatCluster)
    .adds(H2EUOutletChargingLimitCluster)
    .switch(
        attribute_name="button_lock",
        cluster_id=H2EUOutletManufacturerCluster.cluster_id,
        off_value=1,
        on_value=0,
        translation_key="button_lock",
        fallback_name="Button lock",
    )
    .enum(
        attribute_name="power_on_behavior",
        enum_class=PowerOnBehavior,
        cluster_id=H2EUOutletManufacturerCluster.cluster_id,
        translation_key="power_on_behavior",
        fallback_name="Power-on behavior",
    )
    .number(
        attribute_name="overload_protection",
        cluster_id=H2EUOutletManufacturerCluster.cluster_id,
        min_value=100,
        max_value=3840,
        step=1,
        unit=UnitOfPower.WATT,
        translation_key="overload_protection",
        fallback_name="Overload protection",
    )
    .switch(
        attribute_name="led_indicator",
        cluster_id=H2EUOutletManufacturerCluster.cluster_id,
        translation_key="led_indicator",
        fallback_name="LED indicator",
    )
    .switch(
        attribute_name="charging_protection",
        cluster_id=H2EUOutletManufacturerCluster.cluster_id,
        translation_key="charging_protection",
        fallback_name="Charging protection",
    )
    .number(
        attribute_name="charging_protection_limit",
        cluster_id=H2EUOutletChargingLimitCluster.cluster_id,
        min_value=0.1,
        max_value=2.0,
        step=0.1,
        multiplier=0.01,
        unit=UnitOfPower.WATT,
        translation_key="charging_protection_limit",
        fallback_name="Charging protection limit",
    )
    .sensor(
        attribute_name="present_value",
        cluster_id=AnalogInput.cluster_id,
        endpoint_id=21,
        device_class=SensorDeviceClass.POWER,
        state_class=SensorStateClass.MEASUREMENT,
        unit=UnitOfPower.WATT,
        fallback_name="Power",
    )
    .sensor(
        attribute_name="current",
        cluster_id=H2EUOutletHeartbeatCluster.cluster_id,
        device_class=SensorDeviceClass.CURRENT,
        state_class=SensorStateClass.MEASUREMENT,
        unit=UnitOfElectricCurrent.AMPERE,
        fallback_name="Current",
    )
    .sensor(
        attribute_name="voltage",
        cluster_id=H2EUOutletHeartbeatCluster.cluster_id,
        device_class=SensorDeviceClass.VOLTAGE,
        state_class=SensorStateClass.MEASUREMENT,
        unit=UnitOfElectricPotential.VOLT,
        fallback_name="Voltage",
    )
    .sensor(
        attribute_name="energy",
        cluster_id=H2EUOutletHeartbeatCluster.cluster_id,
        device_class=SensorDeviceClass.ENERGY,
        state_class=SensorStateClass.TOTAL_INCREASING,
        unit=UnitOfEnergy.KILO_WATT_HOUR,
        fallback_name="Energy",
    )
    .sensor(
        attribute_name="device_temperature",
        cluster_id=H2EUOutletHeartbeatCluster.cluster_id,
        device_class=SensorDeviceClass.TEMPERATURE,
        state_class=SensorStateClass.MEASUREMENT,
        unit=UnitOfTemperature.CELSIUS,
        entity_type=EntityType.DIAGNOSTIC,
        translation_key="device_temperature",
        fallback_name="Device temperature",
    )
    .skip_configuration()
    .add_to_registry()
)