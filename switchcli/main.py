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
from cli.engine import CLIEngine

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


def main():
    # Ignorar Ctrl+Z (SIGTSTP) para nao cair no shell Linux
    signal.signal(signal.SIGTSTP, signal.SIG_IGN)

    print_banner()
    engine = CLIEngine()

    # Login
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

    try:
        engine.run()
    except (EOFError, KeyboardInterrupt):
        print("\n")
        sys.exit(0)


if __name__ == "__main__":
    main()
