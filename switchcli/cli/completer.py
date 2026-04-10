"""
Tab completion e help (?) estilo Cisco IOS.
"""

from prompt_toolkit.completion import Completer, Completion

_SHOW_TREE = {
    "vlan": {"brief": "VLANs in brief"},
    "mac": {"address-table": "MAC address table"},
    "interfaces": {
        "status": "Interface status",
        "trunk": "Trunk interfaces",
        "Gi0/1": "Interface detail", "Gi0/2": "Interface detail",
        "Gi0/3": "Interface detail", "Gi0/4": "Interface detail",
        "Gi0/5": "Interface detail", "Gi0/6": "Interface detail",
        "Gi0/7": "Interface detail", "Gi0/8": "Interface detail",
        "Management0": "Management interface detail",
    },
    "ip": {
        "interface": {"brief": "IP Interface status and configuration (brief)"},
        "route": "IP routing table",
    },
    "interface": "Show interface Vlan<id> or Management0 details",
    "arp": "ARP table",
    "running-config": {
        "interface": "Show specific interface config",
        "<cr>": "Show full running config",
    },
    "startup-config": "Startup configuration",
    "spanning-tree": "Spanning tree information",
    "version": "System hardware and software status",
    "logging": "System logs",
    "lldp": {
        "<cr>": "Show global LLDP status",
        "neighbors": {
            "<cr>": "LLDP neighbors brief",
            "detail": "Detailed LLDP neighbor information",
        },
        "interface": "LLDP interface information",
    },
}

_DO_TREE = {
    "show": _SHOW_TREE,
    "ping": "Send echo messages",
    "write": {"memory": "Write to NV memory"},
}

COMMAND_TREE = {
    "USER_EXEC": {
        "enable": "Turn on privileged commands",
        "show": _SHOW_TREE,
        "exit": "Exit from the EXEC",
    },
    "PRIVILEGED_EXEC": {
        "configure": {"terminal": "Configure from the terminal"},
        "show": _SHOW_TREE,
        "ping": "Send echo messages",
        "write": {
            "memory": "Write to NV memory",
            "erase": "Erase startup configuration",
        },
        "copy": {"running-config": {"startup-config": "Copy running config to startup"}},
        "erase": {"startup-config": "Erase startup configuration"},
        "clear": {"mac": {"address-table": {"dynamic": "Clear dynamic MAC entries"}}},
        "disable": "Turn off privileged commands",
        "reload": "Halt and perform a cold restart",
        "exit": "Exit from the EXEC",
    },
    "GLOBAL_CONFIG": {
        "hostname": "Set system's network name",
        "enable": {"password": "Assign the privileged level password"},
        "vlan": "VLAN commands",
        "spanning-tree": {
            "mode": {
                "pvst": "Per-VLAN spanning tree",
                "rapid-pvst": "Per-VLAN rapid spanning tree",
                "none": "Disable spanning tree",
            },
        },
        "ip": {
            "default-gateway": "Specify default gateway (if not routing IP)",
            "route": "Add a static route",
        },
        "no": {
            "vlan": "Remove a VLAN",
            "ip": {
                "default-gateway": "Remove default gateway",
                "route": "Remove a static route",
            },
            "interface": "Remove a logical interface (e.g. Vlan1)",
            "spanning-tree": "Re-enable spanning tree",
            "banner": {"motd": "Remove MOTD banner"},
            "lldp": {"run": "Disable LLDP"},
            "errdisable": {"recovery": {"cause": "Remove errdisable recovery cause"}},
        },
        "interface": "Select an interface to configure",
        "banner": {"motd": "Set message-of-the-day banner"},
        "lldp": {
            "run": "Enable LLDP globally",
            "timer": "Set LLDP transmission interval (default 30s)",
            "holdtime": "Set LLDP holdtime (default 120s)",
            "reinit": "Set LLDP reinit delay (default 2s)",
        },
        "errdisable": {
            "recovery": {
                "cause": "Errdisable recovery cause",
                "interval": "Errdisable recovery interval (seconds)",
            },
        },
        "do": _DO_TREE,
        "end": "Exit from configure mode",
        "exit": "Exit from configure mode",
    },
    "INTERFACE_CONFIG": {
        "switchport": {
            "mode": {"access": "Set trunking mode ACCESS", "trunk": "Set trunking mode TRUNK"},
            "access": {"vlan": "Set VLAN when interface is in access mode"},
            "trunk": {
                "allowed": {
                    "vlan": {
                        "add": "Add VLANs to allowed list",
                        "remove": "Remove VLANs from allowed list",
                        "except": "Allow all VLANs except listed",
                        "none": "Allow no VLANs",
                        "all": "Allow all VLANs",
                    },
                },
                "native": {"vlan": "Set trunking native VLAN"},
            },
        },
        "no": {
            "switchport": {"access": {"vlan": "Remove access VLAN"}},
            "shutdown": "Bring the interface up",
            "lldp": {
                "transmit": "Disable LLDP transmission on this interface",
                "receive": "Disable LLDP reception on this interface",
            },
        },
        "lldp": {
            "transmit": "Enable LLDP transmission on this interface",
            "receive": "Enable LLDP reception on this interface",
        },
        "shutdown": "Shutdown the selected interface",
        "description": "Interface specific description",
        "speed": {
            "auto": "Autonegotiate",
            "10": "10 Mbps",
            "100": "100 Mbps",
            "1000": "1 Gbps",
        },
        "duplex": {
            "auto": "Autonegotiate",
            "full": "Full-duplex",
            "half": "Half-duplex",
        },
        "do": _DO_TREE,
        "end": "Exit from configure mode",
        "exit": "Exit from interface configuration mode",
    },
    "INTERFACE_CONFIG_SVI": {
        "ip": {"address": "Set the IP address of an interface"},
        "no": {
            "ip": {"address": "Remove IP address"},
            "shutdown": "Bring the interface up",
        },
        "shutdown": "Shutdown the selected interface",
        "description": "Interface specific description",
        "do": _DO_TREE,
        "end": "Exit from configure mode",
        "exit": "Exit from interface configuration mode",
    },
    "INTERFACE_CONFIG_MGMT": {
        "ip": {
            "address": {
                "dhcp": "Obtain IP via DHCP",
            },
        },
        "no": {
            "ip": {"address": "Remove IP address"},
            "shutdown": "Bring Management0 up",
        },
        "shutdown": "Shutdown Management0",
        "description": "Interface description",
        "do": _DO_TREE,
        "end": "Exit from configure mode",
        "exit": "Exit from interface configuration mode",
    },
    "VLAN_CONFIG": {
        "name": "ASCII name of the VLAN",
        "do": _DO_TREE,
        "exit": "Apply changes, bump revision number, and exit",
    },
}


