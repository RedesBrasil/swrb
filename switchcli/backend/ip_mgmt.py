"""
Operacoes Linux para SVI (Switch Virtual Interface), default-gateway
e interface de gerencia Management0 (eth0).
"""

import json
import os
import subprocess
import ipaddress


def _svi_name(vlan_id):
    return f"vlan{vlan_id}"


def mask_to_prefix(subnet_mask):
    try:
        return ipaddress.IPv4Network(f"0.0.0.0/{subnet_mask}").prefixlen
    except ValueError:
        return 24


def prefix_to_mask(prefix_len):
    return str(ipaddress.IPv4Network(f"0.0.0.0/{prefix_len}").netmask)


# ── SVI ────────────────────────────────────────────────────────────────────────

def create_svi(vlan_id):
    name = _svi_name(vlan_id)
    subprocess.run(
        ["bridge", "vlan", "add", "dev", "br0", "vid", str(vlan_id), "self"],
        check=False, capture_output=True,
    )
    if not os.path.exists(f"/sys/class/net/{name}"):
        subprocess.run(
            ["ip", "link", "add", "link", "br0", "name", name,
             "type", "vlan", "id", str(vlan_id)],
            check=False, capture_output=True,
        )


def delete_svi(vlan_id):
    name = _svi_name(vlan_id)
    subprocess.run(["ip", "link", "del", name], check=False, capture_output=True)


def set_svi_ip(vlan_id, ip_address, subnet_mask):
    name = _svi_name(vlan_id)
    create_svi(vlan_id)
    prefix = mask_to_prefix(subnet_mask)
    subprocess.run(["ip", "addr", "flush", "dev", name],
                   check=False, capture_output=True)
    subprocess.run(
        ["ip", "addr", "add", f"{ip_address}/{prefix}", "dev", name],
        check=False, capture_output=True,
    )


def remove_svi_ip(vlan_id):
    name = _svi_name(vlan_id)
    subprocess.run(["ip", "addr", "flush", "dev", name],
                   check=False, capture_output=True)


def set_svi_state(vlan_id, shutdown):
    name = _svi_name(vlan_id)
    if not os.path.exists(f"/sys/class/net/{name}"):
        create_svi(vlan_id)
    state = "down" if shutdown else "up"
    subprocess.run(["ip", "link", "set", name, state],
                   check=False, capture_output=True)


def get_svi_info(vlan_id):
    name = _svi_name(vlan_id)
    info = {"ip": None, "mask": None, "state": "down", "exists": False}
    if not os.path.exists(f"/sys/class/net/{name}"):
        return info
    info["exists"] = True
    try:
        with open(f"/sys/class/net/{name}/operstate") as f:
            info["state"] = f.read().strip()
    except (FileNotFoundError, PermissionError):
        pass
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


# ── Default Gateway ────────────────────────────────────────────────────────────

def set_default_gateway(gw_ip):
    subprocess.run(
        ["ip", "route", "replace", "default", "via", gw_ip],
        check=False, capture_output=True,
    )


def remove_default_gateway():
    subprocess.run(["ip", "route", "del", "default"],
                   check=False, capture_output=True)


# ── Management0 (eth0) ─────────────────────────────────────────────────────────

