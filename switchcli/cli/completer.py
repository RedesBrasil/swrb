"""
Tab completion e help (?) estilo Cisco IOS.
"""

from prompt_toolkit.completion import Completer, Completion

_SHOW_TREE = {
    "vlan": {"brief": "VLANs in brief"},
    "mac": {"address-table": "MAC address table"},
    "interfaces": {"status": "Interface status", "trunk": "Trunk interfaces"},
    "ip": {"interface": {"brief": "IP Interface status and configuration (brief)"}},
    "interface": "Show interface Vlan<id> details",
    "arp": "ARP table",
    "running-config": {
            "interface": "Show specific interface config",
            "<cr>": "Show full running config",
        },
    "startup-config": "Startup configuration",
    "spanning-tree": "Spanning tree information",
    "version": "System hardware and software status",
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
        "write": {"memory": "Write to NV memory"},
        "copy": {"running-config": {"startup-config": "Copy running config to startup"}},
        "disable": "Turn off privileged commands",
        "reload": "Halt and perform a cold restart",
        "exit": "Exit from the EXEC",
    },
    "GLOBAL_CONFIG": {
        "hostname": "Set system's network name",
        "enable": {"password": "Assign the privileged level password"},
        "vlan": "VLAN commands",
        "ip": {"default-gateway": "Specify default gateway (if not routing IP)"},
        "no": {
            "vlan": "Remove a VLAN",
            "ip": {"default-gateway": "Remove default gateway"},
            "interface": "Remove a logical interface (e.g. Vlan1)",
        },
        "interface": "Select an interface to configure",
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
        },
        "shutdown": "Shutdown the selected interface",
        "description": "Interface specific description",
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
        if mode == "INTERFACE_CONFIG" and self.engine.current_svi is not None:
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


def get_help_text(mode, words, current_svi=None):
    if mode == "INTERFACE_CONFIG" and current_svi is not None:
        tree = COMMAND_TREE.get("INTERFACE_CONFIG_SVI", {})
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
