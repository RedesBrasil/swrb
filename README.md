# SWRB - Switch L2 Cisco-like para EVE-NG

Imagem QEMU de um switch L2 com CLI Cisco-like (estilo Catalyst 2960), construida sobre Alpine Linux, pronta para uso no EVE-NG.

## Caracteristicas

- CLI interativo com prompt Cisco IOS (User EXEC, Privileged EXEC, Global Config, Interface Config, VLAN Config)
- Abreviacoes de comandos estilo Cisco (`sh vl br`, `conf t`, `int gi0/1`, `wr`)
- Tab completion e help contextual com `?`
- VLAN management com bridge VLAN filtering do kernel Linux
- Gerencia de IP: SVIs (interface VlanX), ip default-gateway
- STP (802.1D) via kernel built-in
- Switchport access e trunk (802.1Q) com controle granular de VLANs permitidas
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
├── switchcli/                 # Codigo-fonte do CLI Python
│   ├── main.py                # Entry point
│   ├── loader.py              # Carrega startup-config no boot
│   ├── cli/
│   │   ├── engine.py          # Maquina de estados (5 modos CLI)
│   │   ├── parser.py          # Parser de comandos + abreviacoes
│   │   ├── completer.py       # Tab completion + ? help
│   │   ├── banner.py          # Banner de boot estilo Cisco
│   │   └── commands/
│   │       ├── show.py        # Todos os comandos show
│   │       ├── config.py      # hostname, enable password, ip default-gateway
│   │       ├── interface.py   # switchport, shutdown, SVI IP
│   │       ├── vlan.py        # vlan name
│   │       └── system.py      # write memory, reload
│   └── backend/
│       ├── bridge.py          # Mapeamento Cisco <-> Linux + interface range
│       ├── vlan.py            # Gerencia VLANs no kernel
│       ├── interface.py       # Controle de interfaces fisicas
│       ├── ip_mgmt.py         # Gerencia de SVIs e rotas (ip link/addr/route)
│       └── config_store.py    # Persistencia de configuracao
├── eveng/                     # Arquivos para instalacao no EVE-NG
│   └── ciscosw.yml            # Template YAML (referencia)
├── deploy.sh                  # Injeta arquivos Python na imagem via guestfish
└── configure.sh               # Script de configuracao inicial da imagem Alpine
```

## Comandos Suportados

### User EXEC (`Switch>`)
```
enable                              Entrar em modo privilegiado
show vlan brief                     Listar VLANs e portas associadas
show mac address-table              Tabela de MACs aprendidos
show interfaces status              Status resumido das portas
show interfaces trunk               Portas trunk e VLANs permitidas
show ip interface brief             IPs de todas as interfaces (fisicas + SVIs)
show arp                            Tabela ARP das SVIs
show running-config                 Configuracao ativa
show running-config interface <if>  Configuracao de interface especifica
show startup-config                 Configuracao salva
show spanning-tree                  Informacoes do STP
show version                        Versao do sistema
show ip route                       Tabela de roteamento
show logging                        Logs do sistema
show lldp                           Status global do LLDP (parcial - ver Limitacoes)
show lldp neighbors                 Vizinhos LLDP detectados
show lldp neighbors detail          Detalhes dos vizinhos LLDP
show lldp interface                 Status LLDP por interface
```

### Privileged EXEC (`Switch#`)
```
configure terminal                  Entrar em modo de configuracao global
ping <ip>                           Enviar 5 pings estilo Cisco
ping <ip> repeat <n>                Enviar N pings
write memory                        Salvar configuracao
copy running-config startup-config  Salvar configuracao
reload                              Reiniciar o switch (pede confirmacao)
write erase                         Apagar startup-config
erase startup-config                Apagar startup-config
clear mac address-table dynamic     Limpar tabela de MACs
show ...                            Todos os comandos show acima
```

### Global Config (`Switch(config)#`)
```
hostname <name>                     Alterar hostname
enable password <pw>                Definir senha de enable
vlan <id>                           Criar VLAN e entrar em VLAN config
no vlan <id>                        Remover VLAN e limpar portas automaticamente
interface GigabitEthernet0/<1-8>    Configurar interface fisica
interface Vlan<id>                  Criar/configurar SVI (interface L3)
no interface Vlan<id>               Remover SVI completamente
interface range Gi0/<x>-<y>        Configurar multiplas interfaces
interface range Gi0/<x>-<y>,Gi0/<z>-<w>  Range com multiplos segmentos
ip default-gateway <ip>             Definir gateway padrao
no ip default-gateway               Remover gateway padrao
do <comando>                        Executar comando privilegiado em qualquer modo config
ip route <rede> <mascara> <gw>      Adicionar rota estatica
no ip route <rede> <mascara>        Remover rota estatica
banner motd <delim><texto><delim>   Mensagem de login
no banner motd                      Remover mensagem de login
lldp run                            Habilitar LLDP globalmente (parcial - ver Limitacoes)
no lldp run                         Desabilitar LLDP
lldp timer <segundos>               Intervalo de transmissao LLDP (padrao 30s)
lldp holdtime <segundos>            Holdtime LLDP (padrao 120s)
lldp reinit <segundos>              Delay de reinit LLDP (padrao 2s)
spanning-tree mode pvst|rapid-pvst|none  Modo STP
errdisable recovery cause <causa>   Habilitar recuperacao de err-disabled
errdisable recovery interval <seg>  Intervalo de recuperacao
```

