"""
Maquina de estados do CLI Cisco-like.
Modos: USER_EXEC, PRIVILEGED_EXEC, GLOBAL_CONFIG, INTERFACE_CONFIG, VLAN_CONFIG
"""

import getpass
import sys

from prompt_toolkit import PromptSession
from prompt_toolkit.history import FileHistory
from prompt_toolkit.key_binding import KeyBindings

from backend.config_store import ConfigStore
from backend.bridge import (
    cisco_to_linux, normalize_interface_name, parse_interface_range,
    parse_interface_spec,
)
from cli.parser import match_command, AmbiguousCommand, InvalidCommand
from cli.completer import CiscoCompleter, get_help_text
from cli.commands.show import (
    show_vlan_brief, show_mac_address_table, show_interfaces_status,
    show_interfaces_trunk, show_running_config, show_startup_config,
    show_spanning_tree, show_version,
)
from cli.commands.config import cmd_hostname, cmd_enable_password
from cli.commands.interface import (
    cmd_switchport_mode, cmd_switchport_access_vlan,
    cmd_switchport_trunk_allowed_vlan, cmd_switchport_trunk_native_vlan,
    cmd_no_switchport_access_vlan, cmd_shutdown, cmd_description,
)
from cli.commands.vlan import cmd_vlan_name
from cli.commands.system import cmd_write_memory, cmd_reload


