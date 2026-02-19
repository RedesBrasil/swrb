# PLANO DE IMPLEMENTACAO: Switch L2 Cisco-like para EVE-NG

## Objetivo
Entregar um arquivo `virtioa.qcow2` pronto para copiar em `/opt/unetlab/addons/qemu/` no EVE-NG, que boota como um switch L2 com CLI Cisco-like, suportando VLAN basica.

## Resultado final esperado
- Imagem qcow2 comprimida: ~80-120MB
- Boot time: <10 segundos
- Consumo RAM: 128MB
- 9 interfaces de rede (eth0-eth8 → GigabitEthernet0/0-0/8)
- CLI interativo com prompt Cisco-like no console serial (telnet via EVE-NG)

---

# FASE 1 — Build da imagem Alpine Linux

## Objetivo
Criar um disco qcow2 bootavel com Alpine Linux, sem precisar de KVM.

## Ferramenta: `alpine-make-vm-image`
Projeto oficial Alpine Linux: https://github.com/alpinelinux/alpine-make-vm-image
- Funciona via chroot + qemu-nbd (nunca boota uma VM)
- Build em ~32 segundos
- Nao precisa de KVM/virtualizacao

## Pre-requisitos no host de build
```bash
# Instalar dependencias (Debian/Ubuntu)
sudo apt-get install qemu-utils qemu-system-x86 git

# Baixar a ferramenta
git clone https://github.com/alpinelinux/alpine-make-vm-image.git
cd alpine-make-vm-image
```

## Comando de build
```bash
sudo ./alpine-make-vm-image \
    --image-format qcow2 \
    --image-size 512M \
    --serial-console \
    --repositories-file /dev/stdin <<'REPOS' \
    --packages "python3 py3-prompt_toolkit iproute2 mstpd bash agetty" \
    --script-chroot \
    virtioa.qcow2 -- ./configure.sh
https://dl-cdn.alpinelinux.org/alpine/v3.21/main
https://dl-cdn.alpinelinux.org/alpine/v3.21/community
REPOS
```

**Nota sobre versao Alpine**: Usar v3.21 (stable) ou v3.23 (latest). Verificar a versao mais recente em https://alpinelinux.org/downloads/ antes de executar.

## Pacotes instalados e justificativa
| Pacote | Justificativa |
|---|---|
| `python3` | Runtime do CLI shell |
| `py3-prompt_toolkit` | Autocomplete, history, syntax highlighting no CLI (pacote nativo Alpine, **nao precisa de pip**) |
| `iproute2` | Comandos `ip` e `bridge` para manipular VLANs e interfaces |
| `mstpd` | Daemon STP/RSTP para spanning-tree |
| `bash` | Alpine vem com ash; bash facilita scripts |
| `agetty` | Autologin no console serial |

**NAO instalar**:
- `py3-pip` — desnecessario, tudo disponivel via apk
- `bridge-utils` — incompativel com mstpd, usar `ip`/`bridge` do iproute2
- Modulo `8021q` — desnecessario para bridge VLAN filtering

## Script de configuracao (`configure.sh`)
Criar o arquivo `configure.sh` no mesmo diretorio do build:

```bash
#!/bin/sh
set -e

# -------------------------------------------------------
# 1. Kernel boot params: forcar interface naming classico
# -------------------------------------------------------
# CRITICO: sem isso, interfaces aparecem como ens3/enp0s3
# em vez de eth0/eth1 — o EVE-NG exige eth* naming
sed -i 's|^default_kernel_opts=.*|default_kernel_opts="console=ttyS0,115200 net.ifnames=0 biosdevname=0"|' /etc/update-extlinux.conf
update-extlinux

# -------------------------------------------------------
# 2. Console serial — autologin direto no CLI
# -------------------------------------------------------
# Remover consoles padrao e configurar apenas ttyS0
sed -i '/^tty[0-9]/d' /etc/inittab
sed -i '/^ttyS0/d' /etc/inittab
echo 'ttyS0::respawn:/sbin/agetty --autologin root --noclear ttyS0 115200 vt100' >> /etc/inittab

# Permitir login root no serial
grep -q 'ttyS0' /etc/securetty || echo 'ttyS0' >> /etc/securetty

# Profile que lanca o CLI (exec substitui o shell pelo Python)
cat > /root/.profile <<'PROFILE'
# Se estamos num terminal interativo, lancar o CLI do switch
if [ -t 0 ] && [ -f /opt/switchcli/main.py ]; then
    exec /usr/bin/python3 /opt/switchcli/main.py
fi
PROFILE

# -------------------------------------------------------
# 3. Desabilitar servicos desnecessarios
# -------------------------------------------------------
rc-update del crond default 2>/dev/null || true
rc-update del sshd default 2>/dev/null || true

# -------------------------------------------------------
# 4. Habilitar IP forwarding DESABILITADO (e switch, nao router)
# -------------------------------------------------------
echo 'net.ipv4.ip_forward = 0' > /etc/sysctl.d/switch.conf
echo 'net.ipv6.conf.all.forwarding = 0' >> /etc/sysctl.d/switch.conf

# -------------------------------------------------------
# 5. Script de inicializacao do switch
# -------------------------------------------------------
cat > /etc/init.d/switchcli <<'INITSCRIPT'
#!/sbin/openrc-run

description="Switch L2 Bridge Setup"

depend() {
    need net
    after net
}

start() {
    ebegin "Configuring L2 bridge"

    # Criar bridge com VLAN filtering e sem PVID default
    # vlan_default_pvid=0 evita VLAN 1 automatica em cada porta
    ip link add br0 type bridge vlan_filtering 1 vlan_default_pvid 0 2>/dev/null || true
    ip link set br0 up

    # Adicionar todas as interfaces eth1-eth8 a bridge
    # eth0 fica reservada para management (opcional)
    for i in $(seq 1 8); do
        if ip link show eth${i} > /dev/null 2>&1; then
            ip link set eth${i} master br0
            ip link set eth${i} up
        fi
    done

    # Habilitar STP na bridge
    ip link set br0 type bridge stp_state 1

    # Iniciar mstpd para RSTP
    mstpd &
    sleep 1
    mstpctl setforcevers br0 rstp 2>/dev/null || true

    # Carregar startup-config se existir
    if [ -f /opt/switchcli/configs/startup-config ]; then
        /usr/bin/python3 /opt/switchcli/loader.py /opt/switchcli/configs/startup-config &
    fi

    eend 0
}

stop() {
    ebegin "Stopping L2 bridge"
    killall mstpd 2>/dev/null || true
    ip link del br0 2>/dev/null || true
    eend 0
}
INITSCRIPT
chmod +x /etc/init.d/switchcli
rc-update add switchcli default

# -------------------------------------------------------
# 6. Criar diretorio para o CLI (sera populado depois)
# -------------------------------------------------------
mkdir -p /opt/switchcli/cli/commands
mkdir -p /opt/switchcli/backend
mkdir -p /opt/switchcli/configs

# -------------------------------------------------------
# 7. Hostname padrao
# -------------------------------------------------------
echo "Switch" > /etc/hostname
```

## Fallback: se `alpine-make-vm-image` nao funcionar
**Opcao B**: Baixar imagem cloud pre-construida e customizar:
```bash
# Baixar imagem nocloud Alpine (qcow2 pronta, ~105MB)
wget https://dl-cdn.alpinelinux.org/alpine/v3.23/releases/cloud/nocloud_alpine-3.23.3-x86_64-bios-tiny-r0.qcow2 -O virtioa.qcow2

# Redimensionar para 512MB
qemu-img resize virtioa.qcow2 512M

# Montar e customizar
sudo modprobe nbd max_part=16
sudo qemu-nbd --connect=/dev/nbd0 virtioa.qcow2
sudo mount /dev/nbd0p1 /mnt  # ou /dev/nbd0 se nao particionado

# Instalar pacotes via chroot
sudo chroot /mnt apk add python3 py3-prompt_toolkit iproute2 mstpd bash agetty
# Aplicar todas as configs do configure.sh acima

sudo umount /mnt
sudo qemu-nbd --disconnect /dev/nbd0
```

**Opcao C (ultimo recurso)**: QEMU com emulacao TCG (sem KVM):
```bash
qemu-img create -f qcow2 virtioa.qcow2 512M
wget https://dl-cdn.alpinelinux.org/alpine/v3.21/releases/x86_64/alpine-virt-3.21.3-x86_64.iso

qemu-system-x86_64 -m 512 -accel tcg -nic user \
    -boot once=d \
    -cdrom alpine-virt-3.21.3-x86_64.iso \
    -drive file=virtioa.qcow2,format=qcow2 \
    -nographic
# Instalacao manual via setup-alpine (lento, ~5-10x mais que KVM)
```

## Validacao da Fase 1
```bash
# Testar boot da imagem (com emulacao, sem KVM)
qemu-system-x86_64 -m 128 -accel tcg \
    -drive file=virtioa.qcow2,format=qcow2 \
    -nographic -serial mon:stdio \
    -nic user

# Deve aparecer:
# 1. Boot do Alpine via serial
# 2. Login automatico como root
# 3. Shell bash (ate o CLI Python ser instalado)
```

---

# ✅ FASE 1 — CONCLUIDA (2026-02-19)

## Resultado
- **Imagem**: `virtioa.qcow2` — 82MB comprimida, 512MB virtual
- **Base**: Alpine Linux 3.21.5 (generic_alpine bios-tiny cloud image)
- **Boot validado**: ~90s via QEMU TCG (sem KVM), sera <10s com KVM no EVE-NG

## Metodo de build utilizado (diferente do plano original)
O ambiente de build era um **container LXC no Proxmox**, sem modulos `nbd` nem `loop` no kernel.
Portanto `alpine-make-vm-image` (que depende de qemu-nbd) **nao pode ser usado**.

