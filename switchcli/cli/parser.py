"""
Parser de comandos com suporte a abreviacoes estilo Cisco IOS.
'sh vl br' -> 'show vlan brief'
'conf t'   -> 'configure terminal'
"""


class AmbiguousCommand(Exception):
    def __init__(self, token, matches):
        self.token = token
        self.matches = matches
        super().__init__(
            f"% Ambiguous command:  \"{token}\"")


class InvalidCommand(Exception):
    def __init__(self, token):
        self.token = token
        super().__init__(
            f"% Invalid input detected at '^' marker.")


class IncompleteCommand(Exception):
    def __init__(self):
        super().__init__(
            "% Incomplete command.")


def match_command(input_token, valid_commands):
    """
    Retorna o comando completo se input_token e prefixo unico.
    match_command("sh", ["show", "shutdown"]) -> ambiguo
    match_command("sho", ["show", "shutdown"]) -> "show"
    """
    lower = input_token.lower()
    # Primeiro: match exato
    for cmd in valid_commands:
        if cmd.lower() == lower:
            return cmd
    # Segundo: match por prefixo
    matches = [cmd for cmd in valid_commands if cmd.lower().startswith(lower)]
    if len(matches) == 1:
        return matches[0]
    elif len(matches) > 1:
        raise AmbiguousCommand(input_token, matches)
    else:
        raise InvalidCommand(input_token)


def parse_vlan_list(vlan_str):
    """
    Parse lista de VLANs estilo Cisco.
    '10,20,30' -> [10, 20, 30]
    '10-15' -> [10, 11, 12, 13, 14, 15]
    '10,20-25,30' -> [10, 20, 21, 22, 23, 24, 25, 30]
    """
    result = []
    parts = vlan_str.split(",")
    for part in parts:
        part = part.strip()
        if "-" in part:
            start_end = part.split("-", 1)
            try:
                start = int(start_end[0])
                end = int(start_end[1])
                result.extend(range(start, end + 1))
            except ValueError:
                pass
        else:
            try:
                result.append(int(part))
            except ValueError:
                pass
    return sorted(set(result))
