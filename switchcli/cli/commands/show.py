"""
Comandos show: vlan brief, mac address-table, interfaces status/trunk,
ip interface brief, interface VlanX, arp, running-config, startup-config,
spanning-tree, version.
"""

import json
import os
import subprocess

from backend.bridge import linux_to_cisco, format_mac_cisco, REVERSE_MAP
from backend.interface import (
    get_interface_state, get_interface_speed, get_interface_mac,
)
from backend.vlan import get_all_vlans
from backend import ip_mgmt


def show_vlan_brief(config_store):
    kernel_vlans = get_all_vlans()
    vlan_ports = {}
    for entry in kernel_vlans:
        dev = entry.get("ifname", "")
        if dev == "br0":
            continue
        for vlan_info in entry.get("vlans", []):
            vid = vlan_info["vlan"]
            if vid not in vlan_ports:
                vlan_ports[vid] = []
            vlan_ports[vid].append(dev)
    for vid in config_store.vlans:
        if vid not in vlan_ports:
            vlan_ports[vid] = []
    print()
    print("VLAN Name                             Status    Ports")
    print("---- -------------------------------- --------- -------------------------------")
    for vid in sorted(vlan_ports.keys()):
        name = config_store.get_vlan_name(vid)
        if name is None:
            name = "default" if vid == 1 else f"VLAN{vid:04d}"
        ports_str = ", ".join(linux_to_cisco(p) for p in sorted(vlan_ports[vid]))
        print(f"{vid:<4} {name:<32} {'active':<9} {ports_str}")
    print()


def show_mac_address_table():
    result = subprocess.run(
        ["bridge", "-j", "fdb", "show", "dynamic"],
        capture_output=True, text=True,
    )
    try:
        entries = json.loads(result.stdout)
    except json.JSONDecodeError:
        entries = []
    print()
    print("          Mac Address Table")
    print("-------------------------------------------")
    print("Vlan    Mac Address       Type        Ports")
    print("----    -----------       --------    -----")
    for entry in entries:
        mac = entry.get("mac", "")
        dev = entry.get("ifname", "")
        vlan = entry.get("vlan", "")
        if dev == "br0" or mac.startswith("33:33:") or mac == "ff:ff:ff:ff:ff:ff":
            continue
        cisco_mac = format_mac_cisco(mac)
        cisco_port = linux_to_cisco(dev)
        vlan_str = str(vlan) if vlan else "   -"
        print(f"{vlan_str:>4}    {cisco_mac:<17} {'DYNAMIC':<11} {cisco_port}")
    print()


def show_arp():
    """show arp — tabela ARP das SVIs."""
    result = subprocess.run(
        ["ip", "-j", "neigh", "show"],
        capture_output=True, text=True,
    )
    try:
        entries = json.loads(result.stdout)
    except json.JSONDecodeError:
        entries = []

    print()
    print("Protocol  Address          Age (min)  Hardware Addr   Type   Interface")

    found = False
    for entry in entries:
        state = entry.get("state", [])
        # Ignorar entradas incompletas ou failed
        if "FAILED" in state or "INCOMPLETE" in state:
            continue
        dev = entry.get("dev", "")
        # Mostrar apenas entradas de SVIs (vlanX) ou bridge
        if not (dev.startswith("vlan") or dev == "br0"):
            continue
        ip_addr = entry.get("dst", "")
        mac = entry.get("lladdr", "")
        if not ip_addr or not mac:
            continue
        cisco_mac = format_mac_cisco(mac)
        iface_display = dev if dev.startswith("vlan") else dev
        print(f"{'Internet':<10}{ip_addr:<17}{'-':<11}{cisco_mac:<16}{'ARPA':<7}{iface_display}")
        found = True

    if not found:
        print("  (no ARP entries)")
    print()


def show_interfaces_status(config_store):
    print()
    print("Port         Name               Status       Vlan       Duplex  Speed Type")
    print("------------ ------------------ ------------ ---------- ------- ----- ----")
    for i in range(1, 9):
        eth = f"eth{i}"
        cisco = f"Gi0/{i}"
        iface = config_store.get_interface(i)
        state = get_interface_state(eth)
        if iface and iface.shutdown:
            status = "disabled"
        elif state == "up":
            status = "connected"
        else:
            status = "notconnect"
        desc = (iface.description if iface else "")[:18]
        if iface and iface.mode == "trunk":
            vlan_str = "trunk"
        elif iface:
            vlan_str = str(iface.access_vlan)
        else:
            vlan_str = "1"
        speed = get_interface_speed(eth)
        if speed != "auto":
            speed_str = f"a-{speed}"
            duplex_str = "a-full"
        else:
            speed_str = "auto"
            duplex_str = "auto"
        print(f"{cisco:<12} {desc:<18} {status:<12} {vlan_str:<10} "
              f"{duplex_str:<7} {speed_str:<5} 10/100/1000BaseTX")
    print()