class CiscoCompleter(Completer):
    def __init__(self, engine):
        self.engine = engine

    def _get_tree(self):
        mode = self.engine.mode
        if mode == "INTERFACE_CONFIG":
            if self.engine.current_management:
                return COMMAND_TREE.get("INTERFACE_CONFIG_MGMT", {})
            if self.engine.current_svi is not None:
                return COMMAND_TREE.get("INTERFACE_CONFIG_SVI", {})
        return COMMAND_TREE.get(mode, {})

    def get_completions(self, document, complete_event):
        text = document.text_before_cursor
        words = text.split()
        tree = self._get_tree()

        partial = ""
        if text and not text.endswith(" "):
            partial = words[-1] if words else ""
            words = words[:-1]

        for word in words:
            if isinstance(tree, dict):
                lower = word.lower()
                matched = next((k for k in tree if k.lower() == lower or k.lower().startswith(lower)), None)
                if matched and isinstance(tree[matched], dict):
                    tree = tree[matched]
                else:
                    return
            else:
                return

        if not isinstance(tree, dict):
            return

        for key, value in tree.items():
            if key.lower().startswith(partial.lower()):
                desc = value if isinstance(value, str) else ""
                yield Completion(key, start_position=-len(partial), display_meta=desc)


def get_help_text(mode, words, current_svi=None, current_management=False):
    if mode == "INTERFACE_CONFIG":
        if current_management:
            tree = COMMAND_TREE.get("INTERFACE_CONFIG_MGMT", {})
        elif current_svi is not None:
            tree = COMMAND_TREE.get("INTERFACE_CONFIG_SVI", {})
        else:
            tree = COMMAND_TREE.get(mode, {})
    else:
        tree = COMMAND_TREE.get(mode, {})

    for word in words:
        if isinstance(tree, dict):
            lower = word.lower()
            matched = next((k for k in tree if k.lower() == lower or k.lower().startswith(lower)), None)
            if matched:
                tree = tree[matched]
            else:
                return "% Unrecognized command"
        else:
            return "  <cr>"

    if isinstance(tree, dict):
        lines = [f"  {k:<24}{v if isinstance(v, str) else ''}" for k, v in sorted(tree.items())]
        lines.append(f"  {'<cr>':<24}")
        return "\n".join(lines)
    elif isinstance(tree, str):
        return f"  {tree}\n  <cr>"
    return "  <cr>"