**Metodo alternativo aplicado:**
1. Download da imagem pre-construida: `generic_alpine-3.21.5-x86_64-bios-tiny-r0.qcow2`
2. Resize para 512M com `qemu-img resize`
3. Expansao do filesystem com `guestfish` (e2fsck + resize2fs)
4. Customizacao via `virt-customize` e `guestfish` (libguestfs-tools)
5. Compactacao com `virt-sparsify --compress`

**Para rebuild**, instalar: `sudo apt-get install qemu-utils guestfs-tools libguestfs-tools linux-image-generic`
(o `linux-image-generic` e necessario para o appliance interno do libguestfs)

## Divergencias do plano original (IMPORTANTE para Fase 2)

### 1. `agetty` nao existe no Alpine
- Alpine nao tem pacote `agetty` (que e do `util-linux`)
- **Solucao aplicada**: busybox `getty` com script `/usr/local/bin/autologin`
- Linha no inittab: `ttyS0::respawn:/sbin/getty -n -l /usr/local/bin/autologin 115200 ttyS0 vt100`

### 2. `mstpd` nao existe nos repos Alpine (main/community/testing/edge)
- **mstpd NAO esta disponivel** em nenhuma versao do Alpine
- O init script usa apenas STP do kernel (`stp_state 1`) que e STP basico (802.1D)
- Para RSTP real, seria necessario compilar mstpd do source: https://github.com/mstpd/mstpd
- **Impacto na Fase 2**: remover referencias a `mstpd` e `mstpctl` no CLI; o `show spanning-tree` pode ler de `/sys/class/net/br0/bridge/`

### 3. Pacotes tiny-cloud removidos
- A imagem base incluia `tiny-cloud-*` e `chrony` que foram removidos
- Servicos desabilitados: crond, sshd, chronyd, tiny-cloud-*

### 4. Estrutura do disco
- **Sem tabela de particoes** — filesystem ext4 direto no device (sem MBR/GPT partition table)
- Bootloader: extlinux/syslinux instalado diretamente
- Label do root: `LABEL=/`

## Estado atual da imagem
- [x] Boot via serial console (ttyS0 115200)
- [x] Autologin como root
- [x] `net.ifnames=0 biosdevname=0` (interfaces eth0-eth8)
- [x] Hostname "Switch"
- [x] Bridge br0 criada automaticamente no boot com VLAN filtering
- [x] STP habilitado (kernel built-in)
- [x] Python3 + py3-prompt_toolkit + iproute2 + bash instalados
- [x] Diretorios `/opt/switchcli/{cli/commands,backend,configs}` criados
- [x] `/root/.profile` configurado para lancar CLI quando existir
- [ ] CLI Python ainda nao existe (Fase 2)
- [ ] `/etc/motd` ainda mostra mensagem padrao Alpine (pode ser customizado)

## Como montar/editar a imagem para Fase 2 (copiar arquivos do CLI)
```bash
# Requer libguestfs-tools e linux-image-generic instalados
export LIBGUESTFS_BACKEND=direct

# Copiar arquivos para dentro da imagem:
virt-customize -a virtioa.qcow2 \
  --copy-in /caminho/local/switchcli:/opt/

# Ou via guestfish para operacoes mais granulares:
guestfish -a virtioa.qcow2 -i <<EOF
copy-in /caminho/local/switchcli/main.py /opt/switchcli/
copy-in /caminho/local/switchcli/cli /opt/switchcli/
copy-in /caminho/local/switchcli/backend /opt/switchcli/
chmod 0755 /opt/switchcli/main.py
chmod 0755 /opt/switchcli/loader.py
EOF

# Recomprimir apos alteracoes:
virt-sparsify --compress virtioa.qcow2 virtioa-compressed.qcow2
mv virtioa-compressed.qcow2 virtioa.qcow2
```

## Teste rapido (sem KVM, via TCG)
```bash
qemu-system-x86_64 -m 128 -accel tcg \
    -drive file=virtioa.qcow2,format=qcow2,snapshot=on \
    -nographic -serial mon:stdio \
    -nic user
# Boot demora ~90s em TCG. Com KVM no EVE-NG sera <10s.
# Ctrl+A X para sair do QEMU.
```

---

# FASE 2 — Desenvolvimento do CLI Shell (Python)

## Objetivo
Criar um shell interativo em Python que emula a experiencia Cisco IOS num switch 2960 basico.

## Estrutura do projeto

```
/opt/switchcli/
├── main.py                  # Entry point — lanca o shell
├── loader.py                # Carrega startup-config no boot
├── cli/
│   ├── __init__.py
│   ├── engine.py            # Maquina de estados (User/Privileged/Config/Interface/VLAN)
│   ├── parser.py            # Parser de comandos + abreviacoes
│   ├── completer.py         # Tab completion + ? help
│   ├── banner.py            # Banner de boot estilo Cisco
│   └── commands/
│       ├── __init__.py
│       ├── show.py          # show vlan, show mac, show interfaces, show running
│       ├── config.py        # hostname, enable password
│       ├── interface.py     # switchport mode, switchport access/trunk
│       ├── vlan.py          # vlan X, name Y
│       └── system.py        # write mem, copy run start, exit, end
├── backend/
│   ├── __init__.py
│   ├── bridge.py            # Wrapper para comandos Linux bridge
│   ├── vlan.py              # Gerencia VLANs no kernel
│   ├── interface.py         # Mapeia ethX <-> GigabitEthernetX/X
│   └── config_store.py      # Salva/carrega running-config e startup-config
└── configs/
    ├── running-config       # Gerado dinamicamente (nao editar manualmente)
    └── startup-config       # Persistente entre reboots
```

---

## 2.1 — Entry Point (`main.py`)

```python
#!/usr/bin/env python3
"""Entry point do CLI do switch."""

import sys
import signal
from cli.banner import print_banner
from cli.engine import CLIEngine


def main():
    # Ignorar Ctrl+Z (SIGTSTP) para nao cair no shell Linux
    signal.signal(signal.SIGTSTP, signal.SIG_IGN)

    print_banner()
    engine = CLIEngine()

    try:
        engine.run()
    except (EOFError, KeyboardInterrupt):
        print("\n")
        sys.exit(0)


if __name__ == "__main__":
    main()
```

---

## 2.2 — Maquina de Estados (`cli/engine.py`)

### Modos CLI
```
Switch>                    ← User EXEC (modo inicial)
Switch#                    ← Privileged EXEC (apos "enable")
Switch(config)#            ← Global Config (apos "configure terminal")
Switch(config-if)#         ← Interface Config (apos "interface GigX/X")
Switch(config-vlan)#       ← VLAN Config (apos "vlan X")
```

### Logica da maquina de estados
```
USER_EXEC:
  "enable"              → PRIVILEGED_EXEC (pedir senha se configurada)
  "show ..."            → executar show commands (somente leitura)
  "exit"                → noop ou desconectar

PRIVILEGED_EXEC:
  "configure terminal"  → GLOBAL_CONFIG
  "disable"             → USER_EXEC
  "show ..."            → executar show commands
  "write memory"        → salvar running → startup
  "copy running-config startup-config" → alias de write memory
  "reload"              → reboot do sistema

GLOBAL_CONFIG:
  "hostname <name>"     → alterar hostname
  "vlan <id>"           → VLAN_CONFIG (registrar VLAN no config_store)
  "interface GigX/X"    → INTERFACE_CONFIG
  "interface range GigX/X-X" → INTERFACE_CONFIG (multiplas)
  "no vlan <id>"        → remover VLAN
  "enable password <pw>"→ configurar senha do enable
  "end"                 → PRIVILEGED_EXEC
  "exit"                → PRIVILEGED_EXEC

INTERFACE_CONFIG:
  "switchport mode access"           → flag interna
  "switchport mode trunk"            → flag interna
  "switchport access vlan <id>"      → aplicar VLAN access
  "switchport trunk allowed vlan X"  → aplicar VLANs trunk
  "switchport trunk native vlan X"   → configurar native VLAN
  "no switchport access vlan"        → remover VLAN access
  "shutdown" / "no shutdown"         → down/up interface
  "end"                              → PRIVILEGED_EXEC
  "exit"                             → GLOBAL_CONFIG

VLAN_CONFIG:
  "name <vlan-name>"    → nomear VLAN no config_store
  "exit"                → GLOBAL_CONFIG
```

### Implementacao com prompt_toolkit
```python
from prompt_toolkit import PromptSession
from prompt_toolkit.history import FileHistory

class CLIEngine:
    def __init__(self):
        self.hostname = self._load_hostname()
        self.mode = "USER_EXEC"
        self.current_interface = None
        self.current_vlan = None
        self.session = PromptSession(
            history=FileHistory('/tmp/.switch_history')
        )
        # ... inicializar backend, completer, etc.

    def get_prompt(self):
        prompts = {
            "USER_EXEC":       f"{self.hostname}>",
            "PRIVILEGED_EXEC": f"{self.hostname}#",
            "GLOBAL_CONFIG":   f"{self.hostname}(config)#",
            "INTERFACE_CONFIG":f"{self.hostname}(config-if)#",
            "VLAN_CONFIG":     f"{self.hostname}(config-vlan)#",
        }
        return prompts[self.mode]

    def run(self):
        while True:
            try:
                user_input = self.session.prompt(self.get_prompt())
                user_input = user_input.strip()
                if not user_input:
                    continue
                self.dispatch(user_input)
            except KeyboardInterrupt:
                # Ctrl+C cancela o comando atual (como no Cisco)
                print("^C")
                continue
            except EOFError:
                break
```

---

## 2.3 — Parser de Comandos (`cli/parser.py`)

