"""
Gerencia running-config e startup-config em memoria e disco.
"""

import hashlib
import json
import os

CONFIG_DIR = "/opt/switchcli/configs"

# Banner MOTD padrao (centralizado em 55 colunas)
DEFAULT_BANNER_MOTD = "\n".join([
    "#" * 55,
    "#" + " " * 53 + "#",
    "#" + "SWITCH REDES BRASIL L2 - CISCO LIKE".center(53) + "#",
    "#" + " " * 53 + "#",
    "#" + "DESENVOLVIDO POR:".center(53) + "#",
    "#" + "MATHEUS SALVADOR E FRANCISCO NETO".center(53) + "#",
    "#" + " " * 53 + "#",
    "#" + "CO-AUTOR: CLAUDE (ANTHROPIC)".center(53) + "#",
    "#" + " " * 53 + "#",
    "#" * 55,
])


class InterfaceConfig:
    def __init__(self, port_num, mode="access", access_vlan=1,
                 trunk_allowed_vlans=None, native_vlan=1,
                 shutdown=False, description="",
                 speed="auto", duplex="auto",
                 lldp_transmit=True, lldp_receive=True):
        self.port_num = port_num
        self.mode = mode
        self.access_vlan = access_vlan
        self.trunk_allowed_vlans = trunk_allowed_vlans or []
        self.native_vlan = native_vlan
        self.shutdown = shutdown
        self.description = description
        self.speed = speed              # auto | 10 | 100 | 1000
        self.duplex = duplex            # auto | full | half
        self.lldp_transmit = lldp_transmit   # True = habilitado (padrao Cisco)
        self.lldp_receive = lldp_receive     # True = habilitado (padrao Cisco)

    def to_dict(self):
        return {
            "port_num": self.port_num,
            "mode": self.mode,
            "access_vlan": self.access_vlan,
            "trunk_allowed_vlans": self.trunk_allowed_vlans,
            "native_vlan": self.native_vlan,
            "shutdown": self.shutdown,
            "description": self.description,
            "speed": self.speed,
            "duplex": self.duplex,
            "lldp_transmit": self.lldp_transmit,
            "lldp_receive": self.lldp_receive,
        }

    @classmethod
    def from_dict(cls, d):
        return cls(
            port_num=d["port_num"],
            mode=d.get("mode", "access"),
            access_vlan=d.get("access_vlan", 1),
            trunk_allowed_vlans=d.get("trunk_allowed_vlans", []),
            native_vlan=d.get("native_vlan", 1),
            shutdown=d.get("shutdown", False),
            description=d.get("description", ""),
            speed=d.get("speed", "auto"),
            duplex=d.get("duplex", "auto"),
            lldp_transmit=d.get("lldp_transmit", True),
            lldp_receive=d.get("lldp_receive", True),
        )


class SVIConfig:
    def __init__(self, vlan_id, ip_address=None, subnet_mask=None,
                 shutdown=True, description=""):
        self.vlan_id = vlan_id
        self.ip_address = ip_address
        self.subnet_mask = subnet_mask
        self.shutdown = shutdown
        self.description = description

    def to_dict(self):
        return {
            "vlan_id": self.vlan_id,
            "ip_address": self.ip_address,
            "subnet_mask": self.subnet_mask,
            "shutdown": self.shutdown,
            "description": self.description,
        }

    @classmethod
    def from_dict(cls, d):
        return cls(
            vlan_id=d["vlan_id"],
            ip_address=d.get("ip_address"),
            subnet_mask=d.get("subnet_mask"),
            shutdown=d.get("shutdown", True),
            description=d.get("description", ""),
        )


class ManagementConfig:
    """Configuracao da interface de gerencia OOB (eth0 / Management0)."""

    def __init__(self, ip_address=None, subnet_mask=None,
                 shutdown=False, description="", method="unset"):
        self.ip_address = ip_address
        self.subnet_mask = subnet_mask
        self.shutdown = shutdown        # Management0 inicia UP por padrao
        self.description = description
        self.method = method            # unset | static | dhcp

    def to_dict(self):
        return {
            "ip_address": self.ip_address,
            "subnet_mask": self.subnet_mask,
            "shutdown": self.shutdown,
            "description": self.description,
            "method": self.method,
        }

    @classmethod
    def from_dict(cls, d):
        return cls(
            ip_address=d.get("ip_address"),
            subnet_mask=d.get("subnet_mask"),
            shutdown=d.get("shutdown", False),
            description=d.get("description", ""),
            method=d.get("method", "unset"),
        )


class StaticRoute:
    def __init__(self, network, mask, gateway):
        self.network = network
        self.mask = mask
        self.gateway = gateway

    def to_dict(self):
        return {"network": self.network, "mask": self.mask, "gateway": self.gateway}

    @classmethod
    def from_dict(cls, d):
        return cls(d["network"], d["mask"], d["gateway"])

    def key(self):
        return (self.network, self.mask)


