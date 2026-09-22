"""Quirk v2 for SONOFF ZBMINIL2."""

from zhaquirks.builder import QuirkBuilder
from zhaquirks.device import CustomZigpyDevice
from zigpy.zcl import ClusterType
from zigpy.zcl.clusters.general import KeepAlive, PowerConfiguration
from zigpy.zdo.types import MACCapabilityFlags


class ZBMINIL2Device(CustomZigpyDevice):
    """Set ZBMINIL2 to mains power."""

    def __init__(self, *args, **kwargs):
        """Init."""
        super().__init__(*args, **kwargs)

        node_desc = self.node_desc
        if (
            node_desc is not None
            and node_desc.mac_capability_flags == MACCapabilityFlags.AllocateAddress
        ):
            self.node_desc = node_desc.replace(
                mac_capability_flags=(
                    MACCapabilityFlags.AllocateAddress
                    | MACCapabilityFlags.MainsPowered
                )
            )


(
    QuirkBuilder("SONOFF", "ZBMINIL2")
    .zigpy_device_class(ZBMINIL2Device)
    # Remove the empty PowerConfiguration cluster to avoid a fake battery entity.
    .removes(PowerConfiguration.cluster_id, endpoint_id=1)
    # Add the hidden KeepAlive client cluster used by ZBMINIL2.
    .adds(KeepAlive, cluster_type=ClusterType.Client)
    .add_to_registry()
)