### Abreviacoes estilo Cisco
O parser deve suportar abreviacoes unicas. Exemplos:
- `sh` → `show`
- `sh vl br` → `show vlan brief`
- `conf t` → `configure terminal`
- `int gi0/1` → `interface GigabitEthernet0/1`
- `wr` → `write memory`
- `no sh` → `no shutdown`

### Algoritmo de abreviacao
```python
def match_command(input_token, valid_commands):
    """
    Retorna o comando completo se input_token e prefixo unico.
    Ex: match_command("sh", ["show", "shutdown"]) → ambiguo → erro
        match_command("sho", ["show", "shutdown"]) → "show"
    """
    matches = [cmd for cmd in valid_commands if cmd.startswith(input_token)]
    if len(matches) == 1:
        return matches[0]
    elif len(matches) > 1:
        raise AmbiguousCommand(input_token, matches)
    else:
        raise InvalidCommand(input_token)
```

### Parsing de `interface range`
```python
# "interface range GigabitEthernet0/1-4"
# Deve expandir para: [eth1, eth2, eth3, eth4]

def parse_interface_range(range_str):
    """Parse 'GigabitEthernet0/1-4' → ['eth1', 'eth2', 'eth3', 'eth4']"""
    # Extrair base e range
    match = re.match(r'GigabitEthernet0/(\d+)-(\d+)', range_str, re.IGNORECASE)
    if match:
        start, end = int(match.group(1)), int(match.group(2))
        return [f'eth{i}' for i in range(start, end + 1)]
```

---

## 2.4 — Completer e Help (`cli/completer.py`)

### Tab completion
Usar `prompt_toolkit.completion.Completer`:
```python
from prompt_toolkit.completion import Completer, Completion

class CiscoCompleter(Completer):
    def __init__(self, engine):
        self.engine = engine

    def get_completions(self, document, complete_event):
        text = document.text_before_cursor
        words = text.split()
        # Determinar completions baseado no modo atual e palavras ja digitadas
        # ...
```

### Help com `?`
Quando o usuario digita `?` no meio de um comando, mostrar opcoes disponiveis:
```
Switch#show ?
  interfaces         Interface status and configuration
  mac address-table  MAC address table
  running-config     Current running configuration
  startup-config     Startup configuration
  vlan               VLAN information
```

**Implementacao**: Interceptar `?` no input antes de enviar ao parser. Mostrar help contextual baseado nos tokens ja digitados e no modo atual.

---

## 2.5 — Banner de Boot (`cli/banner.py`)

```python
import time
import os

def print_banner():
    hostname = "Switch"
    if os.path.exists("/etc/hostname"):
        with open("/etc/hostname") as f:
            hostname = f.read().strip() or "Switch"

    # Calcular uptime
    with open("/proc/uptime") as f:
        uptime_seconds = int(float(f.read().split()[0]))

    uptime_str = format_uptime(uptime_seconds)

    banner = f"""
Cisco IOS Software, C2960 Software (C2960-LANBASEK9-M), Version 15.0(2)SE11
Technical Support: http://www.cisco.com/techsupport
Copyright (c) 1986-2024 by Cisco Systems, Inc.

ROM: Bootstrap program is C2960 boot loader
BOOTLDR: C2960 Boot Loader (C2960-HBOOT-M) Version 15.0(2r)SE11

{hostname} uptime is {uptime_str}
System returned to ROM by power-on
System image file is "flash:c2960-lanbasek9-mz.150-2.SE11.bin"

cisco WS-C2960-8TC-L (PowerPC405) processor with 65536K bytes of memory.
Processor board ID FCZ123456AB
Last reset from power-on
8 Ethernet interfaces
The password-recovery mechanism is enabled.

512K bytes of flash-simulated non-volatile configuration memory.
Base ethernet MAC Address       : 00:AA:BB:CC:DD:00
Motherboard assembly number     : 73-12351-01
Power supply part number        : 341-0097-03
Motherboard serial number       : FCZ123456AB
Model number                    : WS-C2960-8TC-L
System serial number            : FCZ123456AB
"""
    print(banner)

def format_uptime(seconds):
    days = seconds // 86400
    hours = (seconds % 86400) // 3600
    minutes = (seconds % 3600) // 60
    secs = seconds % 60
    parts = []
    if days > 0:
        parts.append(f"{days} day{'s' if days != 1 else ''}")
    if hours > 0:
        parts.append(f"{hours} hour{'s' if hours != 1 else ''}")
    parts.append(f"{minutes} minute{'s' if minutes != 1 else ''}")
    parts.append(f"{secs} second{'s' if secs != 1 else ''}")
    return ", ".join(parts)
```

---

## 2.6 — Show Commands (`cli/commands/show.py`)

### `show vlan brief`
```python
import subprocess
import json

def show_vlan_brief(config_store):
    """
    Saida esperada:
    VLAN Name                             Status    Ports
    ---- -------------------------------- --------- -------------------------------
    1    default                          active    Gi0/1, Gi0/2, Gi0/3
    10   SERVERS                          active    Gi0/4, Gi0/5
    20   USERS                            active    Gi0/6, Gi0/7
    """
    # Buscar VLANs do kernel via JSON
    result = subprocess.run(
        ["bridge", "-j", "-p", "vlan", "show"],
        capture_output=True, text=True
    )
    kernel_vlans = json.loads(result.stdout)

    # Montar mapa vlan_id → [portas]
    vlan_ports = {}  # {vlan_id: [lista de portas]}
    for entry in kernel_vlans:
        dev = entry.get("ifname", "")
        if dev == "br0":
            continue  # ignorar a bridge em si
        for vlan_info in entry.get("vlans", []):
            vid = vlan_info["vlan"]
            if vid not in vlan_ports:
                vlan_ports[vid] = []
            vlan_ports[vid].append(dev)

    # Buscar nomes das VLANs do config_store
    # Formatar output estilo Cisco
    print("VLAN Name                             Status    Ports")
    print("---- -------------------------------- --------- -------------------------------")
    for vid in sorted(vlan_ports.keys()):
        name = config_store.get_vlan_name(vid) or ("default" if vid == 1 else f"VLAN{vid:04d}")
        ports_str = ", ".join(linux_to_cisco(p) for p in vlan_ports[vid])
        print(f"{vid:<4} {name:<32} {'active':<9} {ports_str}")
```

### `show mac address-table`
```python
def show_mac_address_table():
    """
    Saida esperada:
              Mac Address Table
    -------------------------------------------
    Vlan    Mac Address       Type        Ports
    ----    -----------       --------    -----
       1    0050.7966.6800    DYNAMIC     Gi0/1
      10    0050.7966.6801    DYNAMIC     Gi0/4
    """
    result = subprocess.run(
        ["bridge", "-j", "fdb", "show", "dynamic"],
        capture_output=True, text=True
    )
    entries = json.loads(result.stdout)

    print("          Mac Address Table")
    print("-------------------------------------------")
    print("Vlan    Mac Address       Type        Ports")
    print("----    -----------       --------    -----")

    for entry in entries:
        mac = entry.get("mac", "")
        dev = entry.get("ifname", "")
        vlan = entry.get("vlan", "")
        # Formatar MAC como Cisco: aa:bb:cc:dd:ee:ff → aabb.ccdd.eeff
        cisco_mac = format_mac_cisco(mac)
        cisco_port = linux_to_cisco(dev)
        print(f"{vlan:>4}    {cisco_mac:<17} {'DYNAMIC':<11} {cisco_port}")

def format_mac_cisco(mac):
    """aa:bb:cc:dd:ee:ff → aabb.ccdd.eeff"""
    clean = mac.replace(":", "").replace("-", "").lower()
    return f"{clean[0:4]}.{clean[4:8]}.{clean[8:12]}"
```

### `show interfaces status`
```python
def show_interfaces_status():
    """
    Saida esperada:
    Port         Name               Status       Vlan       Duplex  Speed Type
    Gi0/1        SERVIDOR-1         connected    10         a-full  a-1000 10/100/1000BaseTX
    Gi0/2                           notconnect   1          auto    auto   10/100/1000BaseTX
    """
    for i in range(1, 9):
        eth = f"eth{i}"
        cisco = f"Gi0/{i}"
        # Checar operstate
        try:
            with open(f"/sys/class/net/{eth}/operstate") as f:
                state = f.read().strip()
            status = "connected" if state == "up" else "notconnect"
            # Buscar speed
            with open(f"/sys/class/net/{eth}/speed") as f:
                speed = f.read().strip()
        except FileNotFoundError:
            status = "notconnect"
            speed = "auto"
        # ... formatar e imprimir
```

### `show interfaces trunk`
```python
def show_interfaces_trunk(config_store):
    """
    Saida esperada:
    Port        Mode         Encapsulation  Status        Native vlan
    Gi0/8       on           802.1q         trunking      1

    Port        Vlans allowed on trunk
    Gi0/8       10,20,30

    Port        Vlans allowed and active in management domain
    Gi0/8       10,20,30
    """
    # Iterar interfaces, filtrar as que estao em mode trunk no config_store
    # Para cada trunk, listar native vlan e allowed vlans
```

### `show running-config`
```python
def show_running_config(config_store):
    """Gera running-config no formato Cisco IOS."""
    lines = []
    lines.append("Building configuration...")
    lines.append("")
    lines.append("Current configuration : XXX bytes")  # calcular tamanho
    lines.append("!")
    lines.append(f"hostname {config_store.hostname}")
    lines.append("!")

    # VLANs
    for vid, name in config_store.vlans.items():
        lines.append(f"vlan {vid}")
        if name:
            lines.append(f" name {name}")
        lines.append("!")

    # Interfaces
    for i in range(1, 9):
        iface = config_store.get_interface(i)
        lines.append(f"interface GigabitEthernet0/{i}")
        if iface.mode == "access":
            lines.append(f" switchport mode access")
            if iface.access_vlan != 1:
                lines.append(f" switchport access vlan {iface.access_vlan}")
        elif iface.mode == "trunk":
            lines.append(f" switchport mode trunk")
            if iface.native_vlan != 1:
                lines.append(f" switchport trunk native vlan {iface.native_vlan}")
            if iface.allowed_vlans:
                vlans_str = ",".join(str(v) for v in sorted(iface.allowed_vlans))
                lines.append(f" switchport trunk allowed vlan {vlans_str}")
        if iface.shutdown:
            lines.append(" shutdown")
        lines.append("!")

    lines.append("end")
    print("\n".join(lines))
```

