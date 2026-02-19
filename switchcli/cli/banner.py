"""Banner de boot estilo Cisco 2960."""

import os


def format_uptime(seconds):
    days = seconds // 86400
    hours = (seconds % 86400) // 3600
    minutes = (seconds % 3600) // 60
    secs = seconds % 60
    parts = []
    if days > 0:
        parts.append(f"{days} day{'s' if days != 1 else ''}")
    if hours > 0:
        parts.append(f"{hours} hour{'s' if hours != 1 else ''}")
    parts.append(f"{minutes} minute{'s' if minutes != 1 else ''}")
    parts.append(f"{secs} second{'s' if secs != 1 else ''}")
    return ", ".join(parts)


def get_base_mac():
    """Tenta ler MAC de eth0 ou br0 para o banner."""
    for dev in ("eth0", "br0"):
        path = f"/sys/class/net/{dev}/address"
        try:
            with open(path) as f:
                return f.read().strip().upper()
        except (FileNotFoundError, PermissionError):
            continue
    return "00:AA:BB:CC:DD:00"


def print_banner():
    hostname = "Switch"
    try:
        with open("/etc/hostname") as f:
            hostname = f.read().strip() or "Switch"
    except (FileNotFoundError, PermissionError):
        pass

    try:
        with open("/proc/uptime") as f:
            uptime_seconds = int(float(f.read().split()[0]))
    except (FileNotFoundError, PermissionError, ValueError):
        uptime_seconds = 0

    uptime_str = format_uptime(uptime_seconds)
    base_mac = get_base_mac()

    banner = f"""\
Cisco IOS Software, C2960 Software (C2960-LANBASEK9-M), Version 15.0(2)SE11
Technical Support: http://www.cisco.com/techsupport
Copyright (c) 1986-2024 by Cisco Systems, Inc.

ROM: Bootstrap program is C2960 boot loader
BOOTLDR: C2960 Boot Loader (C2960-HBOOT-M) Version 15.0(2r)SE11

{hostname} uptime is {uptime_str}
System returned to ROM by power-on
System image file is "flash:c2960-lanbasek9-mz.150-2.SE11.bin"

cisco WS-C2960-8TC-L (PowerPC405) processor with 65536K bytes of memory.
Processor board ID FCZ123456AB
Last reset from power-on
8 Ethernet interfaces
The password-recovery mechanism is enabled.

512K bytes of flash-simulated non-volatile configuration memory.
Base ethernet MAC Address       : {base_mac}
Motherboard assembly number     : 73-12351-01
Power supply part number        : 341-0097-03
Motherboard serial number       : FCZ123456AB
Model number                    : WS-C2960-8TC-L
System serial number            : FCZ123456AB
"""
    print(banner)
