"""
Comandos de sistema: write memory, write erase, reload, clear mac address-table,
spanning-tree mode.
"""

import os
import subprocess


CONFIG_PATH = "/opt/switchcli/configs/startup-config"


def cmd_write_memory(config_store):
    print("Building configuration...")
    try:
        config_store.save_startup()
        try:
            with open("/etc/hostname", "w") as f:
                f.write(config_store.hostname + "\n")
        except PermissionError:
            pass
        print("[OK]")
    except Exception as e:
        print(f"% Error saving configuration: {e}")


def cmd_write_erase(config_store):
    """write erase — apaga startup-config."""
    print("Erasing the nvram filesystem will remove all configuration files!")
    print("Continue? [confirm]", end="", flush=True)
    try:
        answer = input()
    except (EOFError, KeyboardInterrupt):
        print()
        return
    if answer.strip().lower() in ("", "y", "yes"):
        try:
            if os.path.exists(CONFIG_PATH):
                os.remove(CONFIG_PATH)
            print("Erase of nvram: complete")
        except Exception as e:
            print(f"% Error erasing nvram: {e}")
    else:
        print("Aborted.")


def cmd_erase_startup(config_store):
    """erase startup-config — alias de write erase."""
    cmd_write_erase(config_store)


def cmd_reload():
    """reload — reinicia o switch."""
    print("Proceed with reload? [confirm]", end="", flush=True)
    try:
        answer = input()
    except (EOFError, KeyboardInterrupt):
        print()
        return
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


def cmd_clear_mac_address_table():
    """clear mac address-table dynamic — limpa MACs aprendidos."""
    for i in range(1, 9):
        subprocess.run(
            ["bridge", "fdb", "flush", "dev", f"eth{i}", "dynamic"],
            check=False, capture_output=True,
        )
    subprocess.run(
        ["bridge", "fdb", "flush", "dev", "br0", "dynamic"],
        check=False, capture_output=True,
    )
    print("MAC address table cleared.")


def cmd_spanning_tree_mode(config_store, args):
    """spanning-tree mode pvst|rapid-pvst|none"""
    if not args:
        print("% Incomplete command.")
        return
    mode = args[0].lower()
    if mode == "none":
        subprocess.run(
            ["ip", "link", "set", "br0", "type", "bridge", "stp_state", "0"],
            check=False, capture_output=True,
        )
        config_store.spanning_tree_mode = "none"
        print("% Spanning-tree disabled.")
    elif mode in ("pvst", "rapid-pvst"):
        subprocess.run(
            ["ip", "link", "set", "br0", "type", "bridge", "stp_state", "1"],
            check=False, capture_output=True,
        )
        config_store.spanning_tree_mode = mode
    else:
        print("% Invalid spanning-tree mode. Use: pvst, rapid-pvst, none")
