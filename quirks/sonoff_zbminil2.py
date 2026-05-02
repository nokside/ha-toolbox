"""SONOFF ZBMINI Extreme Zigbee Smart Switch ZBMINIL2"""

from zigpy.quirks.v2 import QuirkBuilder
from zigpy.zdo.types import NodeDescriptor
from zigpy.zcl.clusters.general import PowerConfiguration

SONOFF_NODE_DESCRIPTOR = NodeDescriptor(
    logical_type=2,
    complex_descriptor_available=0,
    user_descriptor_available=0,
    reserved=0,
    aps_flags=0,
    frequency_band=8,
    mac_capability_flags=132,  # fix power source
    manufacturer_code=4742,
    maximum_buffer_size=82,
    maximum_incoming_transfer_size=1024,
    server_mask=11264,
    maximum_outgoing_transfer_size=1024,
    descriptor_capability_field=0,
)

(
    QuirkBuilder("SONOFF", "ZBMINIL2")
    .node_descriptor(SONOFF_NODE_DESCRIPTOR)
    .removes(PowerConfiguration.cluster_id)
    .add_to_registry()
)
