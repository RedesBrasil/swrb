"""
Gerencia running-config e startup-config em memoria e disco.
Armazena hostname, VLANs, interfaces e enable password.
"""

import json
import os


CONFIG_DIR = "/opt/switchcli/configs"


class InterfaceConfig:
    def __init__(self, port_num, mode="access", access_vlan=1,
                 trunk_allowed_vlans=None, native_vlan=1,
                 shutdown=False, description=""):
        self.port_num = port_num
        self.mode = mode
        self.access_vlan = access_vlan
        self.trunk_allowed_vlans = trunk_allowed_vlans or []
        self.native_vlan = native_vlan
        self.shutdown = shutdown
        self.description = description

    def to_dict(self):
        return {
            "port_num": self.port_num,
            "mode": self.mode,
            "access_vlan": self.access_vlan,
            "trunk_allowed_vlans": self.trunk_allowed_vlans,
            "native_vlan": self.native_vlan,
            "shutdown": self.shutdown,
            "description": self.description,
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
        )


class ConfigStore:
    def __init__(self):
        self.hostname = self._load_hostname()
        self.enable_password = None
        self.vlans = {1: "default"}
        self.interfaces = {}
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

    def _serialize(self):
        return {
            "hostname": self.hostname,
            "enable_password": self.enable_password,
            "vlans": {str(k): v for k, v in self.vlans.items()},
            "interfaces": {
                str(k): v.to_dict() for k, v in self.interfaces.items()
            },
        }

    def _deserialize(self, data):
        self.hostname = data.get("hostname", "Switch")
        self.enable_password = data.get("enable_password")
        self.vlans = {int(k): v for k, v in data.get("vlans", {}).items()}
        for k, v in data.get("interfaces", {}).items():
            self.interfaces[int(k)] = InterfaceConfig.from_dict(v)
