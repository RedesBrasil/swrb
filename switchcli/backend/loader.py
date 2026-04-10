#!/usr/bin/env python3
"""
Carrega startup-config e aplica as configuracoes no kernel.
Executado pelo init script no boot (antes do CLI interativo).
"""

import sys
import os

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from backend.config_store import ConfigStore
from backend.vlan import set_access_vlan, set_trunk_allowed_vlans
from backend.interface import set_interface_shutdown
from backend import ip_mgmt


def _apply_speed_duplex(eth, speed, duplex):
    try:
        ip_mgmt.set_interface_speed_duplex(eth, speed, duplex)
    except Exception:
        pass


def load_and_apply(config_path=None):
    # Sempre aplica group_fwd_mask independente de ter startup-config.
    # Necessario para que lldpd receba frames LLDP nas interfaces bridgeadas.
    ip_mgmt.setup_lldp_bridge()

    store = ConfigStore()
    if not store.load_startup():
        return

    # Aplicar hostname
    try:
        with open("/etc/hostname", "w") as f:
            f.write(store.hostname + "\n")
    except PermissionError:
        pass

    # Aplicar configuracao de cada interface fisica
    for port_num, iface in store.interfaces.items():
        eth = f"eth{port_num}"
        try:
            if iface.mode == "access" and iface.access_vlan != 1:
                set_access_vlan(eth, iface.access_vlan)
            elif iface.mode == "trunk" and iface.trunk_allowed_vlans:
                set_trunk_allowed_vlans(
                    eth,
                    iface.trunk_allowed_vlans,
                    native_vlan=iface.native_vlan,
                )
            if iface.shutdown:
                set_interface_shutdown(eth, shutdown=True)
            # Aplicar speed/duplex (best-effort — virtio pode ignorar)
            if iface.speed != "auto" or iface.duplex != "auto":
                _apply_speed_duplex(eth, iface.speed, iface.duplex)
        except Exception as e:
            print(f"Warning: failed to configure eth{port_num}: {e}",
                  file=sys.stderr)

    # Aplicar Management0
    mgmt = store.management
    try:
        if mgmt.method == "dhcp":
            ip_mgmt.set_mgmt_dhcp()
        elif mgmt.method == "static" and mgmt.ip_address and mgmt.subnet_mask:
            ip_mgmt.set_mgmt_ip(mgmt.ip_address, mgmt.subnet_mask)
        if mgmt.shutdown:
            ip_mgmt.set_mgmt_state(shutdown=True)
    except Exception as e:
        print(f"Warning: failed to configure Management0: {e}", file=sys.stderr)

    # Aplicar SVIs (interfaces VlanX)
    for vlan_id, svi in store.svi_interfaces.items():
        try:
            ip_mgmt.create_svi(vlan_id)
            if svi.ip_address and svi.subnet_mask:
                ip_mgmt.set_svi_ip(vlan_id, svi.ip_address, svi.subnet_mask)
            ip_mgmt.set_svi_state(vlan_id, shutdown=svi.shutdown)
        except Exception as e:
            print(f"Warning: failed to configure Vlan{vlan_id}: {e}",
                  file=sys.stderr)

    # Aplicar default-gateway
    if store.default_gateway:
        try:
            ip_mgmt.set_default_gateway(store.default_gateway)
        except Exception as e:
            print(f"Warning: failed to set default-gateway: {e}",
                  file=sys.stderr)

    # Aplicar rotas estaticas
    for route in store.static_routes:
        try:
            ip_mgmt.add_static_route(route.network, route.mask, route.gateway)
        except Exception as e:
            print(f"Warning: failed to add route {route.network}: {e}",
                  file=sys.stderr)

    # LLDP: aplicar group_fwd_mask sempre (necessario para receber frames LLDP
    # nas interfaces bridgeadas — identico ao comportamento Cisco Catalyst)
    ip_mgmt.setup_lldp_bridge()
    if store.lldp_enabled:
        try:
            ok, err = ip_mgmt.start_lldp(
                timer=store.lldp_timer,
                holdtime=store.lldp_holdtime,
                reinit=store.lldp_reinit,
            )
            if ok:
                for port_num, iface in store.interfaces.items():
                    eth = f"eth{port_num}"
                    ip_mgmt.set_lldp_interface(
                        eth, iface.lldp_transmit, iface.lldp_receive)
        except Exception as e:
            print(f"Warning: failed to start lldpd: {e}", file=sys.stderr)


if __name__ == "__main__":
    config_path = sys.argv[1] if len(sys.argv) > 1 else None
    load_and_apply(config_path)