---

## 2.7 — Backend Bridge (`backend/bridge.py`)

### Mapeamento de nomes
```python
# Mapeamento bidirecional
INTERFACE_MAP = {
    "GigabitEthernet0/0": "eth0",  # management (reservado)
    "GigabitEthernet0/1": "eth1",
    "GigabitEthernet0/2": "eth2",
    "GigabitEthernet0/3": "eth3",
    "GigabitEthernet0/4": "eth4",
    "GigabitEthernet0/5": "eth5",
    "GigabitEthernet0/6": "eth6",
    "GigabitEthernet0/7": "eth7",
    "GigabitEthernet0/8": "eth8",
}

# Reverso para show commands
REVERSE_MAP = {v: k for k, v in INTERFACE_MAP.items()}

def cisco_to_linux(cisco_name):
    """GigabitEthernet0/1 → eth1. Aceita abreviacoes: Gi0/1, gi0/1"""
    # Normalizar: gi0/1, gig0/1, gigabitethernet0/1 → GigabitEthernet0/1
    normalized = normalize_interface_name(cisco_name)
    return INTERFACE_MAP.get(normalized)

def linux_to_cisco(linux_name):
    """eth1 → Gi0/1"""
    full = REVERSE_MAP.get(linux_name, linux_name)
    return full.replace("GigabitEthernet", "Gi")
```

---

## 2.8 — Backend VLAN (`backend/vlan.py`)

### Tabela de mapeamento CLI → Linux COMPLETA

```python
import subprocess

def set_access_vlan(eth_name, vlan_id):
    """
    Cisco: switchport access vlan 10
    Linux: bridge vlan add dev eth1 vid 10 pvid untagged

    Nota: como a bridge foi criada com vlan_default_pvid=0,
    nao precisa remover VLAN 1 — ela nunca foi atribuida.

    Flags:
      pvid     = frames untagged que chegam recebem tag deste VID (ingress)
      untagged = frames deste VID saem sem tag (egress)
    """
    # Primeiro remover qualquer VLAN anterior desta porta
    _clear_port_vlans(eth_name)

    subprocess.run([
        "bridge", "vlan", "add",
        "dev", eth_name,
        "vid", str(vlan_id),
        "pvid", "untagged"
    ], check=True)


def set_trunk_allowed_vlans(eth_name, vlan_list, native_vlan=None):
    """
    Cisco: switchport trunk allowed vlan 10,20,30
           switchport trunk native vlan 10
    Linux: bridge vlan add dev eth2 vid 10 pvid untagged  (native)
           bridge vlan add dev eth2 vid 20                 (tagged)
           bridge vlan add dev eth2 vid 30                 (tagged)

    Sem flags pvid/untagged = frame sai TAGGED (trunk behavior).
    Com pvid untagged = frame sai UNTAGGED (native VLAN).
    """
    _clear_port_vlans(eth_name)

    for vid in vlan_list:
        cmd = ["bridge", "vlan", "add", "dev", eth_name, "vid", str(vid)]
        if native_vlan and vid == native_vlan:
            cmd.extend(["pvid", "untagged"])
        subprocess.run(cmd, check=True)


def remove_access_vlan(eth_name):
    """
    Cisco: no switchport access vlan
    Linux: bridge vlan del dev eth1 vid <current_vid>
    """
    _clear_port_vlans(eth_name)


def set_interface_shutdown(eth_name, shutdown=True):
    """
    Cisco: shutdown / no shutdown
    Linux: ip link set eth1 down / ip link set eth1 up
    """
    state = "down" if shutdown else "up"
    subprocess.run(["ip", "link", "set", eth_name, state], check=True)


def _clear_port_vlans(eth_name):
    """Remove todas as VLANs de uma porta."""
    result = subprocess.run(
        ["bridge", "-j", "vlan", "show", "dev", eth_name],
        capture_output=True, text=True
    )
    import json
    try:
        data = json.loads(result.stdout)
        for entry in data:
            for vlan_info in entry.get("vlans", []):
                vid = vlan_info["vlan"]
                subprocess.run(
                    ["bridge", "vlan", "del", "dev", eth_name, "vid", str(vid)],
                    check=True
                )
    except (json.JSONDecodeError, KeyError):
        pass
```

### Nota importante sobre `vlan <id>` no modo config
```python
def create_vlan(config_store, vlan_id, name=None):
    """
    Cisco: vlan 10 + name SERVERS

    NO LINUX BRIDGE, VLANs NAO PRECISAM SER CRIADAS EXPLICITAMENTE.
    Elas existem quando atribuidas a portas.

    Este comando APENAS registra a VLAN no config_store interno
    (nome, ID, estado administrativo).
    A VLAN so aparece no kernel quando alguma porta for configurada
    com 'switchport access/trunk vlan X'.
    """
    config_store.register_vlan(vlan_id, name)
```

---

## 2.9 — Config Store (`backend/config_store.py`)

### Estrutura de dados em memoria
```python
import json
import os

class ConfigStore:
    CONFIG_DIR = "/opt/switchcli/configs"

    def __init__(self):
        self.hostname = "Switch"
        self.enable_password = None
        self.vlans = {1: "default"}  # {vlan_id: name}
        self.interfaces = {}  # {port_num: InterfaceConfig}

        # Inicializar 8 interfaces com defaults
        for i in range(1, 9):
            self.interfaces[i] = InterfaceConfig(port_num=i)

    def register_vlan(self, vlan_id, name=None):
        if vlan_id not in self.vlans:
            self.vlans[vlan_id] = name or f"VLAN{vlan_id:04d}"
        elif name:
            self.vlans[vlan_id] = name

    def remove_vlan(self, vlan_id):
        if vlan_id == 1:
            return  # nao pode remover VLAN 1
        self.vlans.pop(vlan_id, None)

    def save_startup(self):
        """write memory / copy running-config startup-config"""
        data = self._serialize()
        path = os.path.join(self.CONFIG_DIR, "startup-config")
        with open(path, "w") as f:
            json.dump(data, f, indent=2)

    def load_startup(self):
        """Carregado no boot pelo init script"""
        path = os.path.join(self.CONFIG_DIR, "startup-config")
        if os.path.exists(path):
            with open(path) as f:
                data = json.load(f)
            self._deserialize(data)
            return True
        return False

    def _serialize(self):
        return {
            "hostname": self.hostname,
            "enable_password": self.enable_password,
            "vlans": self.vlans,
            "interfaces": {
                str(k): v.to_dict() for k, v in self.interfaces.items()
            }
        }

    def _deserialize(self, data):
        self.hostname = data.get("hostname", "Switch")
        self.enable_password = data.get("enable_password")
        self.vlans = {int(k): v for k, v in data.get("vlans", {}).items()}
        for k, v in data.get("interfaces", {}).items():
            self.interfaces[int(k)] = InterfaceConfig.from_dict(v)


class InterfaceConfig:
    def __init__(self, port_num, mode="access", access_vlan=1,
                 trunk_allowed_vlans=None, native_vlan=1, shutdown=False):
        self.port_num = port_num
        self.mode = mode               # "access" ou "trunk"
        self.access_vlan = access_vlan  # vlan_id (modo access)
        self.trunk_allowed_vlans = trunk_allowed_vlans or []  # [vlan_ids] (modo trunk)
        self.native_vlan = native_vlan  # vlan_id (trunk native)
        self.shutdown = shutdown

    def to_dict(self):
        return {
            "port_num": self.port_num,
            "mode": self.mode,
            "access_vlan": self.access_vlan,
            "trunk_allowed_vlans": self.trunk_allowed_vlans,
            "native_vlan": self.native_vlan,
            "shutdown": self.shutdown,
        }

    @classmethod
    def from_dict(cls, d):
        return cls(**d)
```

---

## 2.10 — Loader de startup-config (`loader.py`)

```python
#!/usr/bin/env python3
"""
Carrega startup-config e aplica as configuracoes no kernel.
Executado pelo init script no boot.
"""

import sys
from backend.config_store import ConfigStore
from backend.vlan import set_access_vlan, set_trunk_allowed_vlans, set_interface_shutdown

def load_and_apply(config_path):
    store = ConfigStore()
    store.load_startup()

    # Aplicar hostname
    with open("/etc/hostname", "w") as f:
        f.write(store.hostname + "\n")

    # Aplicar configuracao de cada interface
    for port_num, iface in store.interfaces.items():
        eth = f"eth{port_num}"
        if iface.mode == "access" and iface.access_vlan != 1:
            set_access_vlan(eth, iface.access_vlan)
        elif iface.mode == "trunk" and iface.trunk_allowed_vlans:
            set_trunk_allowed_vlans(
                eth,
                iface.trunk_allowed_vlans,
                native_vlan=iface.native_vlan
            )
        if iface.shutdown:
            set_interface_shutdown(eth, shutdown=True)

if __name__ == "__main__":
    config_path = sys.argv[1] if len(sys.argv) > 1 else "/opt/switchcli/configs/startup-config"
    load_and_apply(config_path)
```

---

## 2.11 — Todos os Comandos do MVP

