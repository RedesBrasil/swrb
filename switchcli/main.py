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


def _do_login(config_store):
    """Exibe prompt de login estilo Cisco IOS.

    Retorna True se autenticado (ou se nao ha usuarios configurados).
    Encerra o processo apos _MAX_LOGIN_ATTEMPTS falhas.
    """
    if not config_store.local_users:
        # Sem usuarios configurados — acesso direto (comportamento padrao Cisco)
        print("\nPress RETURN to get started.\n")
        try:
            input()
        except (EOFError, KeyboardInterrupt):
            pass
        return True

    print("\nUser Access Verification\n")
    for attempt in range(1, _MAX_LOGIN_ATTEMPTS + 1):
        try:
            username = input("Username: ").strip()
            password = getpass.getpass("Password: ")
        except (EOFError, KeyboardInterrupt):
            print()
            sys.exit(0)

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

    # Login (antes do banner MOTD — comportamento Cisco)
    _do_login(engine.config_store)

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
