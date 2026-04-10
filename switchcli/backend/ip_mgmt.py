"""
Operacoes Linux para SVI (Switch Virtual Interface) e default-gateway.
SVI = interface vlanX criada sobre br0, usada para gerencia IP do switch.
"""

import json
import os
import subprocess
import ipaddress


def _svi_name(vlan_id):
    return f"vlan{vlan_id}"


def mask_to_prefix(subnet_mask):
    """Converte 255.255.255.0 -> 24."""
    try:
        return ipaddress.IPv4Network(f"0.0.0.0/{subnet_mask}").prefixlen
    except ValueError:
        return 24


def prefix_to_mask(prefix_len):
    """Converte 24 -> 255.255.255.0."""
    return str(ipaddress.IPv4Network(f"0.0.0.0/{prefix_len}").netmask)


def create_svi(vlan_id):
    """Cria interface vlanX sobre br0 (se nao existir)."""
    name = _svi_name(vlan_id)
    # Habilitar a VLAN no bridge com flag 'self' (necessario para SVI)
    subprocess.run(
        ["bridge", "vlan", "add", "dev", "br0", "vid", str(vlan_id), "self"],
        check=False, capture_output=True,
    )
    # Criar a interface VLAN sobre o bridge se nao existir
    if not os.path.exists(f"/sys/class/net/{name}"):
        subprocess.run(
            ["ip", "link", "add", "link", "br0", "name", name,
             "type", "vlan", "id", str(vlan_id)],
            check=False, capture_output=True,
        )


def delete_svi(vlan_id):
    """Remove a interface SVI."""
    name = _svi_name(vlan_id)
    subprocess.run(["ip", "link", "del", name],
                   check=False, capture_output=True)


def set_svi_ip(vlan_id, ip_address, subnet_mask):
    """Configura IP na SVI. subnet_mask pode ser dotted (255.x.x.x) ou CIDR (/24)."""
    name = _svi_name(vlan_id)
    # Garantir que a interface existe
    create_svi(vlan_id)
    prefix = mask_to_prefix(subnet_mask)
    # Remover IPs anteriores
    subprocess.run(["ip", "addr", "flush", "dev", name],
                   check=False, capture_output=True)
    subprocess.run(
        ["ip", "addr", "add", f"{ip_address}/{prefix}", "dev", name],
        check=False, capture_output=True,
    )


def remove_svi_ip(vlan_id):
    """Remove todos os IPs da SVI."""
    name = _svi_name(vlan_id)
    subprocess.run(["ip", "addr", "flush", "dev", name],
                   check=False, capture_output=True)


def set_svi_state(vlan_id, shutdown):
    """Sobe ou derruba a SVI (shutdown=True = down)."""
    name = _svi_name(vlan_id)
    if not os.path.exists(f"/sys/class/net/{name}"):
        create_svi(vlan_id)
    state = "down" if shutdown else "up"
    subprocess.run(["ip", "link", "set", name, state],
                   check=False, capture_output=True)


def set_default_gateway(gw_ip):
    """Configura default gateway."""
    subprocess.run(
        ["ip", "route", "replace", "default", "via", gw_ip],
        check=False, capture_output=True,
    )


def remove_default_gateway():
    """Remove default gateway."""
    subprocess.run(["ip", "route", "del", "default"],
                   check=False, capture_output=True)


def get_svi_info(vlan_id):
    """Retorna dict com estado da SVI: ip, mask, state, exists."""
    name = _svi_name(vlan_id)
    info = {"ip": None, "mask": None, "state": "down", "exists": False}

    if not os.path.exists(f"/sys/class/net/{name}"):
        return info

    info["exists"] = True

    # Estado operacional
    try:
        with open(f"/sys/class/net/{name}/operstate") as f:
            info["state"] = f.read().strip()
    except (FileNotFoundError, PermissionError):
        pass

    # IP via 'ip -j addr show'
    result = subprocess.run(
        ["ip", "-j", "addr", "show", "dev", name],
        capture_output=True, text=True,
    )
    try:
        data = json.loads(result.stdout)
        if data:
            for addr_info in data[0].get("addr_info", []):
                if addr_info.get("family") == "inet":
                    info["ip"] = addr_info.get("local")
                    prefix = addr_info.get("prefixlen", 24)
                    info["mask"] = prefix_to_mask(prefix)
                    break
    except (json.JSONDecodeError, KeyError, IndexError):
        pass

    return info
