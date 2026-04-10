#!/bin/bash
# Deploy: injeta arquivos do swrb-v2 na imagem qcow2
set -e

IMAGE=/opt/unetlab/addons/qemu/swrb-v2/virtioa.qcow2
SRC=/root/swrb-v2/switchcli

echo '[1/2] Injetando arquivos na imagem...'
LIBGUESTFS_BACKEND=direct guestfish -a $IMAGE -i <<GFEOF
# Backend
copy-in $SRC/backend/__init__.py /opt/switchcli/backend/
copy-in $SRC/backend/bridge.py /opt/switchcli/backend/
copy-in $SRC/backend/config_store.py /opt/switchcli/backend/
copy-in $SRC/backend/interface.py /opt/switchcli/backend/
copy-in $SRC/backend/vlan.py /opt/switchcli/backend/
copy-in $SRC/backend/ip_mgmt.py /opt/switchcli/backend/
# CLI core
copy-in $SRC/main.py /opt/switchcli/
copy-in $SRC/loader.py /opt/switchcli/
copy-in $SRC/cli/__init__.py /opt/switchcli/cli/
copy-in $SRC/cli/banner.py /opt/switchcli/cli/
copy-in $SRC/cli/engine.py /opt/switchcli/cli/
copy-in $SRC/cli/parser.py /opt/switchcli/cli/
copy-in $SRC/cli/completer.py /opt/switchcli/cli/
# Commands
copy-in $SRC/cli/commands/__init__.py /opt/switchcli/cli/commands/
copy-in $SRC/cli/commands/show.py /opt/switchcli/cli/commands/
copy-in $SRC/cli/commands/interface.py /opt/switchcli/cli/commands/
copy-in $SRC/cli/commands/config.py /opt/switchcli/cli/commands/
copy-in $SRC/cli/commands/system.py /opt/switchcli/cli/commands/
copy-in $SRC/cli/commands/vlan.py /opt/switchcli/cli/commands/
GFEOF

echo '[2/2] Corrigindo permissoes do EVE-NG...'
/opt/unetlab/wrappers/unl_wrapper -a fixpermissions 2>/dev/null || true

echo 'Deploy concluido!'
