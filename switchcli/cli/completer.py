"""
Tab completion e help (?) estilo Cisco IOS.
Usa prompt_toolkit Completer.
"""

from prompt_toolkit.completion import Completer, Completion


# Arvore de comandos por modo
COMMAND_TREE = {
    "USER_EXEC": {
        "enable": "Turn on privileged commands",
        "show": {
            "vlan": {
                "brief": "VLANs in brief",
            },
            "mac": {
                "address-table": "MAC address table",
            },
            "interfaces": {
                "status": "Interface status",
                "trunk": "Trunk interfaces",
            },
            "running-config": "Current running configuration",
            "startup-config": "Startup configuration",
            "spanning-tree": "Spanning tree information",
            "version": "System hardware and software status",
        },
        "exit": "Exit from the EXEC",
    },
    "PRIVILEGED_EXEC": {
        "configure": {
            "terminal": "Configure from the terminal",
        },
        "show": {
            "vlan": {
                "brief": "VLANs in brief",
            },
            "mac": {
                "address-table": "MAC address table",
            },
            "interfaces": {
                "status": "Interface status",
                "trunk": "Trunk interfaces",
            },
            "running-config": "Current running configuration",
            "startup-config": "Startup configuration",
            "spanning-tree": "Spanning tree information",
            "version": "System hardware and software status",
        },
        "write": {
            "memory": "Write to NV memory",
        },
        "copy": {
            "running-config": {
                "startup-config": "Copy running config to startup",
            },
        },
        "disable": "Turn off privileged commands",
        "reload": "Halt and perform a cold restart",
        "exit": "Exit from the EXEC",
    },
    "GLOBAL_CONFIG": {
        "hostname": "Set system's network name",
        "enable": {
            "password": "Assign the privileged level password",
        },
        "vlan": "VLAN commands",
        "no": {
            "vlan": "Remove a VLAN",
        },
        "interface": "Select an interface to configure",
        "end": "Exit from configure mode",
        "exit": "Exit from configure mode",
    },
    "INTERFACE_CONFIG": {
        "switchport": {
            "mode": {
                "access": "Set trunking mode to ACCESS unconditionally",
                "trunk": "Set trunking mode to TRUNK unconditionally",
            },
            "access": {
                "vlan": "Set VLAN when interface is in access mode",
            },
            "trunk": {
                "allowed": {
                    "vlan": "Set allowed VLAN characteristics",
                },
                "native": {
                    "vlan": "Set trunking native VLAN",
                },
            },
        },
        "no": {
            "switchport": {
                "access": {
                    "vlan": "Remove access VLAN",
                },
            },
            "shutdown": "Bring the interface up",
        },
        "shutdown": "Shutdown the selected interface",
        "description": "Interface specific description",
        "end": "Exit from configure mode",
        "exit": "Exit from interface configuration mode",
    },
    "VLAN_CONFIG": {
        "name": "ASCII name of the VLAN",
        "exit": "Apply changes, bump revision number, and exit",
    },
}


class CiscoCompleter(Completer):
    def __init__(self, engine):
        self.engine = engine

    def get_completions(self, document, complete_event):
        text = document.text_before_cursor
        words = text.split()
        tree = COMMAND_TREE.get(self.engine.mode, {})

        # Navegar na arvore conforme as palavras ja digitadas
        # Para cada palavra completa, descer na arvore
        partial = ""
        if text and not text.endswith(" "):
            partial = words[-1] if words else ""
            words = words[:-1]

        for word in words:
            if isinstance(tree, dict):
                lower = word.lower()
                matched = None
                for key in tree:
                    if key.lower() == lower or key.lower().startswith(lower):
                        matched = key
                        break
                if matched and isinstance(tree[matched], dict):
                    tree = tree[matched]
                else:
                    return
            else:
                return

        if not isinstance(tree, dict):
            return

        # Completar a palavra parcial
        for key, value in tree.items():
            if key.lower().startswith(partial.lower()):
                desc = value if isinstance(value, str) else ""
                yield Completion(
                    key,
                    start_position=-len(partial),
                    display_meta=desc,
                )


def get_help_text(mode, words):
    """
    Retorna texto de help para '?' no contexto atual.
    words: lista de tokens ja digitados antes do '?'
    """
    tree = COMMAND_TREE.get(mode, {})

    for word in words:
        if isinstance(tree, dict):
            lower = word.lower()
            matched = None
            for key in tree:
                if key.lower() == lower or key.lower().startswith(lower):
                    matched = key
                    break
            if matched:
                tree = tree[matched]
            else:
                return "% Unrecognized command"
        else:
            return "  <cr>"

    if isinstance(tree, dict):
        lines = []
        for key, value in sorted(tree.items()):
            desc = value if isinstance(value, str) else ""
            lines.append(f"  {key:<24}{desc}")
        lines.append(f"  {'<cr>':<24}")
        return "\n".join(lines)
    elif isinstance(tree, str):
        return f"  {tree}\n  <cr>"
    else:
        return "  <cr>"
