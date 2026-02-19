"""
Operacoes VLAN no kernel Linux via bridge command.
Traduz comandos Cisco switchport para operacoes Linux bridge vlan.
"""

import json
import subprocess


def set_access_vlan(eth_name, vlan_id):
    """
    Cisco: switchport access vlan 10
    Linux: bridge vlan add dev eth1 vid 10 pvid untagged

    pvid     = frames untagged que chegam recebem tag deste VID (ingress)
    untagged = frames deste VID saem sem tag (egress)
    """
    _clear_port_vlans(eth_name)
    subprocess.run(
        ["bridge", "vlan", "add", "dev", eth_name,
         "vid", str(vlan_id), "pvid", "untagged"],
        check=True,
    )


def set_trunk_allowed_vlans(eth_name, vlan_list, native_vlan=None):
    """
    Cisco: switchport trunk allowed vlan 10,20,30
           switchport trunk native vlan 10
    Linux: bridge vlan add dev eth2 vid 10 pvid untagged  (native)
           bridge vlan add dev eth2 vid 20                 (tagged)
           bridge vlan add dev eth2 vid 30                 (tagged)
    """
    _clear_port_vlans(eth_name)
    for vid in vlan_list:
        cmd = ["bridge", "vlan", "add", "dev", eth_name, "vid", str(vid)]
        if native_vlan and vid == native_vlan:
            cmd.extend(["pvid", "untagged"])
        subprocess.run(cmd, check=True)


def remove_access_vlan(eth_name):
    """
    Cisco: no switchport access vlan
    Linux: remove todas as VLANs da porta
    """
    _clear_port_vlans(eth_name)


def get_port_vlans(eth_name):
    """Retorna lista de {vlan: id, flags: [...]} para uma porta."""
    result = subprocess.run(
        ["bridge", "-j", "vlan", "show", "dev", eth_name],
        capture_output=True, text=True,
    )
    try:
        data = json.loads(result.stdout)
        for entry in data:
            if entry.get("ifname") == eth_name:
                return entry.get("vlans", [])
    except (json.JSONDecodeError, KeyError):
        pass
    return []


def get_all_vlans():
    """Retorna dados completos de bridge vlan show em JSON."""
    result = subprocess.run(
        ["bridge", "-j", "-p", "vlan", "show"],
        capture_output=True, text=True,
    )
    try:
        return json.loads(result.stdout)
    except json.JSONDecodeError:
        return []


def _clear_port_vlans(eth_name):
    """Remove todas as VLANs de uma porta."""
    result = subprocess.run(
        ["bridge", "-j", "vlan", "show", "dev", eth_name],
        capture_output=True, text=True,
    )
    try:
        data = json.loads(result.stdout)
        for entry in data:
            for vlan_info in entry.get("vlans", []):
                vid = vlan_info["vlan"]
                subprocess.run(
                    ["bridge", "vlan", "del", "dev", eth_name,
                     "vid", str(vid)],
                    check=False,
                )
    except (json.JSONDecodeError, KeyError):
        pass
