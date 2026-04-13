"""Banner de boot estilo Cisco 2960."""

import os


def format_uptime(seconds):
    days = seconds // 86400
    hours = (seconds % 86400) // 3600
    minutes = (seconds % 3600) // 60
    secs = seconds % 60
    parts = []
    if days > 0:
        parts.append(f"{days} day{'s' if days != 1 else ''}"  )
    if hours > 0:
        parts.append(f"{hours} hour{'s' if hours != 1 else ''}"  )
    parts.append(f"{minutes} minute{'s' if minutes != 1 else ''}"  )
    parts.append(f"{secs} second{'s' if secs != 1 else ''}"  )
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
    pass
