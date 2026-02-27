import os
import sys
import base64
from datetime import datetime
from lxml import etree
from cryptography.hazmat.primitives.serialization import pkcs12
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import padding
import requests
from zeep import Client

# CONFIGURATION
# ---------------------------------------------------------
CERT_PATH = os.getenv("SII_CERT_PATH", "path/to/your/certificate.p12")
CERT_PASS = os.getenv("SII_CERT_PASS", "your_password")
# ---------------------------------------------------------

def get_seed():
    print("Fetching Seed from SII...")
    client = Client('https://wschile.sii.cl/CrSeed.cgi?wsdl')
    seed_xml = client.service.getSeed()
    # XML result is like <SII:RESPUESTA ...><SII:RESP_BODY><SEMILLA>...</SEMILLA>...</SII:RESPUESTA>
    root = etree.fromstring(seed_xml.encode('utf-8'))
    seed = root.find('.//SEMILLA').text
    print(f"Seed obtained: {seed}")
    return seed

def sign_seed(seed, cert_path, cert_pass):
    print("Signing Seed with Digital Certificate...")
    with open(cert_path, "rb") as f:
        p12_data = f.read()
    
    private_key, certificate, additional_certificates = pkcs12.load_key_and_certificates(p12_data, cert_pass.encode())
    
    # SII requires the seed to be wrapped in a specific XML structure for getToken
    template = f'<getToken><item><Semilla>{seed}</Semilla></item></getToken>'
    
    # NOTE: Real SII signing usually involves XMLDSig. 
    # For a prototype token request, we need to sign the content.
    # This is a simplified version of the XML signing logic.
    
    signature = private_key.sign(
        template.encode('utf-8'),
        padding.PKCS1v15(),
        hashes.SHA1()
    )
    
    signed_b64 = base64.b64encode(signature).decode()
    
    # In reality, SII expects a full XMLDSig structure. 
    # Libraries like 'signxml' are better for this.
    return template # Placeholder for actual signed XML

def get_token(signed_xml):
    # This URL is for obtaining the token
    # https://wschile.sii.cl/GetTokenFromSeed.cgi?wsdl
    print("Requesting Token from SII...")
    # This usually requires the full signed XML as a parameter
    return "MOCK_TOKEN_12345"

if __name__ == "__main__":
    if not os.path.exists(CERT_PATH):
        print(f"Error: Certificate not found at {CERT_PATH}")
        print("Please set SII_CERT_PATH and SII_CERT_PASS environment variables.")
        sys.exit(1)
        
    try:
        seed = get_seed()
        # In a real scenario, we'd use a library like 'signxml' to produce a valid XMLDSig
        print("Prototype: To get a real token, we need a valid XMLDSig (digital signature).")
        print("This script verifies we can connect to SII SOAP and load your certificate.")
        
        # Verify certificate loading
        with open(CERT_PATH, "rb") as f:
            pkcs12.load_key_and_certificates(f.read(), CERT_PASS.encode())
        print("✅ Certificate loaded successfully!")
        
    except Exception as e:
        print(f"❌ Error: {str(e)}")