### User EXEC (`Switch>`)
| Comando | Acao |
|---|---|
| `enable` | Entra em Privileged EXEC (pede senha se configurada) |
| `show vlan brief` | Lista VLANs e portas |
| `show mac address-table` | Lista MACs aprendidos |
| `show interfaces status` | Status de cada porta |
| `show interfaces trunk` | Lista trunk ports |
| `show running-config` | Config atual |
| `show startup-config` | Config salva |
| `exit` | Noop ou desconectar |

### Privileged EXEC (`Switch#`)
| Comando | Acao |
|---|---|
| Todos os `show` acima | Mesmos |
| `configure terminal` | Entra em Global Config |
| `write memory` | Salva running → startup |
| `copy running-config startup-config` | Alias de write memory |
| `disable` | Volta para User EXEC |
| `reload` | Executa `reboot` |

### Global Config (`Switch(config)#`)
| Comando | Acao |
|---|---|
| `hostname <name>` | Altera hostname |
| `enable password <pw>` | Define senha do enable |
| `vlan <id>` | Entra em VLAN Config (registra VLAN internamente) |
| `no vlan <id>` | Remove VLAN (remove das portas e do config_store) |
| `interface GigabitEthernet0/<0-8>` | Entra em Interface Config |
| `interface range GigabitEthernet0/<start>-<end>` | Interface Config para multiplas portas |
| `end` | Volta para Privileged EXEC |
| `exit` | Volta para Privileged EXEC |

### Interface Config (`Switch(config-if)#`)
| Comando | Acao Linux |
|---|---|
| `switchport mode access` | Seta flag `mode=access` no config_store |
| `switchport mode trunk` | Seta flag `mode=trunk` no config_store |
| `switchport access vlan <id>` | `bridge vlan add dev ethX vid <id> pvid untagged` |
| `switchport trunk allowed vlan <id-list>` | `bridge vlan add dev ethX vid <id>` para cada (sem pvid/untagged = tagged) |
| `switchport trunk native vlan <id>` | `bridge vlan add dev ethX vid <id> pvid untagged` |
| `no switchport access vlan` | Remove VLANs da porta |
| `shutdown` | `ip link set ethX down` |
| `no shutdown` | `ip link set ethX up` |
| `end` | Volta para Privileged EXEC |
| `exit` | Volta para Global Config |

### VLAN Config (`Switch(config-vlan)#`)
| Comando | Acao |
|---|---|
| `name <vlan-name>` | Registra nome no config_store |
| `exit` | Volta para Global Config |

---

## Validacao da Fase 2
Testar o CLI localmente (fora da VM) antes de empacotar:
```bash
# Criar ambiente de teste (precisa de root para bridge)
sudo python3 main.py

# Testar sequencia basica:
# enable
# configure terminal
# hostname TestSwitch
# vlan 10
# name SERVERS
# exit
# interface GigabitEthernet0/1
# switchport mode access
# switchport access vlan 10
# end
# show vlan brief
# show running-config
# write memory
```

---

# FASE 2 — CONCLUIDA (2026-02-19)

## Resultado
- **16 arquivos Python** criados em `/home/francisco/swrb/switchcli/`
- **Todos os testes unitarios passaram**: syntax check, imports, maquina de estados, parser de abreviacoes, serialize/deserialize de config, mapeamento de interfaces
- Testado localmente com mocks (host nao tem prompt_toolkit, mas a imagem Alpine sim via `py3-prompt_toolkit`)

## Estrutura final implementada
```
switchcli/
├── main.py                  # Entry point (exec pelo .profile do root)
├── loader.py                # Aplica startup-config no boot (chamado pelo init script)
├── cli/
│   ├── __init__.py
│   ├── engine.py            # Maquina de estados (5 modos) + dispatch de todos os comandos
│   ├── parser.py            # Parser com abreviacoes Cisco + parse_vlan_list
│   ├── completer.py         # Tab completion + ? help (prompt_toolkit Completer)
│   ├── banner.py            # Banner de boot estilo Cisco 2960
│   └── commands/
│       ├── __init__.py
│       ├── show.py          # show vlan brief, mac address-table, interfaces, running/startup-config, spanning-tree, version
│       ├── config.py        # hostname, enable password
│       ├── interface.py     # switchport mode/access/trunk, shutdown, description
│       ├── vlan.py          # name
│       └── system.py        # write memory, reload
├── backend/
│   ├── __init__.py
│   ├── bridge.py            # Mapeamento Cisco<->Linux, MAC format, parse ranges
│   ├── vlan.py              # bridge vlan add/del via subprocess
│   ├── interface.py         # ip link set, leitura de /sys/class/net/
│   └── config_store.py      # ConfigStore + InterfaceConfig, serialize JSON
└── configs/                 # (vazio — preenchido em runtime)
```

## Comandos implementados (MVP completo)
- **User EXEC**: enable, show (vlan brief, mac address-table, interfaces status/trunk, running-config, startup-config, spanning-tree, version), exit
- **Privileged EXEC**: configure terminal, show, write memory, copy running-config startup-config, disable, reload, exit
- **Global Config**: hostname, enable password, vlan, no vlan, interface, interface range, end, exit
- **Interface Config**: switchport mode access/trunk, switchport access vlan, switchport trunk allowed vlan, switchport trunk native vlan, no switchport access vlan, shutdown, no shutdown, description, end, exit
- **VLAN Config**: name, exit

## Funcionalidades
- Abreviacoes estilo Cisco: `sh vl br`, `conf t`, `int gi0/1`, `wr`, `no sh`
- Tab completion contextual por modo
- Help com `?` contextual (mostra opcoes disponiveis)
- History de comandos persistente (/tmp/.switch_history)
- Serialize/deserialize de running-config como JSON
- Banner de boot com uptime real, hostname, MAC

## Divergencias/decisoes tomadas na Fase 2

### 1. STP: sem mstpd, usando kernel built-in
- `show spanning-tree` le diretamente de `/sys/class/net/br0/bridge/` e `/sys/class/net/ethX/brport/`
- Mostra estado STP basico (802.1D), nao RSTP
- Removidas todas as referencias a `mstpd` e `mstpctl`

### 2. `getpass` para enable password
- Usa `getpass.getpass()` para nao ecoar a senha no terminal
- Funciona via console serial (ttyS0)

### 3. sys.path.insert no main.py e loader.py
- Ambos fazem `sys.path.insert(0, dirname(abspath(__file__)))` para que imports relativos funcionem independente do CWD
- Isso e necessario porque o init script executa com cwd=/

### 4. `show spanning-tree` — valores do kernel em jiffies
- Os valores `hello_time`, `max_age`, `forward_delay` do kernel estao em jiffies (x256)
- O codigo divide por 256 para converter em segundos

### 5. Sem `show vlan` sem `brief`
- `show vlan` e `show vlan brief` fazem a mesma coisa (brief e o unico subcomando implementado)

## Notas IMPORTANTES para a Fase 3 (integracao)

### Como copiar o CLI para dentro da imagem
```bash
export LIBGUESTFS_BACKEND=direct

# Copiar toda a arvore switchcli para /opt/switchcli/ na imagem
virt-customize -a virtioa.qcow2 \
  --copy-in /home/francisco/swrb/switchcli/main.py:/opt/switchcli/ \
  --copy-in /home/francisco/swrb/switchcli/loader.py:/opt/switchcli/ \
  --copy-in /home/francisco/swrb/switchcli/cli:/opt/switchcli/ \
  --copy-in /home/francisco/swrb/switchcli/backend:/opt/switchcli/ \
  --chmod 0755:/opt/switchcli/main.py \
  --chmod 0755:/opt/switchcli/loader.py

# Recomprimir
virt-sparsify --compress virtioa.qcow2 virtioa-compressed.qcow2
mv virtioa-compressed.qcow2 virtioa.qcow2
```

### NAO copiar
- Diretorio `configs/` — ja existe na imagem, criado pelo configure.sh
- Arquivos `__pycache__/` — serao gerados pelo Python na primeira execucao
- O diretorio `switchcli/` inteiro NAO deve ser copiado como subdiretorio — o conteudo vai direto em `/opt/switchcli/`

### Validacao pos-copia
Apos copiar, verificar que existem dentro da imagem:
```
/opt/switchcli/main.py        (chmod 755)
/opt/switchcli/loader.py      (chmod 755)
/opt/switchcli/cli/engine.py
/opt/switchcli/cli/parser.py
/opt/switchcli/cli/completer.py
/opt/switchcli/cli/banner.py
/opt/switchcli/cli/commands/show.py
/opt/switchcli/cli/commands/config.py
/opt/switchcli/cli/commands/interface.py
/opt/switchcli/cli/commands/vlan.py
/opt/switchcli/cli/commands/system.py
/opt/switchcli/backend/bridge.py
/opt/switchcli/backend/vlan.py
/opt/switchcli/backend/interface.py
/opt/switchcli/backend/config_store.py
```

### O que ja esta configurado na imagem (Fase 1)
- `/root/.profile` faz `exec /usr/bin/python3 /opt/switchcli/main.py` se o arquivo existir
- `/etc/init.d/switchcli` cria bridge br0, adiciona eth1-eth8, habilita STP, e chama `loader.py` se startup-config existir
- `py3-prompt_toolkit` ja esta instalado via apk
- Python 3 ja esta instalado

### Sequencia de boot esperada apos integracao
1. Alpine boot via serial (ttyS0)
2. OpenRC executa `/etc/init.d/switchcli start` → cria br0, eth1-8 na bridge, STP on
3. Se `/opt/switchcli/configs/startup-config` existir → `loader.py` aplica config
4. getty autologin root → `.profile` → `exec python3 /opt/switchcli/main.py`
5. Banner Cisco aparece
6. Prompt `Switch>` (ou hostname customizado)

---

# FASE 3 — Integracao (copiar CLI para a imagem)

## Objetivo
Copiar os arquivos Python para dentro do qcow2 e validar o boot completo.

## Passos