### Interface Config - Porta Fisica (`Switch(config-if)#`)
```
switchport mode access              Modo de acesso
switchport mode trunk               Modo trunk
switchport access vlan <id>         Definir VLAN de acesso
no switchport access vlan           Voltar para VLAN 1
switchport trunk native vlan <id>   VLAN nativa do trunk
switchport trunk allowed vlan <lista>         Definir VLANs permitidas
switchport trunk allowed vlan add <lista>     Adicionar VLANs
switchport trunk allowed vlan remove <lista>  Remover VLANs
switchport trunk allowed vlan except <lista>  Todas exceto as listadas
switchport trunk allowed vlan none            Nenhuma VLAN
switchport trunk allowed vlan all             Todas as VLANs
description <texto>                 Descricao da interface
shutdown / no shutdown              Desativar / Ativar porta
speed auto|10|100|1000              Velocidade da interface
duplex auto|full|half               Modo duplex
lldp transmit / no lldp transmit    Habilitar/desabilitar envio LLDP
lldp receive / no lldp receive      Habilitar/desabilitar recepcao LLDP
```

### Interface Config - SVI (`Switch(config-if)#`)
```
ip address <ip> <mask>              Atribuir endereco IP
no ip address                       Remover endereco IP
shutdown / no shutdown              Desativar / Ativar SVI
description <texto>                 Descricao da SVI
```

### Interface Config - Management0 (`Switch(config-if)#`)
```
ip address <ip> <mask>              Configurar IP estatico na porta OOB
ip address dhcp                     Obter IP via DHCP na porta OOB
no ip address                       Remover IP
shutdown / no shutdown              Desativar / Ativar porta de gerencia
description <texto>                 Descricao
```

### VLAN Config (`Switch(config-vlan)#`)
```
name <nome>                         Nomear a VLAN
```

## Mapeamento de Interfaces

| EVE-NG | Linux | CLI Cisco |
|--------|-------|-----------|
| e0 | eth0 | Management (fora do bridge) |
| e1 | eth1 | GigabitEthernet0/1 |
| e2 | eth2 | GigabitEthernet0/2 |
| ... | ... | ... |
| e8 | eth8 | GigabitEthernet0/8 |

> **Nota:** eth0 e reservado para gerencia do EVE-NG. Conecte dispositivos a partir de e1.

## Instalacao no EVE-NG

### Pre-requisitos
```bash
# No servidor EVE-NG
apt-get install -y libguestfs-tools
```

### Instalacao
```bash
# 1. Copiar template
cp eveng/swrb.yml /opt/unetlab/html/templates/intel/

# 2. Criar diretorio e copiar imagem
mkdir -p /opt/unetlab/addons/qemu/swrb-v2/
cp virtioa.qcow2 /opt/unetlab/addons/qemu/swrb-v2/

# 3. Fixar permissoes
/opt/unetlab/wrappers/unl_wrapper -a fixpermissions
```

### Atualizar o CLI (deploy)

Apos modificar arquivos Python no servidor:
```bash
bash deploy.sh
```

O script injeta todos os arquivos Python na imagem qcow2 via `guestfish` sem precisar iniciar a VM. Apos o deploy, wipe + restart o no no EVE-NG.

## Exemplo de Configuracao

```
Switch> enable
Switch# configure terminal
Switch(config)# hostname Core-SW
Core-SW(config)# vlan 10
Core-SW(config-vlan)# name PRODUCAO
Core-SW(config-vlan)# exit
Core-SW(config)# interface Gi0/1
Core-SW(config-if)# switchport mode trunk
Core-SW(config-if)# switchport trunk allowed vlan add 10,20
Core-SW(config-if)# exit
Core-SW(config)# interface Vlan10
Core-SW(config-if)# ip address 192.168.10.1 255.255.255.0
Core-SW(config-if)# no shutdown
Core-SW(config-if)# exit
Core-SW(config)# ip default-gateway 192.168.10.254
Core-SW(config)# end
Core-SW# write memory
```

## Limitacoes

- Sem VTP, EtherChannel/LACP, ACLs, SNMP
- Switch L2 puro: IP somente em SVIs (interface VlanX), nao em portas fisicas
- STP basico (802.1D) — sem RSTP/MSTP configuravel
- Sem port-security ou DHCP snooping
- `duplex` / `speed` sem efeito pratico em ambiente QEMU
- **LLDP parcialmente implementado:** comandos CLI funcionam (lldp run, show lldp, timers, tx/rx por porta), mas o daemon lldpd nao inicializa corretamente na VM — vizinhos nao sao detectados. Em investigacao.

## Licenca

Uso interno.
