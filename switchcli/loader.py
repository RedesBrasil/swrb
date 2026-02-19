#!/usr/bin/env python3
"""
Carrega startup-config e aplica as configuracoes no kernel.
Executado pelo init script no boot (antes do CLI interativo).
"""

import sys
import os

# Garantir imports
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from backend.config_store import ConfigStore
from backend.vlan import set_access_vlan, set_trunk_allowed_vlans
from backend.interface import set_interface_shutdown


def load_and_apply(config_path=None):
    store = ConfigStore()
    if not store.load_startup():
        return

    # Aplicar hostname
    try:
        with open("/etc/hostname", "w") as f:
            f.write(store.hostname + "\n")
    except PermissionError:
        pass

    # Aplicar configuracao de cada interface
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
        except Exception as e:
            print(f"Warning: failed to configure eth{port_num}: {e}",
                  file=sys.stderr)


if __name__ == "__main__":
    config_path = sys.argv[1] if len(sys.argv) > 1 else None
    load_and_apply(config_path)