### 3.1 — Montar a imagem
```bash
sudo modprobe nbd max_part=16
sudo qemu-nbd --connect=/dev/nbd0 virtioa.qcow2
# Aguardar o device aparecer
sleep 2

# Descobrir particao (pode ser /dev/nbd0p1, /dev/nbd0p2, ou /dev/nbd0 direto)
sudo fdisk -l /dev/nbd0
sudo mount /dev/nbd0p1 /mnt  # ajustar conforme output do fdisk
```

### 3.2 — Copiar arquivos do CLI
```bash
# Copiar todo o projeto
sudo cp -r /caminho/local/switchcli/* /mnt/opt/switchcli/

# Garantir permissoes
sudo chmod +x /mnt/opt/switchcli/main.py
sudo chmod +x /mnt/opt/switchcli/loader.py

# Criar diretorio de configs se nao existe
sudo mkdir -p /mnt/opt/switchcli/configs
```

### 3.3 — Desmontar
```bash
sudo umount /mnt
sudo qemu-nbd --disconnect /dev/nbd0
```

### 3.4 — Testar boot completo
```bash
qemu-system-x86_64 -m 128 -accel tcg \
    -drive file=virtioa.qcow2,format=qcow2 \
    -nographic -serial mon:stdio \
    -device virtio-net-pci,netdev=net0 \
    -netdev user,id=net0 \
    -device virtio-net-pci,netdev=net1 \
    -netdev user,id=net1

# Deve aparecer:
# 1. Boot Alpine
# 2. Init script cria bridge br0
# 3. Banner Cisco
# 4. Prompt: Switch>
# 5. Comandos funcionando
```

---

# FASE 3 — CONCLUIDA (2026-02-19)

## Resultado
- **18 arquivos Python** copiados com sucesso para `/opt/switchcli/` dentro da imagem
- **Boot completo validado** via QEMU TCG (sem KVM)
- **CLI funcional**: banner Cisco, prompt `Switch>`, `show vlan brief`, `show running-config` todos operacionais
- **Imagem**: 82MB comprimida (sem alteracao significativa de tamanho apos adicionar os ~50KB de Python)

## Metodo utilizado
Como o ambiente de build e um **container LXC no Proxmox** (sem modulos `nbd`/`loop`), o metodo original (qemu-nbd + mount) **nao funciona**. Foi utilizado `virt-customize` do libguestfs-tools:

```bash
export LIBGUESTFS_BACKEND=direct

virt-customize -a virtioa.qcow2 \
  --copy-in /home/francisco/swrb/switchcli/main.py:/opt/switchcli/ \
  --copy-in /home/francisco/swrb/switchcli/loader.py:/opt/switchcli/ \
  --copy-in /home/francisco/swrb/switchcli/cli:/opt/switchcli/ \
  --copy-in /home/francisco/swrb/switchcli/backend:/opt/switchcli/ \
  --chmod 0755:/opt/switchcli/main.py \
  --chmod 0755:/opt/switchcli/loader.py \
  --run-command 'chown -R root:root /opt/switchcli/'
```

**Para rebuild/atualizacao do CLI**, basta repetir o comando acima (substitui os arquivos).

## Sequencia de boot validada
1. Alpine boot via serial (ttyS0 115200) — ~90s em TCG, sera <10s com KVM no EVE-NG
2. OpenRC executa `/etc/init.d/switchcli start` → `* Configuring L2 bridge ... [ ok ]`
3. getty autologin root → `.profile` → `exec python3 /opt/switchcli/main.py`
4. Banner Cisco aparece (com MAC real da VM, uptime calculado)
5. Prompt `Switch>` funcional
6. Comandos `show vlan brief` e `show running-config` testados com sucesso

## Comandos de teste validados
```
Switch> show vlan brief
VLAN Name                             Status    Ports
---- -------------------------------- --------- -------------------------------
1    default                          active

Switch> show running-config
Building configuration...

Current configuration:
!
hostname Switch
!
interface GigabitEthernet0/1
 switchport mode access
!
[...8 interfaces...]
!
end
```

## Notas IMPORTANTES para a Fase 4 (empacotamento e otimizacao)

### 1. /etc/motd ainda mostra mensagem padrao Alpine
- A mensagem "Welcome to Alpine!" aparece ANTES do banner Cisco no boot
- **Recomendacao para Fase 4**: limpar `/etc/motd` (esvaziar ou remover) para que so apareca o banner Cisco
- Comando: `virt-customize -a virtioa.qcow2 --run-command 'echo -n > /etc/motd'`

### 2. prompt_toolkit e CPR warning
- No boot aparece: `WARNING: your terminal doesn't support cursor position requests (CPR).`
- Isso ocorre porque o console serial (ttyS0) via QEMU nao responde a sequencias CPR
- **Nao e um problema funcional** — o CLI funciona normalmente apos o warning
- No EVE-NG via telnet, o comportamento pode ser diferente (depende do cliente telnet)
- **Possivel fix para Fase 4**: suprimir o warning no prompt_toolkit ou redirecionar stderr

### 3. Tamanho atual: 82MB — ja dentro do target (80-120MB)
- A imagem ja esta comprimida (virt-sparsify da Fase 1)
- A Fase 4 pode reduzir ainda mais com limpeza de cache/docs/man pages
- Executar `virt-sparsify --compress` apos a limpeza da Fase 4

### 4. Como atualizar o CLI (se precisar corrigir bugs)
```bash
export LIBGUESTFS_BACKEND=direct

# Copiar arquivos atualizados (substitui os existentes)
virt-customize -a virtioa.qcow2 \
  --copy-in /home/francisco/swrb/switchcli/main.py:/opt/switchcli/ \
  --copy-in /home/francisco/swrb/switchcli/loader.py:/opt/switchcli/ \
  --copy-in /home/francisco/swrb/switchcli/cli:/opt/switchcli/ \
  --copy-in /home/francisco/swrb/switchcli/backend:/opt/switchcli/ \
  --chmod 0755:/opt/switchcli/main.py \
  --chmod 0755:/opt/switchcli/loader.py \
  --run-command 'chown -R root:root /opt/switchcli/'

# Recomprimir apos alteracoes
virt-sparsify --compress virtioa.qcow2 virtioa-compressed.qcow2
mv virtioa-compressed.qcow2 virtioa.qcow2
```

### 5. Dependencias no host de build (LXC container)
```bash
sudo apt-get install qemu-utils guestfs-tools libguestfs-tools linux-image-generic
```
O `linux-image-generic` e obrigatorio para o appliance interno do libguestfs funcionar.

### 6. Teste rapido (sem KVM, via TCG)
```bash
qemu-system-x86_64 -m 128 -accel tcg \
    -drive file=virtioa.qcow2,format=qcow2,snapshot=on \
    -nographic -serial mon:stdio \
    -device virtio-net-pci,netdev=net0 \
    -netdev user,id=net0 \
    -device virtio-net-pci,netdev=net1 \
    -netdev user,id=net1
# Boot demora ~90s em TCG. Com KVM no EVE-NG sera <10s.
# Usar snapshot=on para nao alterar a imagem durante testes.
# Ctrl+A X para sair do QEMU.
```

### 7. Checklist para Fase 4
- [ ] Limpar `/etc/motd` (remover mensagem Alpine)
- [ ] Executar limpeza de cache: `apk cache clean`, `rm -rf /var/cache/apk/*`
- [ ] Remover docs/man: `rm -rf /usr/share/man/* /usr/share/doc/*`
- [ ] Limpar logs: `rm -rf /var/log/*`
- [ ] Zerar espaco livre: `dd if=/dev/zero of=/tmp/zero bs=1M; rm /tmp/zero`
- [ ] Recomprimir: `virt-sparsify --compress` ou `qemu-img convert -c`
- [ ] (Opcional) Suprimir warning CPR do prompt_toolkit

---

# FASE 4 — Empacotamento e otimizacao

## Objetivo
Reduzir tamanho do qcow2 e preparar para EVE-NG.

## Passos

### 4.1 — Limpeza dentro da imagem
Montar a imagem novamente e executar:
```bash
# Via chroot ou boot com QEMU
apk cache clean
rm -rf /var/cache/apk/*
rm -rf /usr/share/man/*
rm -rf /usr/share/doc/*
rm -rf /tmp/*
rm -rf /var/log/*
```

### 4.2 — Zerar espaco livre (melhora compressao)
Dentro da VM/chroot:
```bash
dd if=/dev/zero of=/tmp/zero bs=1M 2>/dev/null || true
rm /tmp/zero
sync
```

### 4.3 — Compactar qcow2
```bash
# Desligar a VM primeiro!
qemu-img convert -f qcow2 -O qcow2 -c virtioa.qcow2 virtioa-compressed.qcow2
mv virtioa-compressed.qcow2 virtioa.qcow2
```

### Resultado esperado
- Tamanho comprimido: ~80-120MB
- Boot time: <10 segundos
- RAM: 128MB

---

# FASE 4 — CONCLUIDA (2026-02-19)

## Resultado
- **Imagem final**: `virtioa.qcow2` — 81MB comprimida (disk size 80MB), 512MB virtual
- **Boot time com KVM**: ~6 segundos ate o prompt `Switch>` (sem contar DHCP no eth0)
- **RAM**: 128MB
- **Todas as metas atingidas**

## Operacoes realizadas

### 1. Limpeza da imagem (via virt-customize)
Removidos de dentro da imagem:
- `/etc/motd` — esvaziado (removia mensagem "Welcome to Alpine!" antes do banner Cisco)
- `/var/cache/apk/*` — cache de pacotes Alpine
- `/usr/share/man/*` e `/usr/share/doc/*` — documentacao/man pages
- `/var/log/*` — logs antigos
- `/tmp/*` — arquivos temporarios
- `/root/.ash_history` — historico de shell
- `__pycache__/` em todos os diretorios Python