def show_interfaces_trunk(config_store):
    trunks = []
    for i in range(1, 9):
        iface = config_store.get_interface(i)
        if iface and iface.mode == "trunk":
            trunks.append((i, iface))
    if not trunks:
        print()
        return
    print()
    print("Port        Mode         Encapsulation  Status        Native vlan")
    print("----------- ------------ -------------- ------------- -----------")
    for port_num, iface in trunks:
        cisco = f"Gi0/{port_num}"
        state = get_interface_state(f"eth{port_num}")
        status = "trunking" if state == "up" else "not-trunking"
        print(f"{cisco:<11} {'on':<12} {'802.1q':<14} {status:<13} {iface.native_vlan}")
    print()
    print("Port        Vlans allowed on trunk")
    print("----------- --------------------------------------")
    for port_num, iface in trunks:
        cisco = f"Gi0/{port_num}"
        vlans = ",".join(str(v) for v in sorted(iface.trunk_allowed_vlans)) if iface.trunk_allowed_vlans else "ALL"
        print(f"{cisco:<11} {vlans}")
    print()
    print("Port        Vlans allowed and active in management domain")
    print("----------- --------------------------------------")
    for port_num, iface in trunks:
        cisco = f"Gi0/{port_num}"
        if iface.trunk_allowed_vlans:
            active = [v for v in iface.trunk_allowed_vlans if v in config_store.vlans]
            vlans = ",".join(str(v) for v in sorted(active))
        else:
            vlans = "ALL"
        print(f"{cisco:<11} {vlans}")
    print()


def show_interface_vlan(config_store, vlan_id):
    svi = config_store.get_svi(vlan_id)
    info = ip_mgmt.get_svi_info(vlan_id)
    state = info["state"] if info["exists"] else "down"
    line_proto = "up" if state == "up" else "down"
    admin_state = "up"
    if svi and svi.shutdown:
        admin_state = "administratively down"
        line_proto = "down"
    print(f"\nVlan{vlan_id} is {admin_state}, line protocol is {line_proto}")
    print(f"  Hardware is EtherSVI, address is 0000.0000.0000")
    if svi and svi.description:
        print(f"  Description: {svi.description}")
    ip_addr = info.get("ip") or (svi.ip_address if svi else None)
    mask = info.get("mask") or (svi.subnet_mask if svi else None)
    if ip_addr and mask:
        print(f"  Internet address is {ip_addr}/{_mask_to_prefix(mask)}")
    else:
        print("  Internet address is unassigned")
    print(f"  MTU 1500 bytes")
    print()


def _mask_to_prefix(mask):
    try:
        import ipaddress
        return ipaddress.IPv4Network(f"0.0.0.0/{mask}").prefixlen
    except ValueError:
        return mask


def show_ip_interface_brief(config_store):
    print("\nInterface              IP-Address      OK? Method Status    Protocol")
    print("---------------------- --------------- --- ------ ---------- --------")
    # Portas físicas (L2 switchports — sem IP)
    for i in range(1, 9):
        eth = f"eth{i}"
        cisco = f"GigabitEthernet0/{i}"
        iface = config_store.get_interface(i)
        state = get_interface_state(eth)
        if iface and iface.shutdown:
            status, proto = "administratively down", "down"
        elif state == "up":
            status, proto = "up", "up"
        else:
            status, proto = "down", "down"
        print(f"{cisco:<22} {'unassigned':<15} YES unset  {status:<10} {proto}")
    # SVIs (L3 — com IP)
    svix = config_store.svi_interfaces
    for vlan_id in sorted(svix.keys()):
        svi = svix[vlan_id]
        info = ip_mgmt.get_svi_info(vlan_id)
        iface_name = f"Vlan{vlan_id}"
        ip_display = info.get("ip") or svi.ip_address or "unassigned"
        ok = "YES" if ip_display != "unassigned" else "NO"
        if svi.shutdown:
            status, proto = "admin down", "down"
        elif info["exists"] and info["state"] == "up":
            status, proto = "up", "up"
        else:
            status, proto = "down", "down"
        print(f"{iface_name:<22} {ip_display:<15} {ok:<3} manual {status:<10} {proto}")
    print()


