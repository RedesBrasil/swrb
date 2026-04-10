#!/usr/bin/env python3
"""Entry point do CLI do switch."""

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


def main():
    # Ignorar Ctrl+Z (SIGTSTP) para nao cair no shell Linux
    signal.signal(signal.SIGTSTP, signal.SIG_IGN)

    print_banner()
    engine = CLIEngine()

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