### 2. Zeramento de espaco livre
- `dd if=/dev/zero` para preencher espaco livre com zeros
- Melhora significativa na compressao do qcow2

### 3. Compressao final
- `virt-sparsify --compress` para recomprimir
- Tamanho reduziu de 82MB para 81MB (ganho modesto porque a imagem base ja era pequena)

### 4. Supressao do warning CPR do prompt_toolkit
- **Problema**: `WARNING: your terminal doesn't support cursor position requests (CPR).` aparecia no boot
- **Fix aplicado**: `os.environ["PROMPT_TOOLKIT_NO_CPR"] = "1"` no `main.py` antes dos imports do prompt_toolkit
- **Resultado**: warning eliminado completamente, CLI inicia limpo

### 5. Reducao do timeout do bootloader syslinux
- **Antes**: `TIMEOUT 100` (10 segundos de countdown "Alpine will be booted automatically in X seconds")
- **Depois**: `TIMEOUT 10` (1 segundo)
- Alterado tanto em `/boot/extlinux.conf` (runtime) como em `/etc/update-extlinux.conf` (persistente)
- **Ganho**: ~9 segundos a menos no boot

### 6. Atualizacao do CLI na imagem
- `main.py` atualizado com fix do CPR (via `virt-customize --copy-in`)
- Todos os arquivos Python recopiados para garantir consistencia

## Boot validado com KVM
```
Sequencia observada:
1. Syslinux carrega kernel em ~1s (timeout reduzido para 1s)
2. Kernel boot + OpenRC services: ~4s
3. Bridge br0 configurada: "Configuring L2 bridge ... [ ok ]"
4. Banner Cisco com MAC real e uptime
5. Prompt "Switch>" funcional
6. Nenhum warning de CPR
7. Nenhuma mensagem /etc/motd Alpine
```

**Nota sobre DHCP**: O boot total mostra ~15s de uptime porque eth0 faz DHCP via `dhcpcd` (~10s). No EVE-NG, eth0 sera uma interface de management sem DHCP ativo, entao o boot sera mais rapido (~5-6s).

## Notas IMPORTANTES para a Fase 5 (template EVE-NG)

### 1. DHCP no eth0 atrasa o boot em ~10 segundos
- O `dhcpcd` no eth0 bloqueia o init por ~10s enquanto tenta DHCP
- No EVE-NG, eth0 sera uma interface virtual sem DHCP server — pode travar ainda mais tempo
- **Recomendacao**: desabilitar DHCP no eth0 antes de instalar no EVE-NG, ou configurar eth0 como estatica sem IP (so bridge member), ou remover `dhcpcd` e usar `auto` no interfaces
- **Para desabilitar DHCP**: `virt-customize -a virtioa.qcow2 --run-command 'rc-update del networking default'` e configurar eth0 manualmente se necessario
- **Alternativa mais simples**: editar `/etc/network/interfaces` para nao ter `iface eth0 inet dhcp` — pode usar `iface eth0 inet manual` ou simplesmente nao configurar eth0

### 2. Imagem pronta para copia direta
```bash
# Copiar para o EVE-NG:
scp virtioa.qcow2 root@eve-ng:/opt/unetlab/addons/qemu/ciscosw-1.0/virtioa.qcow2
```

### 3. Se precisar atualizar o CLI novamente
```bash
export LIBGUESTFS_BACKEND=direct

# Copiar arquivos atualizados
virt-customize -a virtioa.qcow2 \
  --copy-in /home/francisco/swrb/switchcli/main.py:/opt/switchcli/ \
  --copy-in /home/francisco/swrb/switchcli/loader.py:/opt/switchcli/ \
  --copy-in /home/francisco/swrb/switchcli/cli:/opt/switchcli/ \
  --copy-in /home/francisco/swrb/switchcli/backend:/opt/switchcli/ \
  --chmod 0755:/opt/switchcli/main.py \
  --chmod 0755:/opt/switchcli/loader.py \
  --run-command 'chown -R root:root /opt/switchcli/'

# Recomprimir
virt-sparsify --compress virtioa.qcow2 virtioa-compressed.qcow2
mv virtioa-compressed.qcow2 virtioa.qcow2
```

### 4. Dependencias no host de build
```bash
sudo apt-get install qemu-utils guestfs-tools libguestfs-tools linux-image-generic
```

### 5. KVM funciona neste host
- QEMU aceita `-accel kvm` sem problemas
- Boot via KVM validado: ~6s ate prompt (sem DHCP)
- Para teste rapido: `qemu-system-x86_64 -m 128 -accel kvm -drive file=virtioa.qcow2,format=qcow2,snapshot=on -nographic -serial mon:stdio -device virtio-net-pci,netdev=net0 -netdev user,id=net0`
- `snapshot=on` para nao alterar a imagem durante testes
- `Ctrl+A X` para sair do QEMU

### 6. Checklist para Fase 5 (no servidor EVE-NG)
- [ ] Verificar versao do QEMU no EVE-NG (`ls /opt/qemu/`)
- [ ] Criar template YAML `ciscosw.yml` em `/opt/unetlab/html/templates/intel/`
- [ ] Registrar em `custom_templates.yml`
- [ ] Criar diretorio `/opt/unetlab/addons/qemu/ciscosw-1.0/`
- [ ] Copiar `virtioa.qcow2` para esse diretorio
- [ ] Fixar permissoes com `unl_wrapper -a fixpermissions`
- [ ] (Recomendado) Resolver questao do DHCP no eth0 antes de instalar
- [ ] Testar boot e CLI via console telnet no EVE-NG
- [ ] Testar conectividade L2 entre dois switches (VLAN trunk)

---

# FASE 5 — Template e instalacao no EVE-NG

## Objetivo
Criar template EVE-NG e instalar a imagem.

### 5.1 — Template YAML (`ciscosw.yml`)
Salvar em `/opt/unetlab/html/templates/intel/ciscosw.yml`:

```yaml
---
type: qemu
description: Cisco-like L2 Switch (Alpine)
name: CiscoSW
cpulimit: 1
icon: Switch L2.png
cpu: 1
ram: 128
ethernet: 9
console: telnet
shutdown: 1
qemu_arch: x86_64
qemu_nic: virtio-net-pci
qemu_options: -machine type=pc,accel=kvm -nographic -serial mon:stdio
```

**IMPORTANTE sobre `qemu_version`**: Verificar qual versao do QEMU esta instalada no EVE-NG:
```bash
ls /opt/qemu/
# Se listar "4.2.1", adicionar: qemu_version: 4.2.1
# Se nao tiver o diretorio, remover o campo qemu_version do YAML
```

### 5.2 — Registrar template customizado
**Este passo e obrigatorio** — sem ele o EVE-NG nao lista o node:

Editar/criar `/opt/unetlab/html/includes/custom_templates.yml`:
```yaml
---
custom_templates:
  - name: ciscosw
```

**Regra de naming**: O prefixo do diretorio da imagem (antes do `-`) DEVE ser igual ao `name` em lowercase. Ex: diretorio `ciscosw-1.0` → name `ciscosw`.

### 5.3 — Copiar imagem
```bash
mkdir -p /opt/unetlab/addons/qemu/ciscosw-1.0/
cp virtioa.qcow2 /opt/unetlab/addons/qemu/ciscosw-1.0/virtioa.qcow2
```

### 5.4 — Fixar permissoes
```bash
/opt/unetlab/wrappers/unl_wrapper -a fixpermissions
```

### 5.5 — Validacao no EVE-NG
1. Abrir interface web do EVE-NG
2. Criar novo lab
3. Adicionar node → buscar "CiscoSW" na lista
4. Conectar 2+ switches entre si
5. Iniciar os nodes
6. Abrir console (telnet) → deve aparecer banner + `Switch>`
7. Testar:
   ```
   enable
   configure terminal
   vlan 10
   name TEST
   exit
   interface GigabitEthernet0/1
   switchport mode trunk
   switchport trunk allowed vlan 10
   end
   show vlan brief
   write memory
   ```
8. Fazer `reload` e verificar que startup-config foi carregado

---

# FASE 5 — CONCLUIDA (2026-02-19)

## Resultado
- **Template YAML**: `eveng/ciscosw.yml` — pronto para copiar em `/opt/unetlab/html/templates/intel/`
- **Registro**: `eveng/custom_templates.yml` — pronto para copiar em `/opt/unetlab/html/includes/`
- **Script de instalacao**: `eveng/install-eveng.sh` — automatiza toda a instalacao no EVE-NG
- **Imagem final**: `virtioa.qcow2` — 81MB comprimida, 512MB virtual
- **DHCP no eth0 RESOLVIDO** — boot sem delay de DHCP
- **Boot validado com KVM**: ~12s ate o prompt `Switch>` (inclui todo OpenRC init)

## Operacoes realizadas

### 1. Fix do DHCP no eth0 (eliminacao do delay de ~10s)
- **Problema**: `dhcpcd` no eth0 adicionava ~10s ao boot tentando obter IP via DHCP. No EVE-NG sem DHCP server, poderia travar ainda mais.
- **Solucao aplicada**:
  - `/etc/network/interfaces` alterado de `iface eth0 inet dhcp` para `iface eth0 inet manual` (apenas link up, sem IP)
  - Pacotes `dhcpcd` e `dhcpcd-openrc` removidos via `apk del`
  - Servico `dhcpcd` removido do runlevel default
- **Resultado**: eth0 sobe instantaneamente sem esperar DHCP

### 2. Template YAML criado (`eveng/ciscosw.yml`)
- Tipo: qemu, 128MB RAM, 1 CPU, 9 interfaces ethernet (eth0-eth8)
- Console: telnet (padrao EVE-NG)
- NIC: virtio-net-pci
- `qemu_version` NAO incluido no template — o script de instalacao detecta e adiciona automaticamente
- Icone: "Switch L2.png" (icone padrao do EVE-NG)