def show_running_config(config_store):
    lines = []
    lines.append("Building configuration...")
    lines.append("")
    lines.append("Current configuration:")
    lines.append("!")
    lines.append(f"hostname {config_store.hostname}")
    lines.append("!")
    if config_store.enable_password:
        lines.append(f"enable password {config_store.enable_password}")
        lines.append("!")
    if config_store.default_gateway:
        lines.append(f"ip default-gateway {config_store.default_gateway}")
        lines.append("!")
    for vid in sorted(config_store.vlans.keys()):
        if vid == 1:
            continue
        name = config_store.vlans[vid]
        lines.append(f"vlan {vid}")
        if name:
            lines.append(f" name {name}")
        lines.append("!")
    for i in range(1, 9):
        iface = config_store.get_interface(i)
        if not iface:
            continue
        lines.append(f"interface GigabitEthernet0/{i}")
        if iface.description:
            lines.append(f" description {iface.description}")
        if iface.mode == "access":
            lines.append(" switchport mode access")
            if iface.access_vlan != 1:
                lines.append(f" switchport access vlan {iface.access_vlan}")
        elif iface.mode == "trunk":
            lines.append(" switchport mode trunk")
            if iface.native_vlan != 1:
                lines.append(f" switchport trunk native vlan {iface.native_vlan}")
            if iface.trunk_allowed_vlans:
                vlans_str = ",".join(str(v) for v in sorted(iface.trunk_allowed_vlans))
                lines.append(f" switchport trunk allowed vlan {vlans_str}")
        if iface.shutdown:
            lines.append(" shutdown")
        lines.append("!")
    for vid in sorted(config_store.svi_interfaces.keys()):
        svi = config_store.svi_interfaces[vid]
        lines.append(f"interface Vlan{vid}")
        if svi.description:
            lines.append(f" description {svi.description}")
        if svi.ip_address and svi.subnet_mask:
            lines.append(f" ip address {svi.ip_address} {svi.subnet_mask}")
        lines.append(" no shutdown" if not svi.shutdown else " shutdown")
        lines.append("!")
    lines.append("end")
    lines.append("")
    print("\n".join(lines))


def show_startup_config():
    path = "/opt/switchcli/configs/startup-config"
    if not os.path.exists(path):
        print("startup-config is not present")
        return
    with open(path) as f:
        data = json.load(f)
    from backend.config_store import ConfigStore
    temp = ConfigStore()
    temp._deserialize(data)
    show_running_config(temp)


def show_spanning_tree():
    bridge_path = "/sys/class/net/br0/bridge"
    try:
        with open(f"{bridge_path}/bridge_id") as f:
            bridge_id = f.read().strip()
        with open(f"{bridge_path}/root_id") as f:
            root_id = f.read().strip()
        with open(f"{bridge_path}/hello_time") as f:
            hello_time = int(f.read().strip()) // 256
        with open(f"{bridge_path}/max_age") as f:
            max_age = int(f.read().strip()) // 256
        with open(f"{bridge_path}/forward_delay") as f:
            fwd_delay = int(f.read().strip()) // 256
    except (FileNotFoundError, ValueError):
        print("% Spanning-tree not available")
        return
    print()
    print("VLAN0001")
    print(f"  Spanning tree enabled protocol ieee")
    print(f"  Root ID    Priority    {root_id.split('.')[0] if '.' in root_id else 'N/A'}")
    print(f"             Address     {root_id}")
    print(f"  Bridge ID  Priority    {bridge_id.split('.')[0] if '.' in bridge_id else 'N/A'}")
    print(f"             Address     {bridge_id}")
    print(f"             Hello Time  {hello_time} sec  Max Age {max_age} sec  Forward Delay {fwd_delay} sec")
    print()
    print("Interface           Role Sts Cost      Prio.Nbr Type")
    print("------------------- ---- --- --------- -------- ----")
    for i in range(1, 9):
        eth = f"eth{i}"
        port_path = f"/sys/class/net/{eth}/brport"
        if not os.path.exists(port_path):
            continue
        try:
            with open(f"{port_path}/state") as f:
                state_num = int(f.read().strip())
            with open(f"{port_path}/port_no") as f:
                port_no = f.read().strip()
            with open(f"{port_path}/path_cost") as f:
                cost = f.read().strip()
            with open(f"{port_path}/priority") as f:
                prio = f.read().strip()
        except (FileNotFoundError, ValueError):
            continue
        state_map = {0: "DIS", 1: "LIS", 2: "LRN", 3: "FWD", 4: "BLK"}
        sts = state_map.get(state_num, "???")
        role = "Desg" if sts == "FWD" else "Altn"
        print(f"Gi0/{i:<15} {role:<4} {sts:<3} {cost:<9} {prio}.{port_no:<5} P2p")
    print()


