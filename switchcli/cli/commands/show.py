"""
Comandos show: vlan brief, mac address-table, interfaces status/trunk/detail,
ip interface brief, interface VlanX, arp, running-config, startup-config,
spanning-tree, version, Management0.
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
        if "FAILED" in state or "INCOMPLETE" in state:
            continue
        dev = entry.get("dev", "")
        if not (dev.startswith("vlan") or dev == "br0"):
            continue
        ip_addr = entry.get("dst", "")
        mac = entry.get("lladdr", "")
        if not ip_addr or not mac:
            continue
        cisco_mac = format_mac_cisco(mac)
        print(f"{'Internet':<10}{ip_addr:<17}{'-':<11}{cisco_mac:<16}{'ARPA':<7}{dev}")
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


def _read_stat(eth, stat):
    """Le contador de /sys/class/net/ethX/statistics/stat."""
    try:
        with open(f"/sys/class/net/{eth}/statistics/{stat}") as f:
            return int(f.read().strip())
    except (FileNotFoundError, ValueError):
        return 0


def show_interface_detail(config_store, eth, cisco_name=None):
    """show interfaces Gi0/X — contadores detalhados."""
    if cisco_name is None:
        from backend.bridge import linux_to_cisco
        cisco_name = linux_to_cisco(eth)

    state = get_interface_state(eth)
    mac = get_interface_mac(eth)
    speed = get_interface_speed(eth)

    port_num = int(eth.replace("eth", "")) if eth.startswith("eth") else None
    iface = config_store.get_interface(port_num) if port_num else None

    if iface and iface.shutdown:
        admin = "administratively down"
        line_proto = "down"
    elif state == "up":
        admin = "up"
        line_proto = "up"
    else:
        admin = "down"
        line_proto = "down"

    desc_line = ""
    if iface and iface.description:
        desc_line = f"\n  Description: {iface.description}"

    rx_pkts  = _read_stat(eth, "rx_packets")
    rx_bytes = _read_stat(eth, "rx_bytes")
    rx_err   = _read_stat(eth, "rx_errors")
    rx_drop  = _read_stat(eth, "rx_dropped")
    rx_crc   = _read_stat(eth, "rx_crc_errors")
    tx_pkts  = _read_stat(eth, "tx_packets")
    tx_bytes = _read_stat(eth, "tx_bytes")
    tx_err   = _read_stat(eth, "tx_errors")
    tx_drop  = _read_stat(eth, "tx_dropped")
    tx_coll  = _read_stat(eth, "tx_collisions")

    speed_str = f"{speed}Mb/s" if speed != "auto" else "1000Mb/s"

    print(f"""
{cisco_name} is {admin}, line protocol is {line_proto}{desc_line}
  Hardware is Gigabit Ethernet, address is {mac}
  MTU 1500 bytes, BW 1000000 Kbit/sec, DLY 10 usec
  Full-duplex, {speed_str}, media type is 10/100/1000BaseTX
  Last clearing of "show interface" counters never
     {rx_pkts} packets input, {rx_bytes} bytes
     0 runts, 0 giants, 0 throttles
     {rx_err} input errors, {rx_crc} CRC, 0 frame, 0 overrun, 0 ignored
     {rx_drop} input packets dropped
     {tx_pkts} packets output, {tx_bytes} bytes
     {tx_err} output errors, {tx_coll} collisions
     {tx_drop} output packets dropped
""")


def show_interface_management(config_store):
    """show interfaces Management0"""
    info = ip_mgmt.get_mgmt_info()
    mgmt = config_store.management
    state = info["state"]
    if mgmt.shutdown:
        admin = "administratively down"
        line_proto = "down"
    elif state == "up":
        admin = "up"
        line_proto = "up"
    else:
        admin = "down"
        line_proto = "down"

    mac = get_interface_mac("eth0")
    desc_line = f"\n  Description: {mgmt.description}" if mgmt.description else ""
    ip_line = ""
    if info.get("ip") or mgmt.ip_address:
        ip = info.get("ip") or mgmt.ip_address
        mask = info.get("mask") or mgmt.subnet_mask
        prefix = _mask_to_prefix(mask) if mask else "?"
        ip_line = f"\n  Internet address is {ip}/{prefix}"

    rx_pkts  = _read_stat("eth0", "rx_packets")
    rx_bytes = _read_stat("eth0", "rx_bytes")
    tx_pkts  = _read_stat("eth0", "tx_packets")
    tx_bytes = _read_stat("eth0", "tx_bytes")

    print(f"""
