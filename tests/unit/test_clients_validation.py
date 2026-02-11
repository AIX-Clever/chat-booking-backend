
import unittest
import sys
import os

# Add project root and clients dir to path
sys.path.append(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
sys.path.append(os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), 'clients'))

from clients.validation import validate_id, validate_rut, validate_cpf

class TestClientsValidation(unittest.TestCase):

    def test_validate_rut_valid(self):
        # Valid RUTs (Self-calculated or known)
        self.assertTrue(validate_rut("30.686.957-4"))
        self.assertTrue(validate_rut("11.111.111-1"))
        
    def test_validate_rut_invalid(self):
        self.assertFalse(validate_rut("11.111.111-2")) # Bad Check Digit
        self.assertFalse(validate_rut("bad-rut"))
        
    def test_validate_id_dispatcher(self):
        # CL Tax ID -> RUT
        # valid rut: 30.686.957-4
        self.assertTrue(validate_id("TAX_ID", "30.686.957-4", "CL"))
        self.assertFalse(validate_id("TAX_ID", "bad-rut", "CL"))
        
        # Other types -> Always True (for now)
        self.assertTrue(validate_id("PASSPORT", "P1234567", "CL"))
