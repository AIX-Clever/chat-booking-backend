import re


def validate_rut(rut: str) -> bool:
    """
    Validates Chilean RUT (Rol Único Tributario).
    Format: 12.345.678-K or 12345678-K
    """
    rut = rut.replace(".", "").replace("-", "").upper()
    if len(rut) < 2:
        return False

    body = rut[:-1]
    dv = rut[-1]

    try:
        if not body.isdigit():
            return False

        total = 0
        multiplier = 2

        for c in reversed(body):
            total += int(c) * multiplier
            multiplier += 1
            if multiplier > 7:
                multiplier = 2

        remainder = 11 - (total % 11)
        if remainder == 11:
            calculated_dv = "0"
        elif remainder == 10:
            calculated_dv = "K"
        else:
            calculated_dv = str(remainder)

        return dv == calculated_dv
    except Exception:
        return False


def validate_cpf(cpf: str) -> bool:
    """
    Validates Brazilian CPF (Cadastro de Pessoas Físicas).
    Format: 123.456.789-00 or 12345678900
    """
    cpf = re.sub(r'[^0-9]', '', cpf)

    if len(cpf) != 11:
        return False

    # Check for repeated digits (invalid CPFs)
    if cpf == cpf[0] * len(cpf):
        return False

    # First digit validation
    total = 0
    for i in range(9):
        total += int(cpf[i]) * (10 - i)

    remainder = total % 11
    if remainder < 2:
        digit1 = 0
    else:
        digit1 = 11 - remainder

    if digit1 != int(cpf[9]):
        return False

    # Second digit validation
    total = 0
    for i in range(10):
        total += int(cpf[i]) * (11 - i)

    remainder = total % 11
    if remainder < 2:
        digit2 = 0
    else:
        digit2 = 11 - remainder

    return digit2 == int(cpf[10])


def validate_id(id_type: str, value: str, country_code: str = 'CL') -> bool:
    """
    Validates ID based on type and country.
    """
    if id_type == 'TAX_ID':
        if country_code == 'CL':
            return validate_rut(value)
        elif country_code == 'BR':
            return validate_cpf(value)
        # Default strict validation could go here, or lenient
        return True  # Lenient for unknown countries

    if id_type == 'PASSPORT':
        # Basic alphanumeric check
        return bool(re.match(r'^[A-Z0-9]{5,20}$', value.upper()))

    return True
