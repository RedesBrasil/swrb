"""
Comandos de configuracao de interface:
switchport mode, switchport access/trunk vlan, shutdown, description.
Comandos SVI: ip address, shutdown, description.
Comandos Management0: ip address, shutdown, description.
"""

import ipaddress

from backend.vlan import set_access_vlan, set_trunk_allowed_vlans, remove_access_vlan
from backend.interface import set_interface_shutdown
from backend.bridge import eth_to_port_num
from backend import ip_mgmt
from cli.parser import parse_vlan_list


def cmd_switchport_mode(config_store, eth_names, args):
    if not args:
        print("% Incomplete command.")
        return
    mode = args[0].lower()
    if mode not in ("access", "trunk"):
        print("% Invalid input detected at '^' marker.")
        return
    for eth in eth_names:
        port = eth_to_port_num(eth)
        if port is None:
            continue
        iface = config_store.get_interface(port)
        if iface:
            iface.mode = mode


def cmd_switchport_access_vlan(config_store, eth_names, args):
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
    if not args:
        print("% Incomplete command.")
        return
    first = args[0].lower()
    if first in ("add", "remove", "except"):
        if len(args) < 2:
            print("% Incomplete command.")
            return
        vlan_list = parse_vlan_list(args[1])
        if not vlan_list:
            print("% Bad VLAN list.")
            return
        action = first
        extra_list = vlan_list
    elif first == "none":
        action = "none"
        extra_list = []
    elif first == "all":
        action = "all"
        extra_list = []
    else:
        vlan_list = parse_vlan_list(args[0])
        if not vlan_list:
            print("% Bad VLAN list.")
            return
        action = "set"
        extra_list = vlan_list

    for eth in eth_names:
        port = eth_to_port_num(eth)
        if port is None:
            continue
        iface = config_store.get_interface(port)
        if not iface:
            continue
        current = list(iface.trunk_allowed_vlans)
        if action == "set":
            new_list = sorted(extra_list)
        elif action == "add":
            new_list = sorted(set(current) | set(extra_list))
        elif action == "remove":
            new_list = sorted(set(current) - set(extra_list))
        elif action == "except":
            new_list = sorted(set(range(1, 4095)) - set(extra_list))
        elif action == "none":
            new_list = []
        elif action == "all":
            new_list = []
        for vid in new_list:
            config_store.register_vlan(vid)
        iface.trunk_allowed_vlans = new_list
        try:
            set_trunk_allowed_vlans(eth, new_list, native_vlan=iface.native_vlan)
        except Exception as e:
            print(f"% Error configuring {eth}: {e}")


def cmd_switchport_trunk_native_vlan(config_store, eth_names, args):
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
                        eth, iface.trunk_allowed_vlans, native_vlan=vlan_id)
                except Exception as e:
                    print(f"% Error configuring {eth}: {e}")


def cmd_no_switchport_access_vlan(config_store, eth_names):
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
    desc = " ".join(args) if args else ""
    for eth in eth_names:
        port = eth_to_port_num(eth)
        if port is None:
            continue
        iface = config_store.get_interface(port)
        if iface:
            iface.description = desc


def cmd_cleanup_vlan_from_ports(config_store, vlan_id):
    from backend.vlan import set_access_vlan, set_trunk_allowed_vlans
    for port_num, iface in config_store.interfaces.items():
        eth = f"eth{port_num}"
        if iface.mode == "access" and iface.access_vlan == vlan_id:
            iface.access_vlan = 1
            try:
                set_access_vlan(eth, 1)
            except Exception:
                pass
        elif iface.mode == "trunk" and vlan_id in iface.trunk_allowed_vlans:
            iface.trunk_allowed_vlans = sorted(
                set(iface.trunk_allowed_vlans) - {vlan_id}
            )
            try:
                set_trunk_allowed_vlans(
                    eth, iface.trunk_allowed_vlans, native_vlan=iface.native_vlan)
            except Exception:
                pass


# ── SVI (interface VlanX) ──────────────────────────────────────────────────────

def _is_valid_ip(ip_str):
    try:
        ipaddress.IPv4Address(ip_str)
        return True
    except ValueError:
        return False


def _is_valid_mask(mask_str):
    try:
        ipaddress.IPv4Network(f"0.0.0.0/{mask_str}")
        return True
    except ValueError:
        return False


def cmd_svi_ip_address(config_store, vlan_id, args):
    if len(args) < 2:
        print("% Incomplete command.")
        return
    ip_addr, mask = args[0], args[1]
    if not _is_valid_ip(ip_addr):
        print("% Invalid IP address.")
        return
    if not _is_valid_mask(mask):
        print("% Invalid subnet mask.")
        return
    svi = config_store.get_or_create_svi(vlan_id)
    svi.ip_address = ip_addr
    svi.subnet_mask = mask
    try:
        ip_mgmt.set_svi_ip(vlan_id, ip_addr, mask)
    except Exception as e:
        print(f"% Error configuring Vlan{vlan_id}: {e}")


def cmd_no_svi_ip_address(config_store, vlan_id):
    svi = config_store.get_or_create_svi(vlan_id)
    svi.ip_address = None
    svi.subnet_mask = None
    try:
        ip_mgmt.remove_svi_ip(vlan_id)
    except Exception as e:
        print(f"% Error removing IP from Vlan{vlan_id}: {e}")


