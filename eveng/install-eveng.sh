#!/bin/bash
# =============================================================
# install-eveng.sh — Instala o switch Cisco-like no EVE-NG
# =============================================================
# Executar como root no servidor EVE-NG:
#   scp -r eveng/ root@eve-ng:/tmp/ciscosw-install/
#   scp virtioa.qcow2 root@eve-ng:/tmp/ciscosw-install/
#   ssh root@eve-ng 'bash /tmp/ciscosw-install/install-eveng.sh'
# =============================================================
set -e

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
TEMPLATE_NAME="ciscosw"
TEMPLATE_DIR="/opt/unetlab/html/templates/intel"
CUSTOM_TEMPLATES="/opt/unetlab/html/includes/custom_templates.yml"
# Imagem atual do SWRB. Outras imagens (ciscosw-1.0, ciscosw-swrb-aprimorado)
# podem coexistir no mesmo diretorio pai; o EVE-NG lista todas que casam
# com o padrao "ciscosw-*" no seletor de imagens do template.
IMAGE_DIR="/opt/unetlab/addons/qemu/ciscosw-swrb-v2"
IMAGE_FILE="virtioa.qcow2"

echo "========================================="
echo " Instalando CiscoSW-L2 Switch no EVE-NG"
echo "========================================="

# 1. Verificar que estamos no EVE-NG
if [ ! -d /opt/unetlab ]; then
    echo "ERRO: /opt/unetlab nao encontrado. Este script deve ser executado no servidor EVE-NG."
    exit 1
fi

# 2. Verificar que a imagem existe
if [ ! -f "${SCRIPT_DIR}/${IMAGE_FILE}" ]; then
    # Tentar um nivel acima (caso o script esteja em eveng/ e a imagem em ../)
    if [ -f "${SCRIPT_DIR}/../${IMAGE_FILE}" ]; then
        IMAGE_SOURCE="${SCRIPT_DIR}/../${IMAGE_FILE}"
    else
        echo "ERRO: ${IMAGE_FILE} nao encontrado em ${SCRIPT_DIR}/ nem em ${SCRIPT_DIR}/../"
        echo "Copie a imagem para o mesmo diretorio do script ou para o diretorio pai."
        exit 1
    fi
else
    IMAGE_SOURCE="${SCRIPT_DIR}/${IMAGE_FILE}"
fi

# 3. Detectar versao do QEMU
echo ""
echo "[1/5] Detectando versao do QEMU..."
QEMU_VERSION=""
if [ -d /opt/qemu ]; then
    QEMU_VERSION=$(ls /opt/qemu/ 2>/dev/null | head -1)
    if [ -n "$QEMU_VERSION" ]; then
        echo "  QEMU encontrado: /opt/qemu/${QEMU_VERSION}"
    fi
fi

# 4. Instalar template YAML
echo ""
echo "[2/5] Instalando template YAML..."
mkdir -p "${TEMPLATE_DIR}"
cp "${SCRIPT_DIR}/ciscosw.yml" "${TEMPLATE_DIR}/${TEMPLATE_NAME}.yml"

# Adicionar qemu_version se detectado
if [ -n "$QEMU_VERSION" ]; then
    echo "qemu_version: ${QEMU_VERSION}" >> "${TEMPLATE_DIR}/${TEMPLATE_NAME}.yml"
    echo "  qemu_version: ${QEMU_VERSION} adicionado ao template"
fi
echo "  Template instalado em: ${TEMPLATE_DIR}/${TEMPLATE_NAME}.yml"

# 5. Registrar template customizado
echo ""
echo "[3/5] Registrando template customizado..."
if [ -f "${CUSTOM_TEMPLATES}" ]; then
    # Verificar se ja esta registrado
    if grep -q "name: ${TEMPLATE_NAME}" "${CUSTOM_TEMPLATES}" 2>/dev/null; then
        echo "  Template '${TEMPLATE_NAME}' ja registrado em ${CUSTOM_TEMPLATES}"
    else
        # Adicionar ao arquivo existente
        echo "  - name: ${TEMPLATE_NAME}" >> "${CUSTOM_TEMPLATES}"
        echo "  Adicionado '${TEMPLATE_NAME}' ao ${CUSTOM_TEMPLATES} existente"
    fi
else
    cp "${SCRIPT_DIR}/custom_templates.yml" "${CUSTOM_TEMPLATES}"
    echo "  Criado ${CUSTOM_TEMPLATES}"
fi

# 6. Copiar imagem
echo ""
echo "[4/5] Copiando imagem qcow2..."
mkdir -p "${IMAGE_DIR}"
cp "${IMAGE_SOURCE}" "${IMAGE_DIR}/${IMAGE_FILE}"
echo "  Imagem copiada para: ${IMAGE_DIR}/${IMAGE_FILE}"
echo "  Tamanho: $(du -h "${IMAGE_DIR}/${IMAGE_FILE}" | cut -f1)"

# 7. Fixar permissoes
echo ""
echo "[5/5] Fixando permissoes..."
/opt/unetlab/wrappers/unl_wrapper -a fixpermissions
echo "  Permissoes fixadas"

# Resumo
echo ""
echo "========================================="
echo " Instalacao concluida com sucesso!"
echo "========================================="
echo ""
echo "Template: ${TEMPLATE_DIR}/${TEMPLATE_NAME}.yml"
echo "Imagem:   ${IMAGE_DIR}/${IMAGE_FILE}"
echo ""
echo "Proximos passos:"
echo "  1. Abra a interface web do EVE-NG"
echo "  2. Crie um novo lab"
echo "  3. Adicione node -> busque 'CiscoSW' na lista"
echo "  4. Conecte 2+ switches entre si"
echo "  5. Inicie os nodes e abra o console (telnet)"
echo "  6. Deve aparecer o banner Cisco + prompt 'Switch>'"
echo ""
echo "Teste rapido:"
echo "  enable"
echo "  configure terminal"
echo "  vlan 10"
echo "  name TEST"
echo "  exit"
echo "  interface GigabitEthernet0/1"
echo "  switchport mode trunk"
echo "  switchport trunk allowed vlan 10"
echo "  end"
echo "  show vlan brief"
echo "  write memory"
echo ""
