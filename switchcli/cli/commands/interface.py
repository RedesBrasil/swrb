"""
Comandos de configuracao de interface:
switchport mode, switchport access/trunk vlan, shutdown, description.
"""

from backend.vlan import set_access_vlan, set_trunk_allowed_vlans, remove_access_vlan
from backend.interface import set_interface_shutdown
from backend.bridge import eth_to_port_num
from cli.parser import parse_vlan_list


def cmd_switchport_mode(config_store, eth_names, args):
    """switchport mode access|trunk"""
    if not args:
        print("% Incomplete command.")
        return
    mode = args[0].lower()
    if mode not in ("access", "trunk"):
        print(f"% Invalid input detected at '^' marker.")
        return

    for eth in eth_names:
        port = eth_to_port_num(eth)
        if port is None:
            continue
        iface = config_store.get_interface(port)
        if iface:
            iface.mode = mode


def cmd_switchport_access_vlan(config_store, eth_names, args):
    """switchport access vlan <id>"""
    if not args:
        print("% Incomplete command.")
        return
    try:
        vlan_id = int(args[0])
    except ValueError:
        print("% Invalid VLAN ID.")
        return

    if vlan_id < 1 or vlan_id > 4094:
        print("% Bad VLAN list - character #1 is out of range.")
        return

    # Registrar a VLAN se nao existir
    config_store.register_vlan(vlan_id)

    for eth in eth_names:
        port = eth_to_port_num(eth)
        if port is None:
            continue
        iface = config_store.get_interface(port)
        if iface:
            iface.access_vlan = vlan_id
            try:
                set_access_vlan(eth, vlan_id)
            except Exception as e:
                print(f"% Error configuring {eth}: {e}")


def cmd_switchport_trunk_allowed_vlan(config_store, eth_names, args):
    """switchport trunk allowed vlan <vlan-list>"""
    if not args:
        print("% Incomplete command.")
        return

    vlan_list = parse_vlan_list(args[0])
    if not vlan_list:
        print("% Bad VLAN list.")
        return

    # Registrar VLANs que nao existem
    for vid in vlan_list:
        config_store.register_vlan(vid)

    for eth in eth_names:
        port = eth_to_port_num(eth)
        if port is None:
            continue
        iface = config_store.get_interface(port)
        if iface:
            iface.trunk_allowed_vlans = vlan_list
            try:
                set_trunk_allowed_vlans(
                    eth, vlan_list, native_vlan=iface.native_vlan)
            except Exception as e:
                print(f"% Error configuring {eth}: {e}")


def cmd_switchport_trunk_native_vlan(config_store, eth_names, args):
    """switchport trunk native vlan <id>"""
    if not args:
        print("% Incomplete command.")
        return
    try:
        vlan_id = int(args[0])
    except ValueError:
        print("% Invalid VLAN ID.")
        return

    config_store.register_vlan(vlan_id)

    for eth in eth_names:
        port = eth_to_port_num(eth)
        if port is None:
            continue
        iface = config_store.get_interface(port)
        if iface:
            iface.native_vlan = vlan_id
            if iface.trunk_allowed_vlans:
                try:
                    set_trunk_allowed_vlans(
                        eth, iface.trunk_allowed_vlans,
                        native_vlan=vlan_id)
                except Exception as e:
                    print(f"% Error configuring {eth}: {e}")


def cmd_no_switchport_access_vlan(config_store, eth_names):
    """no switchport access vlan"""
    for eth in eth_names:
        port = eth_to_port_num(eth)
        if port is None:
            continue
        iface = config_store.get_interface(port)
        if iface:
            iface.access_vlan = 1
            try:
                remove_access_vlan(eth)
            except Exception as e:
                print(f"% Error configuring {eth}: {e}")


def cmd_shutdown(config_store, eth_names, negate=False):
    """shutdown / no shutdown"""
    for eth in eth_names:
        port = eth_to_port_num(eth)
        if port is None:
            continue
        iface = config_store.get_interface(port)
        if iface:
            iface.shutdown = not negate
            try:
                set_interface_shutdown(eth, shutdown=not negate)
            except Exception as e:
                print(f"% Error configuring {eth}: {e}")


def cmd_description(config_store, eth_names, args):
    """description <text>"""
    desc = " ".join(args) if args else ""
    for eth in eth_names:
        port = eth_to_port_num(eth)
        if port is None:
            continue
        iface = config_store.get_interface(port)
        if iface:
            iface.description = desc