class ConfigStore:
    def __init__(self):
        self.hostname = self._load_hostname()
        self.enable_password = None
        self.local_users = {}              # {username: sha256_hash}
        self.vlans = {1: "default"}
        self.interfaces = {}
        self.svi_interfaces = {}
        self.default_gateway = None
        self.management = ManagementConfig()
        self.spanning_tree_mode = "pvst"   # pvst | rapid-pvst | none
        self.static_routes = []            # lista de StaticRoute
        self.banner_motd = DEFAULT_BANNER_MOTD  # texto do banner MOTD
        self.lldp_enabled = False
        self.lldp_timer = 30               # intervalo tx (padrao Cisco: 30s)
        self.lldp_holdtime = 120           # holdtime vizinhos (padrao: 120s)
        self.lldp_reinit = 2               # reinit delay (padrao: 2s)
        self.errdisable_causes = []        # lista de causas habilitadas
        self.errdisable_interval = 300     # segundos
        for i in range(1, 9):
            self.interfaces[i] = InterfaceConfig(port_num=i)

    def _load_hostname(self):
        try:
            with open("/etc/hostname") as f:
                name = f.read().strip()
                return name if name else "Switch"
        except (FileNotFoundError, PermissionError):
            return "Switch"

    def get_vlan_name(self, vlan_id):
        return self.vlans.get(vlan_id)

    def register_vlan(self, vlan_id, name=None):
        if vlan_id < 1 or vlan_id > 4094:
            return False
        if vlan_id not in self.vlans:
            self.vlans[vlan_id] = name or f"VLAN{vlan_id:04d}"
        elif name:
            self.vlans[vlan_id] = name
        return True

    def remove_vlan(self, vlan_id):
        if vlan_id == 1:
            return False
        self.vlans.pop(vlan_id, None)
        return True

    def get_interface(self, port_num):
        return self.interfaces.get(port_num)

    def get_svi(self, vlan_id):
        return self.svi_interfaces.get(vlan_id)

    def get_or_create_svi(self, vlan_id):
        if vlan_id not in self.svi_interfaces:
            self.svi_interfaces[vlan_id] = SVIConfig(vlan_id=vlan_id)
        return self.svi_interfaces[vlan_id]

    def save_startup(self):
        data = self._serialize()
        path = os.path.join(CONFIG_DIR, "startup-config")
        os.makedirs(CONFIG_DIR, exist_ok=True)
        with open(path, "w") as f:
            json.dump(data, f, indent=2)

    def load_startup(self):
        path = os.path.join(CONFIG_DIR, "startup-config")
        if not os.path.exists(path):
            return False
        with open(path) as f:
            data = json.load(f)
        self._deserialize(data)
        return True

    @staticmethod
    def hash_password(password):
        return hashlib.sha256(password.encode()).hexdigest()

    def add_user(self, username, password):
        self.local_users[username] = self.hash_password(password)

    def remove_user(self, username):
        return self.local_users.pop(username, None) is not None

    def verify_user(self, username, password):
        hashed = self.local_users.get(username)
        if hashed is None:
            return False
        return hashed == self.hash_password(password)

    def add_static_route(self, network, mask, gateway):
        route = StaticRoute(network, mask, gateway)
        for r in self.static_routes:
            if r.key() == route.key():
                r.gateway = gateway
                return
        self.static_routes.append(route)

    def remove_static_route(self, network, mask):
        before = len(self.static_routes)
        self.static_routes = [
            r for r in self.static_routes if r.key() != (network, mask)
        ]
        return len(self.static_routes) < before

    def _serialize(self):
        return {
            "hostname": self.hostname,
            "enable_password": self.enable_password,
            "local_users": dict(self.local_users),
            "vlans": {str(k): v for k, v in self.vlans.items()},
            "interfaces": {str(k): v.to_dict() for k, v in self.interfaces.items()},
            "svi_interfaces": {str(k): v.to_dict() for k, v in self.svi_interfaces.items()},
            "default_gateway": self.default_gateway,
            "management": self.management.to_dict(),
            "spanning_tree_mode": self.spanning_tree_mode,
            "static_routes": [r.to_dict() for r in self.static_routes],
            "banner_motd": self.banner_motd,
            "lldp_enabled": self.lldp_enabled,
            "lldp_timer": self.lldp_timer,
            "lldp_holdtime": self.lldp_holdtime,
            "lldp_reinit": self.lldp_reinit,
            "errdisable_causes": list(self.errdisable_causes),
            "errdisable_interval": self.errdisable_interval,
        }

    def _deserialize(self, data):
        self.hostname = data.get("hostname", "Switch")
        self.enable_password = data.get("enable_password")
        self.local_users = dict(data.get("local_users", {}))
        self.vlans = {int(k): v for k, v in data.get("vlans", {}).items()}
        for k, v in data.get("interfaces", {}).items():
            self.interfaces[int(k)] = InterfaceConfig.from_dict(v)
        self.svi_interfaces = {}
        for k, v in data.get("svi_interfaces", {}).items():
            self.svi_interfaces[int(k)] = SVIConfig.from_dict(v)
        self.default_gateway = data.get("default_gateway")
        mgmt_data = data.get("management", {})
        self.management = ManagementConfig.from_dict(mgmt_data) if mgmt_data else ManagementConfig()
        self.spanning_tree_mode = data.get("spanning_tree_mode", "pvst")
        self.static_routes = [
            StaticRoute.from_dict(r) for r in data.get("static_routes", [])
        ]
        self.banner_motd = data.get("banner_motd")
        self.lldp_enabled = data.get("lldp_enabled", False)
        self.lldp_timer = data.get("lldp_timer", 30)
        self.lldp_holdtime = data.get("lldp_holdtime", 120)
        self.lldp_reinit = data.get("lldp_reinit", 2)
        self.errdisable_causes = list(data.get("errdisable_causes", []))
        self.errdisable_interval = data.get("errdisable_interval", 300)