def show_version():
    from cli.banner import format_uptime
    hostname = "Switch"
    try:
        with open("/etc/hostname") as f:
            hostname = f.read().strip() or "Switch"
    except (FileNotFoundError, PermissionError):
        pass
    try:
        with open("/proc/uptime") as f:
            uptime = int(float(f.read().split()[0]))
    except (FileNotFoundError, PermissionError, ValueError):
        uptime = 0
    uptime_str = format_uptime(uptime)
    mac = "00:AA:BB:CC:DD:00"
    try:
        with open("/sys/class/net/eth0/address") as f:
            mac = f.read().strip().upper()
    except (FileNotFoundError, PermissionError):
        pass
    print(f"""
Cisco IOS Software, C2960 Software (C2960-LANBASEK9-M), Version 15.0(2)SE11
Copyright (c) 1986-2024 by Cisco Systems, Inc.

ROM: Bootstrap program is C2960 boot loader

{hostname} uptime is {uptime_str}

cisco WS-C2960-8TC-L (PowerPC405) processor with 65536K bytes of memory.
8 Ethernet interfaces
512K bytes of flash-simulated non-volatile configuration memory.
Base ethernet MAC Address       : {mac}
Model number                    : WS-C2960-8TC-L
System serial number            : FCZ123456AB
""")




def show_running_config_interface(config_store, tokens):
    """show running-config interface Gi0/1 | Vlan200"""
    import re
    from backend.bridge import parse_interface_spec, eth_to_port_num

    if not tokens:
        print("% Incomplete command.")
        return

    spec = "".join(tokens)

    # SVI: VlanX
    m = re.match(r'^[Vv][Ll][Aa][Nn]\s*(\d+)$', spec)
    if m:
        vlan_id = int(m.group(1))
        svi = config_store.get_svi(vlan_id)
        if not svi:
            print(f"% interface Vlan{vlan_id} not configured.")
            return
        lines = ["Building configuration...", "",
                 f"interface Vlan{vlan_id}"]
        if svi.description:
            lines.append(f" description {svi.description}")
        if svi.ip_address and svi.subnet_mask:
            lines.append(f" ip address {svi.ip_address} {svi.subnet_mask}")
        lines.append(" no shutdown" if not svi.shutdown else " shutdown")
        lines.append("end")
        print("\n".join(lines))
        return

    # Interface fisica: Gi0/1
    eths = parse_interface_spec(spec)
    if not eths:
        print("% Invalid interface specification.")
        return
    eth = eths[0]
    port = eth_to_port_num(eth)
    if port is None:
        print("% Invalid interface.")
        return
    iface = config_store.get_interface(port)
    if not iface:
        print("% Interface not found.")
        return

    lines = ["Building configuration...", "",
             f"interface GigabitEthernet0/{port}"]
    if iface.description:
        lines.append(f" description {iface.description}")
    if iface.mode == "access":
        lines.append(" switchport mode access")
        if iface.access_vlan != 1:
            lines.append(f" switchport access vlan {iface.access_vlan}")
    elif iface.mode == "trunk":
        lines.append(" switchport mode trunk")
        if iface.native_vlan != 1:
            lines.append(f" switchport trunk native vlan {iface.native_vlan}")
        if iface.trunk_allowed_vlans:
            vlans_str = ",".join(str(v) for v in sorted(iface.trunk_allowed_vlans))
            lines.append(f" switchport trunk allowed vlan {vlans_str}")
    if iface.shutdown:
        lines.append(" shutdown")
    lines.append("end")
    print("\n".join(lines))