Management0 is {admin}, line protocol is {line_proto}{desc_line}
  Hardware is Ethernet, address is {mac}{ip_line}
  MTU 1500 bytes
     {rx_pkts} packets input, {rx_bytes} bytes
     {tx_pkts} packets output, {tx_bytes} bytes
""")


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
    # Management0 (eth0)
    mgmt_info = ip_mgmt.get_mgmt_info()
    mgmt = config_store.management
    mgmt_ip = mgmt_info.get("ip") or mgmt.ip_address or "unassigned"
    mgmt_ok = "YES" if mgmt_ip != "unassigned" else "YES"
    mgmt_method = "manual" if mgmt.ip_address else "DHCP" if mgmt_info.get("ip") else "unset"
    if mgmt.shutdown:
        mgmt_status, mgmt_proto = "admin down", "down"
    elif mgmt_info["state"] == "up":
        mgmt_status, mgmt_proto = "up", "up"
    else:
        mgmt_status, mgmt_proto = "down", "down"
    print(f"{'Management0':<22} {mgmt_ip:<15} {mgmt_ok:<3} {mgmt_method:<6} {mgmt_status:<10} {mgmt_proto}")
    # Portas fisicas
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
    # SVIs
    for vlan_id in sorted(config_store.svi_interfaces.keys()):
        svi = config_store.svi_interfaces[vlan_id]
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
    if config_store.banner_motd:
        lines.append(f"banner motd #{config_store.banner_motd}#")
        lines.append("!")
    if config_store.lldp_enabled:
        lines.append("lldp run")
        if config_store.lldp_timer != 30:
            lines.append(f"lldp timer {config_store.lldp_timer}")
        if config_store.lldp_holdtime != 120:
            lines.append(f"lldp holdtime {config_store.lldp_holdtime}")
        if config_store.lldp_reinit != 2:
            lines.append(f"lldp reinit {config_store.lldp_reinit}")
        lines.append("!")
    for cause in config_store.errdisable_causes:
        lines.append(f"errdisable recovery cause {cause}")
    if config_store.errdisable_interval != 300:
        lines.append(f"errdisable recovery interval {config_store.errdisable_interval}")
    if config_store.errdisable_causes or config_store.errdisable_interval != 300:
        lines.append("!")
    if config_store.spanning_tree_mode != "pvst":
        lines.append(f"spanning-tree mode {config_store.spanning_tree_mode}")
        lines.append("!")
    if config_store.default_gateway:
        lines.append(f"ip default-gateway {config_store.default_gateway}")
        lines.append("!")
    for route in config_store.static_routes:
        lines.append(f"ip route {route.network} {route.mask} {route.gateway}")
    if config_store.static_routes:
        lines.append("!")
    # Management0
    mgmt = config_store.management
    mgmt_has_config = (mgmt.ip_address or mgmt.shutdown or mgmt.description
                       or mgmt.method == "dhcp")
    if mgmt_has_config:
        lines.append("interface Management0")
        if mgmt.description:
            lines.append(f" description {mgmt.description}")
        if mgmt.method == "dhcp":
            lines.append(" ip address dhcp")
        elif mgmt.ip_address and mgmt.subnet_mask:
            lines.append(f" ip address {mgmt.ip_address} {mgmt.subnet_mask}")
        if mgmt.shutdown:
            lines.append(" shutdown")
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
        if iface.speed != "auto":
            lines.append(f" speed {iface.speed}")
        if iface.duplex != "auto":
            lines.append(f" duplex {iface.duplex}")
        if not iface.lldp_transmit:
            lines.append(" no lldp transmit")
        if not iface.lldp_receive:
            lines.append(" no lldp receive")
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


def show_logging():
    """show logging — exibe logs do sistema."""
    print()
    print("Syslog logging: enabled")
    print()
    print("Log Buffer:")
    sources = ["/var/log/messages", "/var/log/syslog"]
    printed = False
    for path in sources:
        if os.path.exists(path):
            try:
                with open(path) as f:
                    content = f.read().splitlines()[-200:]
                for line in content:
                    print(line)
                printed = True
                break
            except (PermissionError, OSError):
                continue
    if not printed:
        result = subprocess.run(
            ["dmesg", "-T"], capture_output=True, text=True,
        )
        if result.returncode == 0:
            lines = result.stdout.splitlines()[-200:]
            for line in lines:
                print(line)
        else:
            print("  (no logs available)")
    print()


def _parse_lldp_neighbor(nb):
    """Extrai campos padronizados de uma entrada de vizinho LLDP."""
    local_if_linux = nb.get("local_if", "")
    local_if = linux_to_cisco(local_if_linux) if local_if_linux else "?"
    chassis = nb.get("chassis", {})
    if isinstance(chassis, dict):
        for k, v in chassis.items():
            if isinstance(v, dict):
                chassis = v
                break
    dev_id = chassis.get("name", "?") if isinstance(chassis, dict) else "?"
    mgmt_ip = None
    if isinstance(chassis, dict):
        mgmt = chassis.get("mgmt-ip", "")
        if isinstance(mgmt, list) and mgmt:
            mgmt_ip = mgmt[0]
        elif isinstance(mgmt, str) and mgmt:
            mgmt_ip = mgmt
    caps = chassis.get("capability", []) if isinstance(chassis, dict) else []
    if isinstance(caps, dict):
        caps = [caps]
    cap_str = ""
    for c in caps:
        if isinstance(c, dict) and c.get("enabled"):
            t = c.get("type", "")
            if t.startswith("Router"): cap_str += "R "
            elif t.startswith("Bridge"): cap_str += "B "
            elif t.startswith("Telephone"): cap_str += "T "
            elif t.startswith("Station"): cap_str += "S "
            elif t.startswith("Wlan"): cap_str += "W "
    cap_str = cap_str.strip()
    port = nb.get("port", {})
    port_id = "?"
    port_desc = ""
    if isinstance(port, dict):
        pid = port.get("id", {})
        if isinstance(pid, dict):
            port_id = pid.get("value", "?")
        port_desc = port.get("descr", "")
    ttl_info = nb.get("ttl", {})
    ttl = ttl_info.get("ttl", "120") if isinstance(ttl_info, dict) else "120"
    return {
        "local_if": local_if,
        "local_if_linux": local_if_linux,
        "dev_id": dev_id,
        "cap_str": cap_str,
        "port_id": port_id,
        "port_desc": port_desc,
        "ttl": str(ttl),
        "mgmt_ip": mgmt_ip or "",
        "chassis": chassis,
        "port_raw": port,
    }


def show_lldp_global(config_store):
    """show lldp — status global"""
    status = "enabled" if config_store.lldp_enabled else "disabled"
    running = ip_mgmt.is_lldp_running()
    print()
    print(f"Global LLDP Information:")
    print(f"  Status: LLDP is {status}")
    print(f"  LLDP advertisements are sent every {config_store.lldp_timer} seconds")
    print(f"  LLDP hold time advertised is {config_store.lldp_holdtime} seconds")
    print(f"  LLDP interface reinitialisation delay is {config_store.lldp_reinit} seconds")
    print(f"  LLDP tlv select:")
    print(f"    Management Address    : enabled")
    print(f"    Port Description      : enabled")
    print(f"    System Capabilities   : enabled")
    print(f"    System Description    : enabled")
    print(f"    System Name           : enabled")
    if config_store.lldp_enabled and not running:
        print()
        print("  % Warning: lldpd is not running (try 'no lldp run' then 'lldp run')")
    print()


def show_lldp_neighbors(config_store):
    """show lldp neighbors"""
    if not config_store.lldp_enabled:
        print("% LLDP is not enabled. Use 'lldp run' in global config.")
        return
    neighbors = ip_mgmt.get_lldp_neighbors()
    print()
    print("Capability codes:")
    print("    (R) Router, (B) Bridge, (T) Telephone, (S) Switch, (W) WLAN Access Point")
    print()
    print(f"{'Device ID':<20} {'Local Intf':<14} {'Hold-time':<11} {'Capability':<16} Port ID")
    print("-" * 75)
    if not neighbors:
        print("  (no neighbors detected)")
        print()
        print("Total entries displayed: 0")
        print()
        return
    count = 0
    for nb in neighbors:
        p = _parse_lldp_neighbor(nb)
        print(f"{p['dev_id']:<20} {p['local_if']:<14} {p['ttl']:<11} {p['cap_str']:<16} {p['port_id']}")
        count += 1
    print()
    print(f"Total entries displayed: {count}")
    print()


def show_lldp_neighbors_detail(config_store):
    """show lldp neighbors detail"""
    if not config_store.lldp_enabled:
        print("% LLDP is not enabled. Use 'lldp run' in global config.")
        return
    neighbors = ip_mgmt.get_lldp_neighbors()
    if not neighbors:
        print()
        print("  (no neighbors detected)")
        print()
        return
    print()
    for nb in neighbors:
        p = _parse_lldp_neighbor(nb)
        print(f"------------------------------------------------")
        print(f"Local Intf: {p['local_if']}")
        print(f"  Chassis id:        {p['dev_id']}")
        print(f"  Port id:           {p['port_id']}")
        if p['port_desc']:
            print(f"  Port Description:  {p['port_desc']}")
        if p['mgmt_ip']:
            print(f"  Management Addr:   {p['mgmt_ip']}")
        print(f"  System Capab:      {p['cap_str']}")
        print(f"  Enabled Capab:     {p['cap_str']}")
        print(f"  TTL:               {p['ttl']} seconds")
    print()
    print(f"Total entries displayed: {len(neighbors)}")
    print()


def show_lldp_interface(config_store, specific_eth=None):
    """show lldp interface [Gi0/X]"""
    if not config_store.lldp_enabled:
        print("% LLDP is not enabled.")
        return
    print()
    print(f"{'Interface':<14} {'Tx':<6} {'Rx':<6} {'Tx-Status':<14} {'Rx-Status'}")
    print("-" * 55)
    for i in range(1, 9):
        eth = f"eth{i}"
        cisco = f"Gi0/{i}"
        if specific_eth and eth != specific_eth:
            continue
        iface = config_store.get_interface(i)
        tx = "enable" if (iface and iface.lldp_transmit) else "disable"
        rx = "enable" if (iface and iface.lldp_receive) else "disable"
        print(f"{cisco:<14} {tx:<6} {rx:<6}")
    print()


def show_ip_route(config_store):
    """show ip route"""
    import ipaddress as _ip
    print()
    print("Codes: C - connected, S - static, * - candidate default")
    print()
    if config_store.default_gateway:
        print(f"Gateway of last resort is {config_store.default_gateway} to network 0.0.0.0")
    else:
        print("Gateway of last resort is not set")
    print()
    mgmt = config_store.management
    if mgmt.ip_address and mgmt.subnet_mask:
        try:
            net = _ip.IPv4Network(f"{mgmt.ip_address}/{mgmt.subnet_mask}", strict=False)
            print(f"C    {net.with_prefixlen} is directly connected, Management0")
        except ValueError:
            pass
    for vlan_id in sorted(config_store.svi_interfaces.keys()):
        svi = config_store.svi_interfaces[vlan_id]
        if svi.ip_address and svi.subnet_mask:
            try:
                net = _ip.IPv4Network(f"{svi.ip_address}/{svi.subnet_mask}", strict=False)
                print(f"C    {net.with_prefixlen} is directly connected, Vlan{vlan_id}")
            except ValueError:
                pass
    for route in config_store.static_routes:
        try:
            net = _ip.IPv4Network(f"{route.network}/{route.mask}", strict=False)
            print(f"S    {net.with_prefixlen} [1/0] via {route.gateway}")
        except ValueError:
            pass
    if config_store.default_gateway:
        print(f"S*   0.0.0.0/0 [1/0] via {config_store.default_gateway}")
    print()


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


def show_spanning_tree(config_store=None):
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

    mode = "ieee"
    if config_store:
        m = config_store.spanning_tree_mode
        if m == "rapid-pvst":
            mode = "rstp"
        elif m == "none":
            print("% Spanning-tree is disabled (spanning-tree mode none)")
            return

    print()
    print("VLAN0001")
    print(f"  Spanning tree enabled protocol {mode}")
    print(f"  Root ID    Address     {root_id}")
    print(f"  Bridge ID  Address     {bridge_id}")
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
    import re
    from backend.bridge import parse_interface_spec, eth_to_port_num

    if not tokens:
        print("% Incomplete command.")
        return

    spec = "".join(tokens)

    # Management0
    if spec.lower() in ("management0", "management"):
        mgmt = config_store.management
        lines = ["Building configuration...", "", "interface Management0"]
        if mgmt.description:
            lines.append(f" description {mgmt.description}")
        if mgmt.ip_address and mgmt.subnet_mask:
            lines.append(f" ip address {mgmt.ip_address} {mgmt.subnet_mask}")
        if mgmt.shutdown:
            lines.append(" shutdown")
        lines.append("end")
        print("\n".join(lines))
        return

    # SVI
    m = re.match(r'^[Vv][Ll][Aa][Nn]\s*(\d+)$', spec)
    if m:
        vlan_id = int(m.group(1))
        svi = config_store.get_svi(vlan_id)
        if not svi:
            print(f"% interface Vlan{vlan_id} not configured.")
            return
        lines = ["Building configuration...", "", f"interface Vlan{vlan_id}"]
        if svi.description:
            lines.append(f" description {svi.description}")
        if svi.ip_address and svi.subnet_mask:
            lines.append(f" ip address {svi.ip_address} {svi.subnet_mask}")
        lines.append(" no shutdown" if not svi.shutdown else " shutdown")
        lines.append("end")
        print("\n".join(lines))
        return

    # Interface fisica
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
    lines = ["Building configuration...", "", f"interface GigabitEthernet0/{port}"]
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
