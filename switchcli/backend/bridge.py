"""
Mapeamento bidirecional entre nomes Cisco e Linux.
GigabitEthernet0/1 <-> eth1
"""

import re

INTERFACE_MAP = {
    "GigabitEthernet0/0": "eth0",
    "GigabitEthernet0/1": "eth1",
    "GigabitEthernet0/2": "eth2",
    "GigabitEthernet0/3": "eth3",
    "GigabitEthernet0/4": "eth4",
    "GigabitEthernet0/5": "eth5",
    "GigabitEthernet0/6": "eth6",
    "GigabitEthernet0/7": "eth7",
    "GigabitEthernet0/8": "eth8",
}

REVERSE_MAP = {v: k for k, v in INTERFACE_MAP.items()}


def normalize_interface_name(name):
    """
    Normaliza abreviacoes de interface para nome completo.
    gi0/1, Gi0/1, gig0/1, gigabitethernet0/1 -> GigabitEthernet0/1
    """
    m = re.match(r'(?i)^gi(?:g(?:a(?:b(?:i(?:t(?:e(?:t(?:h(?:e(?:r(?:n(?:et?)?)?)?)?)?)?)?)?)?)?)?)?(\d+/\d+)$', name)
    if m:
        return f"GigabitEthernet{m.group(1)}"
    return name


def cisco_to_linux(cisco_name):
    """GigabitEthernet0/1 -> eth1. Aceita abreviacoes: Gi0/1, gi0/1"""
    normalized = normalize_interface_name(cisco_name)
    return INTERFACE_MAP.get(normalized)


def linux_to_cisco(linux_name):
    """eth1 -> Gi0/1"""
    full = REVERSE_MAP.get(linux_name, linux_name)
    return full.replace("GigabitEthernet", "Gi")


def linux_to_cisco_full(linux_name):
    """eth1 -> GigabitEthernet0/1"""
    return REVERSE_MAP.get(linux_name, linux_name)


def format_mac_cisco(mac):
    """aa:bb:cc:dd:ee:ff -> aabb.ccdd.eeff"""
    clean = mac.replace(":", "").replace("-", "").lower()
    if len(clean) != 12:
        return mac
    return f"{clean[0:4]}.{clean[4:8]}.{clean[8:12]}"


def parse_interface_spec(spec):
    """
    Parse interface specification.
    'GigabitEthernet0/1' -> ['eth1']
    'Gi0/1' -> ['eth1']
    """
    normalized = normalize_interface_name(spec)
    eth = INTERFACE_MAP.get(normalized)
    if eth:
        return [eth]
    return []


def parse_interface_range(range_str):
    """
    Parse 'GigabitEthernet0/1-4' -> ['eth1', 'eth2', 'eth3', 'eth4']
    Also accepts abbreviated forms: Gi0/1-4, gi0/1-4
    """
    m = re.match(
        r'(?i)^gi(?:g(?:a(?:b(?:i(?:t(?:e(?:t(?:h(?:e(?:r(?:n(?:et?)?)?)?)?)?)?)?)?)?)?)?)?(\d+)/(\d+)-(\d+)$',
        range_str
    )
    if m:
        start = int(m.group(2))
        end = int(m.group(3))
        if start <= end:
            return [f"eth{i}" for i in range(start, end + 1)]
    return []


def eth_to_port_num(eth_name):
    """eth1 -> 1"""
    m = re.match(r'eth(\d+)', eth_name)
    if m:
        return int(m.group(1))
    return None
