#!/usr/bin/env python3
"""Entry point do CLI do switch."""

import getpass
import sys
import os
import signal

# Garantir que imports relativos funcionem de qualquer diretorio
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

# Suprimir warning de CPR (Cursor Position Request) do prompt_toolkit
# Console serial (ttyS0) nao suporta CPR — sem isso aparece warning no boot
os.environ["PROMPT_TOOLKIT_NO_CPR"] = "1"

from cli.banner import print_banner
from cli.engine import CLIEngine, LogoffSignal

_MAX_LOGIN_ATTEMPTS = 3
_DEFAULT_USER = "admin"


def _do_login(config_store):
    """Exibe prompt de login estilo Cisco IOS.

    Comportamento:
    - Sem usuarios configurados: login com 'admin' + senha em branco.
      Apos entrar, exibe aviso para configurar uma senha real.
    - Com usuarios configurados: exige username e password validos.
      3 tentativas invalidas encerram a sessao.
    """
    print("\nUser Access Verification\n")

    using_default = not config_store.local_users

    for attempt in range(1, _MAX_LOGIN_ATTEMPTS + 1):
        try:
            username = input("Username: ").strip()
            password = getpass.getpass("Password: ")
        except (EOFError, KeyboardInterrupt):
            print()
            sys.exit(0)

        if using_default:
            # Credenciais padrao de fabrica: admin / (sem senha)
            if username == _DEFAULT_USER and password == "":
                return True
        else:
            if config_store.verify_user(username, password):
                return True

        print("% Login invalid")
        if attempt < _MAX_LOGIN_ATTEMPTS:
            print()

    print("\n% Bad secrets\n")
    sys.exit(1)


def _show_login_and_banner(engine, show_boot_banner=False):
    """Executa login, exibe aviso de credencial padrao e banner MOTD."""
    if show_boot_banner:
        print_banner()

    _do_login(engine.config_store)

    # Aviso de credenciais padrao (sem senha configurada)
    if not engine.config_store.local_users:
        print()
        print("% WARNING: No local users configured. Default credentials in use.")
        print("%          Please set a password: username admin password <password>")
        print()

    # Banner MOTD (se configurado)
    if engine.config_store.banner_motd:
        print()
        print(engine.config_store.banner_motd)
        print()


def main():
    # Ignorar Ctrl+Z (SIGTSTP) para nao cair no shell Linux
    signal.signal(signal.SIGTSTP, signal.SIG_IGN)

    engine = CLIEngine()
    first_run = True

    # Loop de sessao: cada logoff volta para a tela de login
    while True:
        _show_login_and_banner(engine, show_boot_banner=first_run)
        first_run = False

        # Resetar estado do CLI para USER_EXEC
        engine.mode = "USER_EXEC"
        engine.current_interfaces = []
        engine.current_vlan = None
        engine.current_svi = None
        engine.current_management = False

        try:
            engine.run()
        except LogoffSignal:
            # Logoff: volta para login
            print()
            continue
        except KeyboardInterrupt:
            print()
            continue


if __name__ == "__main__":
    main()
