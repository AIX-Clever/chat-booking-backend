import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
from validation import validate_rut, validate_cpf, validate_id


class TestValidateRut:
    def test_rut_valido(self):
        assert validate_rut("12345678-5") is True

    def test_rut_con_puntos(self):
        assert validate_rut("12.345.678-5") is True

    def test_rut_con_k(self):
        assert validate_rut("7775735-K") is True

    def test_rut_invalido_digito(self):
        assert validate_rut("12345678-9") is False

    def test_rut_muy_corto(self):
        assert validate_rut("1") is False

    def test_rut_vacio(self):
        assert validate_rut("") is False


class TestValidateCpf:
    def test_cpf_valido(self):
        assert validate_cpf("529.982.247-25") is True

    def test_cpf_sin_formato(self):
        assert validate_cpf("52998224725") is True

    def test_cpf_invalido(self):
        assert validate_cpf("111.111.111-11") is False

    def test_cpf_digitos_repetidos(self):
        assert validate_cpf("00000000000") is False

    def test_cpf_longitud_incorrecta(self):
        assert validate_cpf("1234") is False


class TestValidateId:
    def test_tipo_rut_valido(self):
        assert validate_id("RUT", "12345678-5") is True

    def test_tipo_rut_invalido(self):
        assert validate_id("RUT", "12345678-0") is False

    def test_tipo_cpf_valido(self):
        assert validate_id("CPF", "529.982.247-25") is True

    def test_tipo_cpf_invalido(self):
        assert validate_id("CPF", "111.111.111-11") is False

    def test_tipo_passport_valido(self):
        assert validate_id("PASSPORT", "AA123456") is True

    def test_tipo_passport_corto(self):
        assert validate_id("PASSPORT", "AB1") is False

    def test_tipo_passport_con_espacios(self):
        assert validate_id("PASSPORT", "AA 1234") is False

    def test_tipo_dni_lenient(self):
        assert validate_id("DNI", "cualquier-valor") is True

    def test_tipo_other_lenient(self):
        assert validate_id("OTHER", "X") is True

    def test_legacy_tax_id_cl(self):
        assert validate_id("TAX_ID", "12345678-5", "CL") is True

    def test_legacy_tax_id_br(self):
        assert validate_id("TAX_ID", "529.982.247-25", "BR") is True

    def test_legacy_tax_id_otro_pais(self):
        assert validate_id("TAX_ID", "cualquier-cosa", "AR") is True
