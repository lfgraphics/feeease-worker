import os
import base64
from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
from cryptography.hazmat.backends import default_backend

def get_encryption_key() -> str:
    key = os.environ.get("ENCRYPTION_KEY", "")
    if len(key) != 32:
        raise ValueError("ENCRYPTION_KEY environment variable must be exactly 32 characters long")
    return key

def decrypt(encrypted_text: str) -> str:
    if not encrypted_text or type(encrypted_text) is not str:
        return encrypted_text

    parts = encrypted_text.split(":")
    if len(parts) != 2:
        raise ValueError("Invalid encrypted text format")

    iv_hex, encrypted_data_hex = parts
    iv = bytes.fromhex(iv_hex)
    encrypted_data = bytes.fromhex(encrypted_data_hex)
    key = get_encryption_key().encode("utf-8")

    cipher = Cipher(algorithms.AES(key), modes.CBC(iv), backend=default_backend())
    decryptor = cipher.decryptor()
    
    decrypted_padded = decryptor.update(encrypted_data) + decryptor.finalize()
    
    # PKCS#7 unpadding
    pad_len = decrypted_padded[-1]
    decrypted = decrypted_padded[:-pad_len]
    return decrypted.decode("utf-8")

def is_encrypted(text: str) -> bool:
    if not text or type(text) is not str:
        return False
    return ":" in text and len(text.split(":")) == 2

def safe_decrypt(text: str) -> str:
    try:
        return decrypt(text) if is_encrypted(text) else text
    except Exception as e:
        print(f"Decryption failed: {e}")
        return text
