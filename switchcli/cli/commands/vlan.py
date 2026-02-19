"""
Comandos de configuracao VLAN: name.
Remocao de VLAN (no vlan X) e tratada no engine.
"""


def cmd_vlan_name(config_store, vlan_id, args):
    """name <vlan-name>"""
    if not args:
        print("% Incomplete command.")
        return
    name = args[0]
    config_store.vlans[vlan_id] = name
