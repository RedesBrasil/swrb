# SWRB - Switch L2 Cisco-like para EVE-NG

Imagem QEMU de um switch L2 com CLI Cisco-like (estilo Catalyst 2960), construida sobre Alpine Linux, pronta para uso no EVE-NG.

## Caracteristicas

- CLI interativo com prompt Cisco IOS (User EXEC, Privileged EXEC, Global Config, Interface Config, VLAN Config)
- Abreviacoes de comandos estilo Cisco (`sh vl br`, `conf t`, `int gi0/1`, `wr`)
- Tab completion e help contextual com `?`
- VLAN management com bridge VLAN filtering do kernel Linux
- STP (802.1D) via kernel built-in
- Switchport access e trunk (802.1Q tagging)
- Persistencia de configuracao (write memory / copy running-config startup-config)
- Banner de boot estilo Cisco 2960
- Boot em ~6 segundos (com KVM)
- Consumo de apenas 128MB de RAM

## Especificacoes

| Item | Valor |
|---|---|
| Base OS | Alpine Linux 3.21 |
| Imagem | qcow2, ~81MB comprimida, 512MB virtual |
| RAM | 128MB |
| Interfaces | 9 (eth0 management + eth1-eth8 como Gi0/1 a Gi0/8) |
| Console | Serial (ttyS0 115200) / Telnet via EVE-NG |
| CLI Runtime | Python 3 + prompt_toolkit |

## Estrutura do Projeto

```
swrb/
├── switchcli/                # Codigo-fonte do CLI Python
│   ├── main.py               # Entry point
│   ├── loader.py             # Carrega startup-config no boot
│   ├── cli/
│   │   ├── engine.py         # Maquina de estados (5 modos CLI)
│   │   ├── parser.py         # Parser de comandos + abreviacoes
│   │   ├── completer.py      # Tab completion + ? help
│   │   ├── banner.py         # Banner de boot estilo Cisco
│   │   └── commands/
│   │       ├── show.py       # show vlan, mac, interfaces, running-config
│   │       ├── config.py     # hostname, enable password
│   │       ├── interface.py  # switchport mode/access/trunk, shutdown
│   │       ├── vlan.py       # vlan name
│   │       └── system.py     # write memory, reload
│   └── backend/
│       ├── bridge.py         # Mapeamento Cisco <-> Linux
│       ├── vlan.py           # Gerencia VLANs no kernel
│       ├── interface.py      # Controle de interfaces
│       └── config_store.py   # Persistencia de configuracao
├── eveng/                    # Arquivos para instalacao no EVE-NG
│   ├── ciscosw.yml           # Template YAML
│   ├── custom_templates.yml  # Registro de template customizado
│   └── install-eveng.sh      # Script de instalacao automatizada
├── configure.sh              # Script de configuracao da imagem Alpine
└── plano.md                  # Documentacao completa do projeto
```

## Comandos Suportados

### User EXEC (`Switch>`)
- `enable` - Entrar em modo privilegiado
- `show vlan brief` - Listar VLANs e portas
- `show mac address-table` - Tabela MAC
- `show interfaces status` - Status das portas
- `show interfaces trunk` - Portas trunk
- `show running-config` / `show startup-config`
- `show spanning-tree` / `show version`

### Privileged EXEC (`Switch#`)
- `configure terminal` - Entrar em modo de configuracao
- `write memory` - Salvar configuracao
- `copy running-config startup-config`
- `reload` - Reiniciar o switch

### Global Config (`Switch(config)#`)
- `hostname <name>` - Alterar hostname
- `enable password <pw>` - Definir senha
- `vlan <id>` / `no vlan <id>` - Criar/remover VLAN
- `interface GigabitEthernet0/<0-8>` - Configurar interface
- `interface range GigabitEthernet0/<start>-<end>` - Configurar multiplas interfaces

### Interface Config (`Switch(config-if)#`)
- `switchport mode access` / `switchport mode trunk`
- `switchport access vlan <id>`
- `switchport trunk allowed vlan <id-list>`
- `switchport trunk native vlan <id>`
- `shutdown` / `no shutdown`

## Instalacao no EVE-NG

### Automatica (recomendada)
```bash
# Copiar arquivos para o servidor EVE-NG
scp -r eveng/ root@<EVE-NG-IP>:/tmp/ciscosw-install/
scp virtioa.qcow2 root@<EVE-NG-IP>:/tmp/ciscosw-install/

# Executar script de instalacao
ssh root@<EVE-NG-IP> 'bash /tmp/ciscosw-install/install-eveng.sh'
```

### Manual
```bash
# 1. Copiar template
cp eveng/ciscosw.yml /opt/unetlab/html/templates/intel/

# 2. Registrar template
cp eveng/custom_templates.yml /opt/unetlab/html/includes/

# 3. Copiar imagem
mkdir -p /opt/unetlab/addons/qemu/ciscosw-1.0/
cp virtioa.qcow2 /opt/unetlab/addons/qemu/ciscosw-1.0/

# 4. Fixar permissoes
/opt/unetlab/wrappers/unl_wrapper -a fixpermissions
```

## Build da Imagem

### Pre-requisitos (host de build)
```bash
sudo apt-get install qemu-utils guestfs-tools libguestfs-tools linux-image-generic
```

### Rebuild
A imagem base e construida a partir de uma imagem Alpine Linux cloud (generic_alpine bios-tiny) customizada com `virt-customize` do libguestfs-tools. Consulte [plano.md](plano.md) para o processo completo de build.

### Atualizar apenas o CLI
```bash
export LIBGUESTFS_BACKEND=direct

virt-customize -a virtioa.qcow2 \
  --copy-in switchcli/main.py:/opt/switchcli/ \
  --copy-in switchcli/loader.py:/opt/switchcli/ \
  --copy-in switchcli/cli:/opt/switchcli/ \
  --copy-in switchcli/backend:/opt/switchcli/ \
  --chmod 0755:/opt/switchcli/main.py \
  --chmod 0755:/opt/switchcli/loader.py

virt-sparsify --compress virtioa.qcow2 virtioa-compressed.qcow2
mv virtioa-compressed.qcow2 virtioa.qcow2
```

## Limitacoes

- Sem VTP, EtherChannel/LACP, ACLs, SNMP
- Switch L2 puro (sem inter-VLAN routing)
- STP basico (802.1D) - sem RSTP/MSTP
- Sem port-security ou DHCP snooping
- `interface range` limitado a ranges contiguos

## Licenca

Uso interno.