def get_mgmt_info():
    """Retorna dict com estado do Management0 (eth0)."""
    info = {"ip": None, "mask": None, "state": "down", "exists": True}
    try:
        with open("/sys/class/net/eth0/operstate") as f:
            info["state"] = f.read().strip()
    except (FileNotFoundError, PermissionError):
        pass
    result = subprocess.run(
        ["ip", "-j", "addr", "show", "dev", "eth0"],
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


def set_mgmt_ip(ip_address, subnet_mask):
    """Configura IP estatico no Management0 (eth0)."""
    prefix = mask_to_prefix(subnet_mask)
    subprocess.run(["ip", "addr", "flush", "dev", "eth0"],
                   check=False, capture_output=True)
    subprocess.run(
        ["ip", "addr", "add", f"{ip_address}/{prefix}", "dev", "eth0"],
        check=False, capture_output=True,
    )


def remove_mgmt_ip():
    """Remove todos os IPs do Management0 (eth0)."""
    subprocess.run(["ip", "addr", "flush", "dev", "eth0"],
                   check=False, capture_output=True)


def set_mgmt_state(shutdown):
    """Sobe ou derruba o Management0 (eth0)."""
    state = "down" if shutdown else "up"
    subprocess.run(["ip", "link", "set", "eth0", state],
                   check=False, capture_output=True)


def set_mgmt_dhcp():
    """Solicita IP via DHCP no eth0 usando udhcpc."""
    # Flush IP atual e garante interface up
    subprocess.run(["ip", "addr", "flush", "dev", "eth0"],
                   check=False, capture_output=True)
    subprocess.run(["ip", "link", "set", "eth0", "up"],
                   check=False, capture_output=True)
    # udhcpc disponivel no Alpine (busybox)
    # -n: sai se nao conseguir / -q: sai apos obter lease / -t 3: 3 tentativas
    result = subprocess.run(
        ["udhcpc", "-i", "eth0", "-n", "-q", "-t", "3", "-T", "3"],
        check=False, capture_output=True, text=True,
    )
    return result.returncode == 0


# ── Rotas estaticas ────────────────────────────────────────────────────────────

def add_static_route(network, subnet_mask, gateway):
    prefix = mask_to_prefix(subnet_mask)
    dest = f"{network}/{prefix}"
    subprocess.run(
        ["ip", "route", "replace", dest, "via", gateway],
        check=False, capture_output=True,
    )


def remove_static_route(network, subnet_mask):
    prefix = mask_to_prefix(subnet_mask)
    dest = f"{network}/{prefix}"
    subprocess.run(
        ["ip", "route", "del", dest],
        check=False, capture_output=True,
    )


# ── LLDP ──────────────────────────────────────────────────────────────────────

def _is_lldpd_installed():
    return subprocess.run(
        ["which", "lldpd"], capture_output=True, text=True,
    ).returncode == 0


def setup_lldp_bridge():
    """Libera recepcao de frames LLDP (01:80:C2:00:00:0E) nas interfaces
    bridgeadas sem encaminha-los entre portas — identico ao Cisco Catalyst.

    O bit 0x4000 do group_fwd_mask instrui o bridge a entregar esses frames
    ao stack de rede local (lldpd) em vez de descarta-los silenciosamente.
    Os frames continuam NAO sendo encaminhados entre portas.
    """
    try:
        with open("/sys/class/net/br0/bridge/group_fwd_mask", "w") as f:
            f.write("0x4000\n")
    except (FileNotFoundError, PermissionError, OSError):
        pass


def start_lldp(timer=30, holdtime=120, reinit=2):
    """Inicia lldpd com comportamento Cisco Catalyst 2960:
    - Aplica group_fwd_mask para receber LLDP nas portas bridgeadas
    - Escuta em eth1-eth8 (portas fisicas), ignora br0/vlans/eth0
    - Configura timers via lldpctl apos inicio
    """
    if not _is_lldpd_installed():
        return False, "lldpd not found — rebuild image with deploy.sh"
    setup_lldp_bridge()
    already_running = bool(
        subprocess.run(["pidof", "lldpd"], capture_output=True, text=True).stdout.strip()
    )
    if already_running:
        # Matar instancia existente para garantir start com parametros corretos
        subprocess.run(["killall", "lldpd"], check=False, capture_output=True)
        import time; time.sleep(1)
    # Garantir diretorio do socket (tmpfs e recriado a cada boot no Alpine)
    for d in ("/run/lldpd", "/var/run/lldpd"):
        try:
            os.makedirs(d, exist_ok=True)
        except OSError:
            pass

    # Iniciar lldpd em foreground por 1s para capturar erros, depois daemonizar
    result = subprocess.run(
        ["lldpd"],
        check=False, capture_output=True, text=True,
    )
    if result.returncode != 0:
        err = (result.stderr.strip() or result.stdout.strip() or "no output")
        return False, f"lldpd exit={result.returncode}: {err}"
    import time; time.sleep(2)
    # Desabilitar LLDP na eth0 (Management0 OOB) e loopback via lldpctl
    for iface in ("eth0", "lo"):
        subprocess.run(
            ["lldpctl", "configure", "ports", iface, "lldp", "status", "disabled"],
            check=False, capture_output=True,
        )
    # Aplica timers (tx-hold = holdtime / timer, arredondado)
    subprocess.run(
        ["lldpctl", "configure", "lldp", "tx-interval", str(timer)],
        check=False, capture_output=True,
    )
    hold_multiplier = max(1, holdtime // timer)
    subprocess.run(
        ["lldpctl", "configure", "lldp", "tx-hold", str(hold_multiplier)],
        check=False, capture_output=True,
    )
    return True, None


def stop_lldp():
    subprocess.run(["killall", "lldpd"], check=False, capture_output=True)
    return True


def is_lldp_running():
    pidof = subprocess.run(["pidof", "lldpd"], capture_output=True, text=True)
    return bool(pidof.stdout.strip())


def set_lldp_interface(eth, transmit=True, receive=True):
    """Configura lldp tx/rx por interface fisica via lldpctl."""
    if transmit and receive:
        status = "rx-and-tx"
    elif transmit:
        status = "tx-only"
    elif receive:
        status = "rx-only"
    else:
        status = "disabled"
    subprocess.run(
        ["lldpctl", "configure", "ports", eth, "lldp", "status", status],
        check=False, capture_output=True,
    )


def get_lldp_neighbors():
    """Retorna lista de vizinhos LLDP parseada do lldpcli JSON."""
    if not _is_lldpd_installed():
        return []
    result = subprocess.run(
        ["lldpcli", "-f", "json", "show", "neighbors"],
        check=False, capture_output=True, text=True,
    )
    if result.returncode != 0:
        return []
    try:
        data = json.loads(result.stdout)
    except json.JSONDecodeError:
        return []
    neighbors = []
    lldp = data.get("lldp", {})
    ifaces = lldp.get("interface", [])
    if isinstance(ifaces, dict):
        ifaces = [ifaces]
    for entry in ifaces:
        if isinstance(entry, dict):
            for key, val in entry.items():
                if isinstance(val, dict):
                    neighbors.append({"local_if": key, **val})
                    break
    return neighbors


def get_lldp_neighbors_detail():
    """Retorna saida detalhada do lldpcli (texto)."""
    if not _is_lldpd_installed():
        return ""
    result = subprocess.run(
        ["lldpcli", "show", "neighbors", "details"],
        check=False, capture_output=True, text=True,
    )
    return result.stdout if result.returncode == 0 else ""


# ── Duplex / Speed ────────────────────────────────────────────────────────────

def set_interface_speed_duplex(eth, speed, duplex):
    """Configura velocidade e duplex via ethtool. Silencioso se falhar (virtio)."""
    if speed == "auto" and duplex == "auto":
        subprocess.run(
            ["ethtool", "-s", eth, "autoneg", "on"],
            check=False, capture_output=True,
        )
        return
    cmd = ["ethtool", "-s", eth, "autoneg", "off"]
    if speed != "auto":
        cmd += ["speed", str(speed)]
    if duplex != "auto":
        cmd += ["duplex", duplex]
    subprocess.run(cmd, check=False, capture_output=True)
