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


def _validate_ip(ip_str):
    try:
        ipaddress.IPv4Address(ip_str)
        return True
    except ValueError:
        return False


def _validate_mask(mask_str):
    try:
        ipaddress.IPv4Network(f"0.0.0.0/{mask_str}")
        return True
    except ValueError:
        return False


def cmd_ip_route(config_store, args):
    """ip route <network> <mask> <gateway>"""
    if len(args) < 3:
        print("% Incomplete command.")
        return
    network, mask, gateway = args[0], args[1], args[2]
    if not _validate_ip(network):
        print("% Invalid network address.")
        return
    if not _validate_mask(mask):
        print("% Invalid subnet mask.")
        return
    if not _validate_ip(gateway):
        print("% Invalid gateway address.")
        return
    config_store.add_static_route(network, mask, gateway)
    try:
        ip_mgmt.add_static_route(network, mask, gateway)
    except Exception as e:
        print(f"% Error adding route: {e}")


def cmd_no_ip_route(config_store, args):
    """no ip route <network> <mask> [gateway]"""
    if len(args) < 2:
        print("% Incomplete command.")
        return
    network, mask = args[0], args[1]
    if not _validate_ip(network) or not _validate_mask(mask):
        print("% Invalid network/mask.")
        return
    if not config_store.remove_static_route(network, mask):
        print("% Route not found.")
        return
    try:
        ip_mgmt.remove_static_route(network, mask)
    except Exception as e:
        print(f"% Error removing route: {e}")


def cmd_banner_motd(config_store, raw_line):
    """banner motd <delim><text><delim>

    Aceita forma single-line: banner motd #Welcome to switch#
    """
    raw = raw_line.strip()
    if len(raw) < 2:
        print("% Incomplete command.")
        return
    delim = raw[0]
    if raw.count(delim) < 2:
        print(f"% Expected closing delimiter '{delim}'.")
        return
    end = raw.rfind(delim)
    text = raw[1:end]
    config_store.banner_motd = text
    print(f"% Banner updated ({len(text)} chars)")


def cmd_no_banner_motd(config_store):
    config_store.banner_motd = None


def cmd_lldp_run(config_store):
    """lldp run — habilita LLDP globalmente."""
    ok, err = ip_mgmt.start_lldp(
        timer=config_store.lldp_timer,
        holdtime=config_store.lldp_holdtime,
        reinit=config_store.lldp_reinit,
    )
    if not ok:
        print(f"% Failed to enable LLDP: {err}")
        return
    config_store.lldp_enabled = True
    for port_num, iface in config_store.interfaces.items():
        eth = f"eth{port_num}"
        ip_mgmt.set_lldp_interface(eth, iface.lldp_transmit, iface.lldp_receive)
    print("% LLDP enabled")


def cmd_no_lldp_run(config_store):
    """no lldp run"""
    ip_mgmt.stop_lldp()
    config_store.lldp_enabled = False
    print("% LLDP disabled")


def cmd_lldp_timer(config_store, args):
    """lldp timer <seconds>  (5-65534, padrao 30)"""
    if not args:
        print("% Incomplete command.")
        return
    try:
        val = int(args[0])
    except ValueError:
        print("% Invalid value.")
        return
    if val < 5 or val > 65534:
        print("% Timer must be between 5 and 65534 seconds.")
        return
    config_store.lldp_timer = val
    if config_store.lldp_enabled:
        subprocess.run(
            ["lldpctl", "configure", "lldp", "tx-interval", str(val)],
            check=False, capture_output=True,
        )


def cmd_lldp_holdtime(config_store, args):
    """lldp holdtime <seconds>  (10-65535, padrao 120)"""
    if not args:
        print("% Incomplete command.")
        return
    try:
        val = int(args[0])
    except ValueError:
        print("% Invalid value.")
        return
    if val < 10 or val > 65535:
        print("% Holdtime must be between 10 and 65535 seconds.")
        return
    config_store.lldp_holdtime = val
    if config_store.lldp_enabled:
        multiplier = max(1, val // config_store.lldp_timer)
        subprocess.run(
            ["lldpctl", "configure", "lldp", "tx-hold", str(multiplier)],
            check=False, capture_output=True,
        )


def cmd_lldp_reinit(config_store, args):
    """lldp reinit <seconds>  (2-5, padrao 2)"""
    if not args:
        print("% Incomplete command.")
        return
    try:
        val = int(args[0])
    except ValueError:
        print("% Invalid value.")
        return
    if val < 2 or val > 5:
        print("% Reinit delay must be between 2 and 5 seconds.")
        return
    config_store.lldp_reinit = val


_VALID_ERRDISABLE_CAUSES = [
    "all", "bpduguard", "link-flap", "loopback",
    "psecure-violation", "security-violation", "udld",
]


def cmd_errdisable_recovery_cause(config_store, args):
    """errdisable recovery cause <cause>"""
    if not args:
        print("% Incomplete command.")
        return
    cause = args[0].lower()
    if cause not in _VALID_ERRDISABLE_CAUSES:
        print(f"% Invalid cause. Valid: {', '.join(_VALID_ERRDISABLE_CAUSES)}")
        return
    if cause not in config_store.errdisable_causes:
        config_store.errdisable_causes.append(cause)


def cmd_no_errdisable_recovery_cause(config_store, args):
    if not args:
        print("% Incomplete command.")
        return
    cause = args[0].lower()
    if cause in config_store.errdisable_causes:
        config_store.errdisable_causes.remove(cause)


def cmd_errdisable_recovery_interval(config_store, args):
    """errdisable recovery interval <seconds>"""
    if not args:
        print("% Incomplete command.")
        return
    try:
        interval = int(args[0])
    except ValueError:
        print("% Invalid interval.")
        return
    if interval < 30 or interval > 86400:
        print("% Interval must be between 30 and 86400 seconds.")
        return
    config_store.errdisable_interval = interval