def cmd_svi_shutdown(config_store, vlan_id, negate=False):
    svi = config_store.get_or_create_svi(vlan_id)
    svi.shutdown = not negate
    try:
        ip_mgmt.set_svi_state(vlan_id, shutdown=not negate)
    except Exception as e:
        print(f"% Error configuring Vlan{vlan_id}: {e}")


def cmd_svi_description(config_store, vlan_id, args):
    desc = " ".join(args) if args else ""
    svi = config_store.get_or_create_svi(vlan_id)
    svi.description = desc


# ── Management0 (eth0) ─────────────────────────────────────────────────────────

def cmd_mgmt_ip_address(config_store, args):
    """ip address <ip> <mask>  OU  ip address dhcp  na Management0."""
    if not args:
        print("% Incomplete command.")
        return
    # Forma DHCP
    if args[0].lower() == "dhcp":
        config_store.management.method = "dhcp"
        config_store.management.ip_address = None
        config_store.management.subnet_mask = None
        try:
            ok = ip_mgmt.set_mgmt_dhcp()
            if not ok:
                print("% DHCP request failed (no lease obtained)")
            else:
                info = ip_mgmt.get_mgmt_info()
                if info.get("ip"):
                    print(f"% Management0 acquired IP {info['ip']} via DHCP")
        except Exception as e:
            print(f"% Error requesting DHCP: {e}")
        return
    # Forma estatica
    if len(args) < 2:
        print("% Incomplete command.")
        return
    ip_addr, mask = args[0], args[1]
    if not _is_valid_ip(ip_addr):
        print("% Invalid IP address.")
        return
    if not _is_valid_mask(mask):
        print("% Invalid subnet mask.")
        return
    config_store.management.method = "static"
    config_store.management.ip_address = ip_addr
    config_store.management.subnet_mask = mask
    try:
        ip_mgmt.set_mgmt_ip(ip_addr, mask)
    except Exception as e:
        print(f"% Error configuring Management0: {e}")


def cmd_no_mgmt_ip_address(config_store):
    """no ip address na Management0."""
    config_store.management.ip_address = None
    config_store.management.subnet_mask = None
    config_store.management.method = "unset"
    try:
        ip_mgmt.remove_mgmt_ip()
    except Exception as e:
        print(f"% Error removing IP from Management0: {e}")


def cmd_mgmt_shutdown(config_store, negate=False):
    """shutdown / no shutdown na Management0."""
    config_store.management.shutdown = not negate
    try:
        ip_mgmt.set_mgmt_state(shutdown=not negate)
    except Exception as e:
        print(f"% Error configuring Management0: {e}")


def cmd_mgmt_description(config_store, args):
    desc = " ".join(args) if args else ""
    config_store.management.description = desc


# ── Speed / Duplex (interface fisica) ──────────────────────────────────────────

_VALID_SPEEDS = ("auto", "10", "100", "1000")
_VALID_DUPLEX = ("auto", "full", "half")


def cmd_interface_speed(config_store, eth_names, args):
    """speed auto|10|100|1000"""
    if not args:
        print("% Incomplete command.")
        return
    spd = args[0].lower()
    if spd not in _VALID_SPEEDS:
        print(f"% Invalid speed. Valid: {', '.join(_VALID_SPEEDS)}")
        return
    for eth in eth_names:
        port = eth_to_port_num(eth)
        if port is None:
            continue
        iface = config_store.get_interface(port)
        if iface:
            iface.speed = spd
            try:
                ip_mgmt.set_interface_speed_duplex(eth, iface.speed, iface.duplex)
            except Exception:
                pass


def cmd_interface_duplex(config_store, eth_names, args):
    """duplex auto|full|half"""
    if not args:
        print("% Incomplete command.")
        return
    dpx = args[0].lower()
    if dpx not in _VALID_DUPLEX:
        print(f"% Invalid duplex. Valid: {', '.join(_VALID_DUPLEX)}")
        return
    for eth in eth_names:
        port = eth_to_port_num(eth)
        if port is None:
            continue
        iface = config_store.get_interface(port)
        if iface:
            iface.duplex = dpx
            try:
                ip_mgmt.set_interface_speed_duplex(eth, iface.speed, iface.duplex)
            except Exception:
                pass


# ── LLDP por interface ─────────────────────────────────────────────────────────

def cmd_lldp_transmit(config_store, eth_names, enable=True):
    """lldp transmit / no lldp transmit"""
    for eth in eth_names:
        port = eth_to_port_num(eth)
        if port is None:
            continue
        iface = config_store.get_interface(port)
        if iface:
            iface.lldp_transmit = enable
            if config_store.lldp_enabled:
                try:
                    ip_mgmt.set_lldp_interface(eth, iface.lldp_transmit, iface.lldp_receive)
                except Exception:
                    pass


def cmd_lldp_receive(config_store, eth_names, enable=True):
    """lldp receive / no lldp receive"""
    for eth in eth_names:
        port = eth_to_port_num(eth)
        if port is None:
            continue
        iface = config_store.get_interface(port)
        if iface:
            iface.lldp_receive = enable
            if config_store.lldp_enabled:
                try:
                    ip_mgmt.set_lldp_interface(eth, iface.lldp_transmit, iface.lldp_receive)
                except Exception:
                    pass