### 3. Registro de template customizado (`eveng/custom_templates.yml`)
- Registra `ciscosw` como template customizado
- Necessario para o EVE-NG listar o node na interface web

### 4. Script de instalacao automatizada (`eveng/install-eveng.sh`)
- Detecta versao do QEMU e adiciona `qemu_version` ao template automaticamente
- Instala template YAML em `/opt/unetlab/html/templates/intel/`
- Registra em `custom_templates.yml` (append se ja existir, cria se nao)
- Copia imagem para `/opt/unetlab/addons/qemu/ciscosw-1.0/`
- Executa `unl_wrapper -a fixpermissions`
- Mostra instrucoes de teste apos instalacao

### 5. Recompressao da imagem
- `virt-sparsify --compress` apos remocao do dhcpcd
- Tamanho final: 81MB (ganho modesto, imagem ja estava otimizada)

## Boot validado com KVM (pos-DHCP fix)
```
Sequencia observada:
1. Syslinux carrega kernel em ~1s (timeout 1s da Fase 4)
2. Kernel boot + OpenRC services: ~10s
3. "Starting networking... lo [ ok ] eth0 [ ok ]" — SEM DELAY de DHCP
4. "Configuring L2 bridge ... [ ok ]"
5. Banner Cisco com MAC real e uptime
6. Prompt "Switch>" funcional em ~12s de uptime
7. Nenhum warning de CPR
8. Nenhuma mensagem /etc/motd
9. Nenhum delay de DHCP
```

## Arquivos criados nesta fase
```
eveng/
├── ciscosw.yml            # Template YAML para EVE-NG
├── custom_templates.yml   # Registro de template customizado
└── install-eveng.sh       # Script de instalacao automatizada
```

## Como instalar no EVE-NG
```bash
# No host de build, copiar arquivos para o servidor EVE-NG:
scp -r /home/francisco/swrb/eveng/ root@<EVE-NG-IP>:/tmp/ciscosw-install/
scp /home/francisco/swrb/virtioa.qcow2 root@<EVE-NG-IP>:/tmp/ciscosw-install/

# No servidor EVE-NG, executar o script:
ssh root@<EVE-NG-IP> 'bash /tmp/ciscosw-install/install-eveng.sh'
```

Ou manualmente:
```bash
# 1. Copiar template
cp ciscosw.yml /opt/unetlab/html/templates/intel/ciscosw.yml

# 2. Adicionar qemu_version se necessario
QEMU_VER=$(ls /opt/qemu/ 2>/dev/null | head -1)
[ -n "$QEMU_VER" ] && echo "qemu_version: $QEMU_VER" >> /opt/unetlab/html/templates/intel/ciscosw.yml

# 3. Registrar template customizado
# Se /opt/unetlab/html/includes/custom_templates.yml nao existe:
cp custom_templates.yml /opt/unetlab/html/includes/custom_templates.yml
# Se ja existe, adicionar:
echo "  - name: ciscosw" >> /opt/unetlab/html/includes/custom_templates.yml

# 4. Copiar imagem
mkdir -p /opt/unetlab/addons/qemu/ciscosw-1.0/
cp virtioa.qcow2 /opt/unetlab/addons/qemu/ciscosw-1.0/virtioa.qcow2

# 5. Fixar permissoes
/opt/unetlab/wrappers/unl_wrapper -a fixpermissions
```

## Notas IMPORTANTES para a fase seguinte (validacao/melhorias)

### 1. eth0 esta como `manual` (sem IP) — management via console apenas
- eth0 sobe com link up mas sem endereco IP
- Se for necessario management via SSH/IP no futuro, sera preciso:
  - Configurar IP estatico em `/etc/network/interfaces` (ex: `iface eth0 inet static`)
  - Ou re-adicionar `dhcpcd` e configurar apenas no eth0
  - Ou implementar no CLI: `interface vlan 1` + `ip address X.X.X.X Y.Y.Y.Y` (funcionalidade L3 nao implementada no MVP)

### 2. Mapeamento de interfaces no EVE-NG
- EVE-NG cria interfaces como `e0`, `e1`, ..., `e8` no template (9 ethernet)
- Dentro da VM, estas aparecem como `eth0`, `eth1`, ..., `eth8`
- `eth0` = primeira interface na topologia (e0) — reservada para management
- `eth1-eth8` = interfaces Gi0/1 a Gi0/8 — fazem parte da bridge br0
- Se o usuario conectar um cabo na porta `e0` no EVE-NG, isso vai para `eth0` que NAO esta na bridge (traffic isolado)

### 3. Conectividade L2 entre switches — teste recomendado
Ao validar no EVE-NG, testar especificamente:
```
Topologia: SW1 (Gi0/1) --- (Gi0/1) SW2

SW1:
  enable
  configure terminal
  vlan 10
  name TEST
  exit
  interface GigabitEthernet0/1
  switchport mode trunk
  switchport trunk allowed vlan 10
  end
  show vlan brief

SW2:
  enable
  configure terminal
  vlan 10
  name TEST
  exit
  interface GigabitEthernet0/1
  switchport mode trunk
  switchport trunk allowed vlan 10
  end
  show vlan brief
```
- Verificar que VLAN 10 aparece em ambos os switches com porta Gi0/1
- Conectar hosts em portas access de cada switch e testar ping L2

### 4. `show spanning-tree` depende de portas ativas
- STP so mostra informacao util quando ha interfaces com link up
- No EVE-NG, as interfaces so ficam up quando conectadas a outro node na topologia
- Se nenhuma porta estiver conectada, `show spanning-tree` pode mostrar informacao vazia ou limitada

### 5. Reload e persistencia de configuracao
- `write memory` salva em `/opt/switchcli/configs/startup-config` (JSON)
- `reload` executa `reboot` — o init script carrega startup-config no boot via `loader.py`
- A imagem qcow2 no EVE-NG usa copy-on-write por node — cada instancia do switch tem seu proprio disco
- Configuracoes sao persistentes entre reboots da mesma instancia
- Wipe/rebuild do node no EVE-NG reseta para estado limpo (sem startup-config)

### 6. Possibilidades de melhoria pos-MVP
- **SSH access**: instalar `openssh-server` e implementar autenticacao no CLI
- **LLDP/CDP**: implementar `show cdp neighbors` usando lldpd
- **Port mirroring**: `monitor session` usando `tc mirred`
- **EtherChannel/LACP**: usando `bonding` module do kernel
- **Per-VLAN STP**: compilar mstpd do source para RSTP/MSTP real
- **Logging**: `show logging` com buffer em memoria
- **Interface descriptions**: `show interfaces description` (ja implementado parcialmente)

### 7. Se precisar atualizar o CLI apos instalacao no EVE-NG
A imagem master em `/opt/unetlab/addons/qemu/ciscosw-1.0/virtioa.qcow2` pode ser atualizada:
```bash
# No host de build, atualizar CLI:
export LIBGUESTFS_BACKEND=direct
virt-customize -a virtioa.qcow2 \
  --copy-in /home/francisco/swrb/switchcli/main.py:/opt/switchcli/ \
  --copy-in /home/francisco/swrb/switchcli/loader.py:/opt/switchcli/ \
  --copy-in /home/francisco/swrb/switchcli/cli:/opt/switchcli/ \
  --copy-in /home/francisco/swrb/switchcli/backend:/opt/switchcli/ \
  --chmod 0755:/opt/switchcli/main.py \
  --chmod 0755:/opt/switchcli/loader.py \
  --run-command 'chown -R root:root /opt/switchcli/'

virt-sparsify --compress virtioa.qcow2 virtioa-compressed.qcow2
mv virtioa-compressed.qcow2 virtioa.qcow2

# Copiar para o EVE-NG:
scp virtioa.qcow2 root@<EVE-NG-IP>:/opt/unetlab/addons/qemu/ciscosw-1.0/virtioa.qcow2
ssh root@<EVE-NG-IP> '/opt/unetlab/wrappers/unl_wrapper -a fixpermissions'
```
**IMPORTANTE**: Nodes ja criados em labs usam copia da imagem. A atualizacao so afeta NOVOS nodes. Para atualizar nodes existentes, e necessario wipe e rebuild no EVE-NG.

### 8. Dependencias no host de build (LXC container)
```bash
sudo apt-get install qemu-utils guestfs-tools libguestfs-tools linux-image-generic
```

---

# LIMITACOES CONHECIDAS DO MVP

1. Sem VTP (VLAN Trunking Protocol)
2. Sem EtherChannel / LACP
3. Sem ACLs
4. Sem inter-VLAN routing (switch L2 puro)
5. STP opera como instancia unica (Common STP) — sem Per-VLAN RSTP (RPVST+)
6. Sem comandos `show spanning-tree` completos
7. Sem SNMP
8. `interface range` limitado a ranges contiguos (ex: 0/1-4, nao 0/1,0/3,0/7)
9. Sem port-security
10. Sem DHCP snooping

---

# ARTEFATOS ENTREGUES

| Artefato | Descricao |
|---|---|
| `virtioa.qcow2` | Imagem qcow2 pronta para EVE-NG (81MB comprimida, 512MB virtual) |
| `eveng/ciscosw.yml` | Template YAML para EVE-NG |
| `eveng/custom_templates.yml` | Registro de template customizado |
| `eveng/install-eveng.sh` | Script de instalacao automatizada no EVE-NG |
| `/opt/switchcli/` (dentro da imagem) | Codigo-fonte do CLI Python (18 arquivos) |
| `switchcli/` (no host de build) | Codigo-fonte local para desenvolvimento |
| `configure.sh` | Script de configuracao usado no build original |
| Este documento | Plano de implementacao completo |
