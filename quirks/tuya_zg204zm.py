"""Quirk for Tuya ZG-204ZM."""

from zhaquirks.builder import (
    EntityPlatform,
    EntityType,
    NumberDeviceClass,
    UnitOfLength,
    UnitOfTime,
)
from zhaquirks.const import BatterySize
from zhaquirks.tuya.builder import TuyaIlluminance, TuyaQuirkBuilder
from zhaquirks.tuya.tuya_motion import (
    TuyaHumanMotionStateV02,
    TuyaOccupancySensing,
)
from zigpy import types as t
from zigpy.zcl.clusters.measurement import OccupancySensing
from zigpy.zcl.clusters.security import IasZone


class TuyaMotionDetectionMode(t.enum8):
    Only_PIR = 0x00
    PIR_and_radar = 0x01
    Only_radar = 0x02


class ZG204ZMIlluminance(TuyaIlluminance):
    """ZG-204ZM illuminance with corrected scale."""

    def _update_attribute(self, attrid, value):
        if attrid == self.AttributeDefs.measured_value.id:
            value = max(0, value - 10000)

        super()._update_attribute(attrid, value)


(
    TuyaQuirkBuilder("_TZE200_2aaelwxk", "TS0601")
    .applies_to("_TZE200_kb5noeto", "TS0601")
    .applies_to("_TZE200_tyffvoij", "TS0601")
    .applies_to("_TZE200_yflzeeqj", "TS0601")
    .applies_to("HOBEIAN", "ZG-204ZM")
    .friendly_name(manufacturer="Tuya", model="ZG-204ZM")
    .removes(IasZone.cluster_id)
    .tuya_dp(
        dp_id=1,
        ep_attribute=TuyaOccupancySensing.ep_attribute,
        attribute_name=OccupancySensing.AttributeDefs.occupancy.name,
        converter=lambda x: x == 1,
    )
    .adds(TuyaOccupancySensing)
    .tuya_number(
        dp_id=2,
        attribute_name="static_detection_sensitivity",
        type=t.uint16_t,
        min_value=0,
        max_value=10,
        step=1,
        translation_key="static_detection_sensitivity",
        fallback_name="Static detection sensitivity",
    )
    .tuya_number(
        dp_id=4,
        attribute_name="static_detection_distance",
        type=t.uint16_t,
        device_class=NumberDeviceClass.DISTANCE,
        unit=UnitOfLength.METERS,
        min_value=0,
        max_value=6,
        step=0.1,
        multiplier=0.01,
        translation_key="static_detection_distance",
        fallback_name="Static detection distance",
    )
    .tuya_enum(
        dp_id=101,
        attribute_name="human_motion_state",
        enum_class=TuyaHumanMotionStateV02,
        entity_platform=EntityPlatform.SENSOR,
        entity_type=EntityType.STANDARD,
        initially_disabled=True,
        translation_key="human_motion_state",
        fallback_name="Human motion state",
    )
    .tuya_number(
        dp_id=102,
        attribute_name="presence_timeout",
        type=t.uint16_t,
        device_class=NumberDeviceClass.DURATION,
        unit=UnitOfTime.SECONDS,
        min_value=0,
        max_value=28800,
        step=1,
        translation_key="fading_time",
        fallback_name="Fading time",
    )
    .tuya_illuminance(
        dp_id=106,
        illuminance_cfg=ZG204ZMIlluminance,
    )
    .tuya_switch(
        dp_id=107,
        attribute_name="find_switch",
        translation_key="led_indicator",
        fallback_name="LED indicator",
    )
    .tuya_battery(
        dp_id=121,
        battery_type=BatterySize.AAA,
        battery_qty=2,
    )
    .tuya_enum(
        dp_id=122,
        attribute_name="motion_detection_mode",
        enum_class=TuyaMotionDetectionMode,
        translation_key="motion_detection_mode",
        fallback_name="Motion detection mode",
    )
    .tuya_number(
        dp_id=123,
        attribute_name="motion_detection_sensitivity",
        type=t.uint16_t,
        min_value=0,
        max_value=10,
        step=1,
        translation_key="motion_detection_sensitivity",
        fallback_name="Motion detection sensitivity",
    )
    .skip_configuration()
    .add_to_registry()
)
