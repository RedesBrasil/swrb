"""
Maquina de estados do CLI Cisco-like.
Modos: USER_EXEC, PRIVILEGED_EXEC, GLOBAL_CONFIG, INTERFACE_CONFIG, VLAN_CONFIG
"""

import getpass
import re
import subprocess
import sys

from prompt_toolkit import PromptSession
from prompt_toolkit.history import FileHistory
from prompt_toolkit.key_binding import KeyBindings

from backend.config_store import ConfigStore
from backend.bridge import (
    cisco_to_linux, normalize_interface_name, parse_interface_range,
    parse_interface_spec,
)
from backend import ip_mgmt
from cli.parser import match_command, AmbiguousCommand, InvalidCommand
from cli.completer import CiscoCompleter, get_help_text
from cli.commands.show import (
    show_vlan_brief, show_mac_address_table, show_interfaces_status,
    show_interfaces_trunk, show_interface_detail, show_interface_management,
    show_running_config, show_startup_config,
    show_spanning_tree, show_version, show_interface_vlan,
    show_ip_interface_brief, show_running_config_interface, show_arp,
    show_logging, show_lldp_neighbors, show_lldp_neighbors_detail,
    show_lldp_global, show_lldp_interface, show_ip_route,
)
from cli.commands.config import (
    cmd_hostname, cmd_enable_password,
    cmd_ip_default_gateway, cmd_no_ip_default_gateway,
    cmd_ip_route, cmd_no_ip_route,
    cmd_banner_motd, cmd_no_banner_motd,
    cmd_lldp_run, cmd_no_lldp_run,
    cmd_lldp_timer, cmd_lldp_holdtime, cmd_lldp_reinit,
    cmd_errdisable_recovery_cause, cmd_no_errdisable_recovery_cause,
    cmd_errdisable_recovery_interval,
)
from cli.commands.interface import (
    cmd_cleanup_vlan_from_ports,
    cmd_switchport_mode, cmd_switchport_access_vlan,
    cmd_switchport_trunk_allowed_vlan, cmd_switchport_trunk_native_vlan,
    cmd_no_switchport_access_vlan, cmd_shutdown, cmd_description,
    cmd_svi_ip_address, cmd_no_svi_ip_address,
    cmd_svi_shutdown, cmd_svi_description,
    cmd_mgmt_ip_address, cmd_no_mgmt_ip_address,
    cmd_mgmt_shutdown, cmd_mgmt_description,
    cmd_interface_speed, cmd_interface_duplex,
    cmd_lldp_transmit, cmd_lldp_receive,
)
from cli.commands.vlan import cmd_vlan_name
from cli.commands.system import (
    cmd_write_memory, cmd_write_erase, cmd_erase_startup,
    cmd_reload, cmd_clear_mac_address_table, cmd_spanning_tree_mode,
)

_RE_VLAN_IFACE = re.compile(r'^[Vv][Ll][Aa][Nn]\s*(\d+)$')
_RE_MGMT_IFACE = re.compile(r'^[Mm]anagement\s*0?$', re.IGNORECASE)
_RE_GI_IFACE   = re.compile(r'^[Gg]i.*|^[Gg]igabit.*', re.IGNORECASE)


