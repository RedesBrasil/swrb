"""
Comandos de sistema: write memory, copy run start, reload.
"""

import os
import subprocess


def cmd_write_memory(config_store):
    """write memory / copy running-config startup-config"""
    print("Building configuration...")
    try:
        config_store.save_startup()
        # Atualizar hostname no sistema
        try:
            with open("/etc/hostname", "w") as f:
                f.write(config_store.hostname + "\n")
        except PermissionError:
            pass
        print("[OK]")
    except Exception as e:
        print(f"% Error saving configuration: {e}")


def cmd_reload():
    """reload"""
    print("Proceed with reload? [confirm]", end="", flush=True)
    try:
        answer = input()
    except (EOFError, KeyboardInterrupt):
        print()
        return
    # Qualquer input (incluindo Enter vazio) confirma como no Cisco
    print()
    print("System configuration has been modified. Save? [yes/no]: ",
          end="", flush=True)
    try:
        save = input().strip().lower()
    except (EOFError, KeyboardInterrupt):
        print()
        return
    if save in ("y", "yes", ""):
        print("Building configuration...")
        print("[OK]")
    subprocess.run(["reboot"], check=False)