class CLIEngine:
    def __init__(self):
        self.config_store = ConfigStore()
        self.config_store.load_startup()
        self.mode = "USER_EXEC"
        self.current_interfaces = []  # lista de ethX em modo interface config
        self.current_vlan = None
        self._setup_keybindings()
        self.session = PromptSession(
            history=FileHistory("/tmp/.switch_history"),
            completer=CiscoCompleter(self),
            key_bindings=self.kb,
        )

    @property
    def hostname(self):
        return self.config_store.hostname

    def _setup_keybindings(self):
        """Configura keybindings para interceptar '?' para help contextual."""
        self.kb = KeyBindings()

        @self.kb.add("?")
        def _(event):
            buf = event.app.current_buffer
            text = buf.text
            words = text.split() if text else []
            help_text = get_help_text(self.mode, words)
            print(f"\n{self.get_prompt()}{text}?")
            print(help_text)
            # Nao consome o '?' no buffer -- re-mostra o prompt com texto atual
            buf.reset()
            buf.insert_text(text)

    def get_prompt(self):
        prompts = {
            "USER_EXEC":        f"{self.hostname}>",
            "PRIVILEGED_EXEC":  f"{self.hostname}#",
            "GLOBAL_CONFIG":    f"{self.hostname}(config)#",
            "INTERFACE_CONFIG": f"{self.hostname}(config-if)#",
            "VLAN_CONFIG":      f"{self.hostname}(config-vlan)#",
        }
        return prompts.get(self.mode, f"{self.hostname}>")

    def run(self):
        while True:
            try:
                user_input = self.session.prompt(self.get_prompt())
                user_input = user_input.strip()
                if not user_input:
                    continue
                self.dispatch(user_input)
            except KeyboardInterrupt:
                print("^C")
                continue
            except EOFError:
                break

    def dispatch(self, line):
        """Dispatcha o comando para o handler apropriado baseado no modo."""
        tokens = line.split()
        if not tokens:
            return

        try:
            if self.mode == "USER_EXEC":
                self._dispatch_user_exec(tokens)
            elif self.mode == "PRIVILEGED_EXEC":
                self._dispatch_privileged_exec(tokens)
            elif self.mode == "GLOBAL_CONFIG":
                self._dispatch_global_config(tokens)
            elif self.mode == "INTERFACE_CONFIG":
                self._dispatch_interface_config(tokens)
            elif self.mode == "VLAN_CONFIG":
                self._dispatch_vlan_config(tokens)
        except AmbiguousCommand as e:
            print(str(e))
        except InvalidCommand:
            print(f"% Invalid input detected at '^' marker.")

    # -------------------------------------------------------
    # USER EXEC
    # -------------------------------------------------------
    def _dispatch_user_exec(self, tokens):
        cmd = match_command(tokens[0], [
            "enable", "show", "exit",
        ])

        if cmd == "enable":
            if self.config_store.enable_password:
                try:
                    pw = getpass.getpass("Password: ")
                except (EOFError, KeyboardInterrupt):
                    print()
                    return
                if pw != self.config_store.enable_password:
                    print("% Access denied")
                    return
            self.mode = "PRIVILEGED_EXEC"

        elif cmd == "show":
            self._handle_show(tokens[1:])

        elif cmd == "exit":
            pass

    # -------------------------------------------------------
    # PRIVILEGED EXEC
    # -------------------------------------------------------
    def _dispatch_privileged_exec(self, tokens):
        cmd = match_command(tokens[0], [
            "configure", "show", "write", "copy",
            "disable", "reload", "exit",
        ])

        if cmd == "configure":
            if len(tokens) < 2:
                print("% Incomplete command.")
                return
            sub = match_command(tokens[1], ["terminal"])
            if sub == "terminal":
                self.mode = "GLOBAL_CONFIG"

        elif cmd == "show":
            self._handle_show(tokens[1:])

        elif cmd == "write":
            if len(tokens) >= 2:
                sub = match_command(tokens[1], ["memory"])
                if sub == "memory":
                    cmd_write_memory(self.config_store)
            else:
                # 'wr' sozinho = write memory (comportamento Cisco)
                cmd_write_memory(self.config_store)

        elif cmd == "copy":
            if len(tokens) >= 3:
                src = match_command(tokens[1], ["running-config"])
                dst = match_command(tokens[2], ["startup-config"])
                if src == "running-config" and dst == "startup-config":
                    cmd_write_memory(self.config_store)
            else:
                print("% Incomplete command.")

        elif cmd == "disable":
            self.mode = "USER_EXEC"

        elif cmd == "reload":
            cmd_reload()

        elif cmd == "exit":
            self.mode = "USER_EXEC"

    # -------------------------------------------------------
    # GLOBAL CONFIG
    # -------------------------------------------------------
    def _dispatch_global_config(self, tokens):
        cmd = match_command(tokens[0], [
            "hostname", "enable", "vlan", "no",
            "interface", "end", "exit",
        ])

        if cmd == "hostname":
            cmd_hostname(self.config_store, tokens[1:])

        elif cmd == "enable":
            if len(tokens) < 3:
                print("% Incomplete command.")
                return
            sub = match_command(tokens[1], ["password"])
            if sub == "password":
                cmd_enable_password(self.config_store, tokens[2:])

        elif cmd == "vlan":
            if len(tokens) < 2:
                print("% Incomplete command.")
                return
            try:
                vlan_id = int(tokens[1])
            except ValueError:
                print("% Invalid VLAN ID.")
                return
            if vlan_id < 1 or vlan_id > 4094:
                print("% Bad VLAN list.")
                return
            self.config_store.register_vlan(vlan_id)
            self.current_vlan = vlan_id
            self.mode = "VLAN_CONFIG"

        elif cmd == "no":
            self._handle_no_global(tokens[1:])

        elif cmd == "interface":
            self._handle_interface_select(tokens[1:])

        elif cmd in ("end", "exit"):
            self.mode = "PRIVILEGED_EXEC"

    def _handle_no_global(self, tokens):
        """Handle 'no' prefix commands in global config."""
        if not tokens:
            print("% Incomplete command.")
            return
        cmd = match_command(tokens[0], ["vlan"])
        if cmd == "vlan":
            if len(tokens) < 2:
                print("% Incomplete command.")
                return
            try:
                vlan_id = int(tokens[1])
            except ValueError:
                print("% Invalid VLAN ID.")
                return
            if not self.config_store.remove_vlan(vlan_id):
                print("% Default VLAN 1 may not be deleted.")

    def _handle_interface_select(self, tokens):
        """Parse interface ou interface range e entrar no modo INTERFACE_CONFIG."""
        if not tokens:
            print("% Incomplete command.")
            return

        # Juntar tokens para lidar com "GigabitEthernet 0/1" (com espaco)
        spec = " ".join(tokens)

        # Checar se e 'range'
        lower_first = tokens[0].lower()
        if lower_first == "range":
            if len(tokens) < 2:
                print("% Incomplete command.")
                return
            range_spec = tokens[1]
            eths = parse_interface_range(range_spec)
            if not eths:
                print("% Invalid interface range.")
                return
            self.current_interfaces = eths
            self.mode = "INTERFACE_CONFIG"
            return

        # Interface unica: "GigabitEthernet0/1" ou "Gi0/1"
        # Tentar juntar tudo num unico token sem espacos
        combined = "".join(tokens)
        eths = parse_interface_spec(combined)
        if eths:
            self.current_interfaces = eths
            self.mode = "INTERFACE_CONFIG"
            return

        print(f"% Invalid interface: {spec}")

    # -------------------------------------------------------
    # INTERFACE CONFIG
    # -------------------------------------------------------
    def _dispatch_interface_config(self, tokens):
        cmd = match_command(tokens[0], [
            "switchport", "no", "shutdown", "description",
            "end", "exit",
        ])

        if cmd == "switchport":
            self._handle_switchport(tokens[1:])

        elif cmd == "no":
            self._handle_no_interface(tokens[1:])

        elif cmd == "shutdown":
            cmd_shutdown(self.config_store, self.current_interfaces,
                         negate=False)

        elif cmd == "description":
            cmd_description(self.config_store, self.current_interfaces,
                            tokens[1:])

        elif cmd == "end":
            self.current_interfaces = []
            self.mode = "PRIVILEGED_EXEC"

        elif cmd == "exit":
            self.current_interfaces = []
            self.mode = "GLOBAL_CONFIG"

    def _handle_switchport(self, tokens):
        """Handle switchport sub-commands."""
        if not tokens:
            print("% Incomplete command.")
            return

        sub = match_command(tokens[0], ["mode", "access", "trunk"])

        if sub == "mode":
            cmd_switchport_mode(self.config_store,
                                self.current_interfaces, tokens[1:])

        elif sub == "access":
            if len(tokens) < 2:
                print("% Incomplete command.")
                return
            sub2 = match_command(tokens[1], ["vlan"])
            if sub2 == "vlan":
                cmd_switchport_access_vlan(
                    self.config_store, self.current_interfaces, tokens[2:])

        elif sub == "trunk":
            if len(tokens) < 2:
                print("% Incomplete command.")
                return
            sub2 = match_command(tokens[1], ["allowed", "native"])

            if sub2 == "allowed":
                if len(tokens) < 3:
                    print("% Incomplete command.")
                    return
                sub3 = match_command(tokens[2], ["vlan"])
                if sub3 == "vlan":
                    cmd_switchport_trunk_allowed_vlan(
                        self.config_store, self.current_interfaces,
                        tokens[3:])

            elif sub2 == "native":
                if len(tokens) < 3:
                    print("% Incomplete command.")
                    return
                sub3 = match_command(tokens[2], ["vlan"])
                if sub3 == "vlan":
                    cmd_switchport_trunk_native_vlan(
                        self.config_store, self.current_interfaces,
                        tokens[3:])

    def _handle_no_interface(self, tokens):
        """Handle 'no' prefix commands in interface config."""
        if not tokens:
            print("% Incomplete command.")
            return

        cmd = match_command(tokens[0], ["switchport", "shutdown"])

        if cmd == "switchport":
            if len(tokens) >= 2:
                sub = match_command(tokens[1], ["access"])
                if sub == "access":
                    if len(tokens) >= 3:
                        sub2 = match_command(tokens[2], ["vlan"])
                        if sub2 == "vlan":
                            cmd_no_switchport_access_vlan(
                                self.config_store, self.current_interfaces)
                    else:
                        print("% Incomplete command.")
            else:
                print("% Incomplete command.")

        elif cmd == "shutdown":
            cmd_shutdown(self.config_store, self.current_interfaces,
                         negate=True)

    # -------------------------------------------------------
    # VLAN CONFIG
    # -------------------------------------------------------
    def _dispatch_vlan_config(self, tokens):
        cmd = match_command(tokens[0], ["name", "exit"])

        if cmd == "name":
            cmd_vlan_name(self.config_store, self.current_vlan, tokens[1:])

        elif cmd == "exit":
            self.current_vlan = None
            self.mode = "GLOBAL_CONFIG"

    # -------------------------------------------------------
    # SHOW COMMANDS
    # -------------------------------------------------------
    def _handle_show(self, tokens):
        """Dispatcha show commands."""
        if not tokens:
            print("% Incomplete command.")
            return

        cmd = match_command(tokens[0], [
            "vlan", "mac", "interfaces", "running-config",
            "startup-config", "spanning-tree", "version",
        ])

        if cmd == "vlan":
            # 'show vlan' ou 'show vlan brief'
            show_vlan_brief(self.config_store)

        elif cmd == "mac":
            if len(tokens) >= 2:
                match_command(tokens[1], ["address-table"])
            show_mac_address_table()

        elif cmd == "interfaces":
            if len(tokens) < 2:
                show_interfaces_status(self.config_store)
                return
            sub = match_command(tokens[1], ["status", "trunk"])
            if sub == "status":
                show_interfaces_status(self.config_store)
            elif sub == "trunk":
                show_interfaces_trunk(self.config_store)

        elif cmd == "running-config":
            show_running_config(self.config_store)

        elif cmd == "startup-config":
            show_startup_config()

        elif cmd == "spanning-tree":
            show_spanning_tree()

        elif cmd == "version":
            show_version()