class CLIEngine:
    def __init__(self):
        self.config_store = ConfigStore()
        self.config_store.load_startup()
        self.mode = "USER_EXEC"
        self.current_interfaces = []
        self.current_vlan = None
        self.current_svi = None
        self.current_management = False
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
        self.kb = KeyBindings()

        @self.kb.add("?")
        def _(event):
            buf = event.app.current_buffer
            text = buf.text
            words = text.split() if text else []
            help_text = get_help_text(self.mode, words, self.current_svi, self.current_management)
            print(f"\n{self.get_prompt()}{text}?")
            print(help_text)
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
        self._raw_line = line  # para comandos que precisam do texto bruto (banner)
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

    # ── USER EXEC ──────────────────────────────────────────────────────────────
    def _dispatch_user_exec(self, tokens):
        cmd = match_command(tokens[0], ["enable", "show", "exit"])
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

    # ── PRIVILEGED EXEC ────────────────────────────────────────────────────────
    def _dispatch_privileged_exec(self, tokens):
        cmd = match_command(tokens[0], [
            "configure", "show", "write", "copy",
            "ping", "disable", "reload", "erase", "clear", "exit",
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

        elif cmd == "ping":
            self._handle_ping(tokens[1:])

        elif cmd == "write":
            if len(tokens) >= 2:
                sub = match_command(tokens[1], ["memory", "erase"])
                if sub == "memory":
                    cmd_write_memory(self.config_store)
                elif sub == "erase":
                    cmd_write_erase(self.config_store)
            else:
                cmd_write_memory(self.config_store)

        elif cmd == "copy":
            if len(tokens) >= 3:
                src = match_command(tokens[1], ["running-config"])
                dst = match_command(tokens[2], ["startup-config"])
                if src == "running-config" and dst == "startup-config":
                    cmd_write_memory(self.config_store)
            else:
                print("% Incomplete command.")

        elif cmd == "erase":
            if len(tokens) >= 2:
                sub = match_command(tokens[1], ["startup-config"])
                if sub == "startup-config":
                    cmd_erase_startup(self.config_store)
            else:
                print("% Incomplete command.")

        elif cmd == "clear":
            if len(tokens) >= 2:
                sub = match_command(tokens[1], ["mac"])
                if sub == "mac":
                    cmd_clear_mac_address_table()
            else:
                print("% Incomplete command.")

        elif cmd == "disable":
            self.mode = "USER_EXEC"

        elif cmd == "reload":
            cmd_reload()

        elif cmd == "exit":
            self.mode = "USER_EXEC"

    # ── GLOBAL CONFIG ──────────────────────────────────────────────────────────
    def _dispatch_global_config(self, tokens):
        cmd = match_command(tokens[0], [
            "hostname", "enable", "vlan", "no",
            "interface", "ip", "spanning-tree", "do", "end", "exit",
            "banner", "lldp", "errdisable",
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

        elif cmd == "ip":
            self._handle_ip_global(tokens[1:])

        elif cmd == "spanning-tree":
            self._handle_spanning_tree_global(tokens[1:])

        elif cmd == "do":
            self._handle_do(tokens[1:])

        elif cmd == "banner":
            if len(tokens) < 2:
                print("% Incomplete command.")
                return
            sub = match_command(tokens[1], ["motd"])
            if sub == "motd":
                # Precisa preservar delimitador/texto bruto
                idx = self._raw_line.find("motd")
                raw_rest = self._raw_line[idx + 4:].strip() if idx >= 0 else ""
                cmd_banner_motd(self.config_store, raw_rest)

        elif cmd == "lldp":
            if len(tokens) < 2:
                print("% Incomplete command.")
                return
            sub = match_command(tokens[1], ["run", "timer", "holdtime", "reinit"])
            if sub == "run":
                cmd_lldp_run(self.config_store)
            elif sub == "timer":
                cmd_lldp_timer(self.config_store, tokens[2:])
            elif sub == "holdtime":
                cmd_lldp_holdtime(self.config_store, tokens[2:])
            elif sub == "reinit":
                cmd_lldp_reinit(self.config_store, tokens[2:])

        elif cmd == "errdisable":
            self._handle_errdisable(tokens[1:])

        elif cmd in ("end", "exit"):
            self.mode = "PRIVILEGED_EXEC"

    def _handle_errdisable(self, tokens):
        if len(tokens) < 2:
            print("% Incomplete command.")
            return
        sub = match_command(tokens[0], ["recovery"])
        if sub != "recovery":
            return
        sub2 = match_command(tokens[1], ["cause", "interval"])
        if sub2 == "cause":
            cmd_errdisable_recovery_cause(self.config_store, tokens[2:])
        elif sub2 == "interval":
            cmd_errdisable_recovery_interval(self.config_store, tokens[2:])

    def _handle_spanning_tree_global(self, tokens):
        if not tokens:
            print("% Incomplete command.")
            return
        sub = match_command(tokens[0], ["mode"])
        if sub == "mode":
            cmd_spanning_tree_mode(self.config_store, tokens[1:])

    def _handle_no_global(self, tokens):
        if not tokens:
            print("% Incomplete command.")
            return
        cmd = match_command(tokens[0], [
            "vlan", "ip", "interface", "spanning-tree",
            "banner", "lldp", "errdisable",
        ])

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
            else:
                cmd_cleanup_vlan_from_ports(self.config_store, vlan_id)

        elif cmd == "ip":
            if len(tokens) < 2:
                print("% Incomplete command.")
                return
            sub = match_command(tokens[1], ["default-gateway", "route"])
            if sub == "default-gateway":
                cmd_no_ip_default_gateway(self.config_store)
            elif sub == "route":
                cmd_no_ip_route(self.config_store, tokens[2:])

        elif cmd == "interface":
            if len(tokens) < 2:
                print("% Incomplete command.")
                return
            combined = "".join(tokens[1:])
            m = _RE_VLAN_IFACE.match(combined)
            if not m:
                print("% Invalid interface specification.")
                return
            vlan_id = int(m.group(1))
            if vlan_id in self.config_store.svi_interfaces:
                del self.config_store.svi_interfaces[vlan_id]
            try:
                ip_mgmt.delete_svi(vlan_id)
            except Exception:
                pass
            print(f"% Interface Vlan{vlan_id} removed.")

        elif cmd == "spanning-tree":
            # no spanning-tree → habilita de volta (pvst)
            cmd_spanning_tree_mode(self.config_store, ["pvst"])

        elif cmd == "banner":
            if len(tokens) >= 2:
                sub = match_command(tokens[1], ["motd"])
                if sub == "motd":
                    cmd_no_banner_motd(self.config_store)

        elif cmd == "lldp":
            if len(tokens) >= 2:
                sub = match_command(tokens[1], ["run"])
                if sub == "run":
                    cmd_no_lldp_run(self.config_store)

        elif cmd == "errdisable":
            if len(tokens) >= 3:
                sub = match_command(tokens[1], ["recovery"])
                if sub == "recovery":
                    sub2 = match_command(tokens[2], ["cause"])
                    if sub2 == "cause":
                        cmd_no_errdisable_recovery_cause(self.config_store, tokens[3:])

    def _handle_ip_global(self, tokens):
        if not tokens:
            print("% Incomplete command.")
            return
        sub = match_command(tokens[0], ["default-gateway", "route"])
        if sub == "default-gateway":
            cmd_ip_default_gateway(self.config_store, tokens[1:])
        elif sub == "route":
            cmd_ip_route(self.config_store, tokens[1:])

    def _handle_do(self, tokens):
        if not tokens:
            print("% Incomplete command.")
            return
        cmd = match_command(tokens[0], ["show", "ping", "write", "copy"])
        if cmd == "show":
            self._handle_show(tokens[1:])
        elif cmd == "ping":
            self._handle_ping(tokens[1:])
        elif cmd == "write":
            if len(tokens) >= 2:
                sub = match_command(tokens[1], ["memory"])
                if sub == "memory":
                    cmd_write_memory(self.config_store)
            else:
                cmd_write_memory(self.config_store)
        elif cmd == "copy":
            if len(tokens) >= 3:
                src = match_command(tokens[1], ["running-config"])
                dst = match_command(tokens[2], ["startup-config"])
                if src == "running-config" and dst == "startup-config":
                    cmd_write_memory(self.config_store)

    def _handle_ping(self, tokens):
        if not tokens:
            print("% Incomplete command.")
            return
        target = tokens[0]
        repeat = 5
        # Suporte a 'ping <ip> repeat <n>'
        i = 1
        while i < len(tokens):
            tok = tokens[i].lower()
            if tok == "repeat" and i + 1 < len(tokens):
                try:
                    repeat = int(tokens[i + 1])
                    if repeat < 1 or repeat > 2147483647:
                        print("% Invalid repeat count.")
                        return
                except ValueError:
                    print("% Invalid repeat count.")
                    return
                i += 2
            else:
                i += 1

        print(f"\nType escape sequence to abort.")
        print(f"Sending {repeat}, 100-byte ICMP Echos to {target}, timeout is 2 seconds:")
        try:
            result = subprocess.run(
                ["ping", "-c", str(repeat), "-W", "2", "-q", target],
                capture_output=True, text=True,
            )
            lines = result.stdout.strip().splitlines()
            stats_line = ""
            rtt_line = ""
            for line in lines:
                if "packets transmitted" in line:
                    stats_line = line
                if "rtt" in line or "round-trip" in line:
                    rtt_line = line
            received = 0
            if stats_line:
                parts = stats_line.split(",")
                for p in parts:
                    if "received" in p:
                        try:
                            received = int(p.strip().split()[0])
                        except (ValueError, IndexError):
                            pass
            dots = "!" * received + "." * (repeat - received)
            print(dots)
            success = int(received * 100 / repeat) if repeat else 0
            print(f"Success rate is {success} percent ({received}/{repeat})", end="")
            if rtt_line and received > 0:
                try:
                    times = rtt_line.split("=")[1].strip().split("/")
                    mn, avg, mx = times[0].strip(), times[1].strip(), times[2].split()[0].strip()
                    print(f", round-trip min/avg/max = {mn}/{avg}/{mx} ms")
                except (IndexError, ValueError):
                    print()
            else:
                print()
        except FileNotFoundError:
            print("\n% ping not available")
        print()

    def _handle_interface_select(self, tokens):
        if not tokens:
            print("% Incomplete command.")
            return

        lower_first = tokens[0].lower()

        # interface range
        if lower_first == "range":
            if len(tokens) < 2:
                print("% Incomplete command.")
                return
            range_spec = " ".join(tokens[1:])
            eths = parse_interface_range(range_spec)
            if not eths:
                print("% Invalid interface range.")
                return
            self.current_interfaces = eths
            self.current_svi = None
            self.current_management = False
            self.mode = "INTERFACE_CONFIG"
            return

        combined = "".join(tokens)

        # Management0
        if _RE_MGMT_IFACE.match(combined):
            self.current_management = True
            self.current_svi = None
            self.current_interfaces = []
            self.mode = "INTERFACE_CONFIG"
            return

        # SVI: VlanX
        m = _RE_VLAN_IFACE.match(combined)
        if m:
            vlan_id = int(m.group(1))
            if vlan_id < 1 or vlan_id > 4094:
                print("% Invalid VLAN ID.")
                return
            self.config_store.register_vlan(vlan_id)
            self.config_store.get_or_create_svi(vlan_id)
            self.current_svi = vlan_id
            self.current_interfaces = []
            self.current_management = False
            self.mode = "INTERFACE_CONFIG"
            return

        # Interface fisica
        eths = parse_interface_spec(combined)
        if eths:
            self.current_interfaces = eths
            self.current_svi = None
            self.current_management = False
            self.mode = "INTERFACE_CONFIG"
            return

        print(f"% Invalid interface: {' '.join(tokens)}")

    # ── INTERFACE CONFIG ───────────────────────────────────────────────────────
    def _dispatch_interface_config(self, tokens):
        if self.current_management:
            self._dispatch_mgmt_config(tokens)
            return
        if self.current_svi is not None:
            self._dispatch_svi_config(tokens)
            return

        cmd = match_command(tokens[0], [
            "switchport", "no", "shutdown", "description",
            "speed", "duplex", "lldp",
            "do", "end", "exit",
        ])
        if cmd == "switchport":
            self._handle_switchport(tokens[1:])
        elif cmd == "no":
            self._handle_no_interface(tokens[1:])
        elif cmd == "shutdown":
            cmd_shutdown(self.config_store, self.current_interfaces, negate=False)
        elif cmd == "description":
            cmd_description(self.config_store, self.current_interfaces, tokens[1:])
        elif cmd == "speed":
            cmd_interface_speed(self.config_store, self.current_interfaces, tokens[1:])
        elif cmd == "duplex":
            cmd_interface_duplex(self.config_store, self.current_interfaces, tokens[1:])
        elif cmd == "lldp":
            self._handle_lldp_interface(tokens[1:], negate=False)
        elif cmd == "do":
            self._handle_do(tokens[1:])
        elif cmd == "end":
            self._exit_interface(to_priv=True)
        elif cmd == "exit":
            self._exit_interface(to_priv=False)

    def _dispatch_mgmt_config(self, tokens):
        cmd = match_command(tokens[0], [
            "ip", "no", "shutdown", "description", "do", "end", "exit",
        ])
        if cmd == "ip":
            self._handle_mgmt_ip(tokens[1:])
        elif cmd == "no":
            self._handle_no_mgmt(tokens[1:])
        elif cmd == "shutdown":
            cmd_mgmt_shutdown(self.config_store, negate=False)
        elif cmd == "description":
            cmd_mgmt_description(self.config_store, tokens[1:])
        elif cmd == "do":
            self._handle_do(tokens[1:])
        elif cmd == "end":
            self._exit_interface(to_priv=True)
        elif cmd == "exit":
            self._exit_interface(to_priv=False)

    def _handle_mgmt_ip(self, tokens):
        if not tokens:
            print("% Incomplete command.")
            return
        sub = match_command(tokens[0], ["address"])
        if sub == "address":
            cmd_mgmt_ip_address(self.config_store, tokens[1:])

    def _handle_no_mgmt(self, tokens):
        if not tokens:
            print("% Incomplete command.")
            return
        cmd = match_command(tokens[0], ["ip", "shutdown"])
        if cmd == "ip":
            if len(tokens) >= 2:
                sub = match_command(tokens[1], ["address"])
                if sub == "address":
                    cmd_no_mgmt_ip_address(self.config_store)
            else:
                print("% Incomplete command.")
        elif cmd == "shutdown":
            cmd_mgmt_shutdown(self.config_store, negate=True)

    def _dispatch_svi_config(self, tokens):
        cmd = match_command(tokens[0], [
            "ip", "no", "shutdown", "description", "do", "end", "exit",
        ])
        if cmd == "ip":
            self._handle_svi_ip(tokens[1:])
        elif cmd == "no":
            self._handle_no_svi(tokens[1:])
        elif cmd == "shutdown":
            cmd_svi_shutdown(self.config_store, self.current_svi, negate=False)
        elif cmd == "description":
            cmd_svi_description(self.config_store, self.current_svi, tokens[1:])
        elif cmd == "do":
            self._handle_do(tokens[1:])
        elif cmd == "end":
            self._exit_interface(to_priv=True)
        elif cmd == "exit":
            self._exit_interface(to_priv=False)

    def _exit_interface(self, to_priv=False):
        self.current_interfaces = []
        self.current_svi = None
        self.current_management = False
        self.mode = "PRIVILEGED_EXEC" if to_priv else "GLOBAL_CONFIG"

    def _handle_svi_ip(self, tokens):
        if not tokens:
            print("% Incomplete command.")
            return
        sub = match_command(tokens[0], ["address"])
        if sub == "address":
            cmd_svi_ip_address(self.config_store, self.current_svi, tokens[1:])

    def _handle_no_svi(self, tokens):
        if not tokens:
            print("% Incomplete command.")
            return
        cmd = match_command(tokens[0], ["ip", "shutdown"])
        if cmd == "ip":
            if len(tokens) >= 2:
                sub = match_command(tokens[1], ["address"])
                if sub == "address":
                    cmd_no_svi_ip_address(self.config_store, self.current_svi)
            else:
                print("% Incomplete command.")
        elif cmd == "shutdown":
            cmd_svi_shutdown(self.config_store, self.current_svi, negate=True)

    def _handle_switchport(self, tokens):
        if not tokens:
            print("% Incomplete command.")
            return
        sub = match_command(tokens[0], ["mode", "access", "trunk"])
        if sub == "mode":
            cmd_switchport_mode(self.config_store, self.current_interfaces, tokens[1:])
        elif sub == "access":
            if len(tokens) < 2:
                print("% Incomplete command.")
                return
            sub2 = match_command(tokens[1], ["vlan"])
            if sub2 == "vlan":
                cmd_switchport_access_vlan(self.config_store, self.current_interfaces, tokens[2:])
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
                        self.config_store, self.current_interfaces, tokens[3:])
            elif sub2 == "native":
                if len(tokens) < 3:
                    print("% Incomplete command.")
                    return
                sub3 = match_command(tokens[2], ["vlan"])
                if sub3 == "vlan":
                    cmd_switchport_trunk_native_vlan(
                        self.config_store, self.current_interfaces, tokens[3:])

    def _handle_lldp_interface(self, tokens, negate=False):
        if not tokens:
            print("% Incomplete command.")
            return
        sub = match_command(tokens[0], ["transmit", "receive"])
        if sub == "transmit":
            cmd_lldp_transmit(self.config_store, self.current_interfaces, enable=not negate)
        elif sub == "receive":
            cmd_lldp_receive(self.config_store, self.current_interfaces, enable=not negate)

    def _handle_no_interface(self, tokens):
        if not tokens:
            print("% Incomplete command.")
            return
        cmd = match_command(tokens[0], ["switchport", "shutdown", "lldp"])
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
            cmd_shutdown(self.config_store, self.current_interfaces, negate=True)
        elif cmd == "lldp":
            self._handle_lldp_interface(tokens[1:], negate=True)

    # ── VLAN CONFIG ────────────────────────────────────────────────────────────
    def _dispatch_vlan_config(self, tokens):
        cmd = match_command(tokens[0], ["name", "do", "exit"])
        if cmd == "name":
            cmd_vlan_name(self.config_store, self.current_vlan, tokens[1:])
        elif cmd == "do":
            self._handle_do(tokens[1:])
        elif cmd == "exit":
            self.current_vlan = None
            self.mode = "GLOBAL_CONFIG"

    # ── SHOW ───────────────────────────────────────────────────────────────────
    def _handle_show(self, tokens):
        if not tokens:
            print("% Incomplete command.")
            return

        cmd = match_command(tokens[0], [
            "vlan", "mac", "interfaces", "ip", "arp",
            "running-config", "startup-config",
            "spanning-tree", "version", "interface",
            "logging", "lldp",
        ])

        if cmd == "vlan":
            show_vlan_brief(self.config_store)

        elif cmd == "mac":
            if len(tokens) >= 2:
                match_command(tokens[1], ["address-table"])
            show_mac_address_table()

        elif cmd == "arp":
            show_arp()

        elif cmd == "interfaces":
            if len(tokens) < 2:
                show_interfaces_status(self.config_store)
                return
            sub_tok = tokens[1].lower()
            # Verificar se e nome de interface (Gi0/1, GigabitEthernet0/1, Management0)
            if sub_tok.startswith("gi") or sub_tok.startswith("gigabit"):
                from backend.bridge import parse_interface_spec
                eths = parse_interface_spec("".join(tokens[1:]))
                if eths:
                    show_interface_detail(self.config_store, eths[0])
                    return
            if sub_tok.startswith("man"):
                show_interface_management(self.config_store)
                return
            sub = match_command(tokens[1], ["status", "trunk"])
            if sub == "status":
                show_interfaces_status(self.config_store)
            elif sub == "trunk":
                show_interfaces_trunk(self.config_store)

        elif cmd == "ip":
            if len(tokens) >= 2:
                sub = match_command(tokens[1], ["interface", "route"])
                if sub == "interface":
                    if len(tokens) >= 3:
                        match_command(tokens[2], ["brief"])
                    show_ip_interface_brief(self.config_store)
                elif sub == "route":
                    show_ip_route(self.config_store)
            else:
                print("% Incomplete command.")

        elif cmd == "logging":
            show_logging()

        elif cmd == "lldp":
            if len(tokens) < 2:
                show_lldp_global(self.config_store)
                return
            sub = match_command(tokens[1], ["neighbors", "interface"])
            if sub == "neighbors":
                if len(tokens) >= 3:
                    sub2 = match_command(tokens[2], ["detail"])
                    if sub2 == "detail":
                        show_lldp_neighbors_detail(self.config_store)
                        return
                show_lldp_neighbors(self.config_store)
            elif sub == "interface":
                specific = None
                if len(tokens) >= 3:
                    from backend.bridge import parse_interface_spec
                    eths = parse_interface_spec("".join(tokens[2:]))
                    specific = eths[0] if eths else None
                show_lldp_interface(self.config_store, specific)

        elif cmd == "interface":
            if len(tokens) < 2:
                print("% Incomplete command.")
                return
            combined = "".join(tokens[1:])
            if _RE_MGMT_IFACE.match(combined):
                show_interface_management(self.config_store)
                return
            m = _RE_VLAN_IFACE.match(combined)
            if m:
                vlan_id = int(m.group(1))
                show_interface_vlan(self.config_store, vlan_id)
            else:
                print("% Invalid interface specification.")

        elif cmd == "running-config":
            if len(tokens) >= 2:
                sub = match_command(tokens[1], ["interface"])
                if sub == "interface":
                    show_running_config_interface(self.config_store, tokens[2:])
            else:
                show_running_config(self.config_store)

        elif cmd == "startup-config":
            show_startup_config()

        elif cmd == "spanning-tree":
            show_spanning_tree(self.config_store)

        elif cmd == "version":
            show_version()
