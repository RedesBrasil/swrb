"""
Operacoes em interfaces de rede Linux.
shutdown/no shutdown, leitura de estado, speed, etc.
"""

import subprocess
import os


def set_interface_shutdown(eth_name, shutdown=True):
    """
    Cisco: shutdown / no shutdown
    Linux: ip link set eth1 down / ip link set eth1 up
    """
    state = "down" if shutdown else "up"
    subprocess.run(["ip", "link", "set", eth_name, state], check=True)


def get_interface_state(eth_name):
    """Retorna 'up', 'down' ou 'unknown'."""
    path = f"/sys/class/net/{eth_name}/operstate"
    try:
        with open(path) as f:
            return f.read().strip()
    except (FileNotFoundError, PermissionError):
        return "unknown"


def get_interface_speed(eth_name):
    """Retorna speed em Mbps ou 'auto'."""
    path = f"/sys/class/net/{eth_name}/speed"
    try:
        with open(path) as f:
            return f.read().strip()
    except (FileNotFoundError, PermissionError, OSError):
        return "auto"


def get_interface_mtu(eth_name):
    """Retorna MTU."""
    path = f"/sys/class/net/{eth_name}/mtu"
    try:
        with open(path) as f:
            return int(f.read().strip())
    except (FileNotFoundError, PermissionError, ValueError):
        return 1500


def get_interface_mac(eth_name):
    """Retorna MAC address."""
    path = f"/sys/class/net/{eth_name}/address"
    try:
        with open(path) as f:
            return f.read().strip()
    except (FileNotFoundError, PermissionError):
        return "0000.0000.0000"


def interface_exists(eth_name):
    """Verifica se a interface existe no sistema."""
    return os.path.exists(f"/sys/class/net/{eth_name}")
