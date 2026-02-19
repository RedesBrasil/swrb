"""
Comandos de configuracao global: hostname, enable password.
"""

import subprocess


def cmd_hostname(config_store, args):
    """hostname <name>"""
    if not args:
        print("% Incomplete command.")
        return
    name = args[0]
    config_store.hostname = name
    # Aplicar no sistema
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
