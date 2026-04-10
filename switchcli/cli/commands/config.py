"""
Comandos de configuracao global: hostname, enable password, ip default-gateway.
"""

import ipaddress
import subprocess

from backend import ip_mgmt


def cmd_hostname(config_store, args):
    """hostname <name>"""
    if not args:
        print("% Incomplete command.")
        return
    name = args[0]
    config_store.hostname = name
    try:
        with open("/etc/hostname", "w") as f:
            f.write(name + "\n")
        subprocess.run(["hostname", name], check=False)
    except PermissionError:
        pass


def cmd_enable_password(config_store, args):
    """enable password <pw>"""
    if not args:
        print("% Incomplete command.")
        return
    config_store.enable_password = args[0]


def cmd_ip_default_gateway(config_store, args):
    """ip default-gateway <ip>"""
    if not args:
        print("% Incomplete command.")
        return
    gw = args[0]
    try:
        ipaddress.IPv4Address(gw)
    except ValueError:
        print("% Invalid IP address.")
        return

    config_store.default_gateway = gw
    try:
        ip_mgmt.set_default_gateway(gw)
    except Exception as e:
        print(f"% Error setting default-gateway: {e}")


def cmd_no_ip_default_gateway(config_store):
    """no ip default-gateway"""
    config_store.default_gateway = None
    try:
        ip_mgmt.remove_default_gateway()
    except Exception as e:
        print(f"% Error removing default-gateway: {e}")
