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

# NOTA: Alpine nao tem o pacote 'agetty' (util-linux).
# Usar busybox getty com script de autologin.
mkdir -p /usr/local/bin
cat > /usr/local/bin/autologin <<'AUTOLOGIN'
#!/bin/sh
exec /bin/login -f root
AUTOLOGIN
chmod +x /usr/local/bin/autologin

echo 'ttyS0::respawn:/sbin/getty -n -l /usr/local/bin/autologin 115200 ttyS0 vt100' >> /etc/inittab

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
rc-update del chronyd default 2>/dev/null || true
rc-update del tiny-cloud-early default 2>/dev/null || true
rc-update del tiny-cloud-final default 2>/dev/null || true
rc-update del tiny-cloud-main default 2>/dev/null || true

# -------------------------------------------------------
# 4. Habilitar IP forwarding DESABILITADO (e switch, nao router)
# -------------------------------------------------------
echo 'net.ipv4.ip_forward = 0' > /etc/sysctl.d/switch.conf
echo 'net.ipv6.conf.all.forwarding = 0' >> /etc/sysctl.d/switch.conf

# -------------------------------------------------------
# 5. Script de inicializacao do switch
# -------------------------------------------------------
# NOTA: mstpd NAO esta disponivel nos repos Alpine.
# O STP do kernel (stp_state 1) e usado no lugar.
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

    # Habilitar STP na bridge (kernel built-in, sem mstpd)
    ip link set br0 type bridge stp_state 1

    # Carregar startup-config se existir
    if [ -f /opt/switchcli/configs/startup-config ]; then
        /usr/bin/python3 /opt/switchcli/loader.py /opt/switchcli/configs/startup-config &
    fi

    eend 0
}

stop() {
    ebegin "Stopping L2 bridge"
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
