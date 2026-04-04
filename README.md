[日本語版 (Japanese)](./README_ja.md) | [English version (英語版)](./README.md) | [API Reference](./API.md)

**R4S Archive System** is an encrypted archive solution designed for high-security, speed, and physical structural flexibility.

---

## 🚀 Key Features

-   **🔑 Variable Key Lengths (8 / 16 / 32 Bytes)**:
    -   Supports three security levels: `LOW (64-bit)`, `MID (128-bit)`, and `HIGH (256-bit)`.
-   **⚡ High-Speed XOR Encryption**:
    -   Uses an extremely fast XOR stream cipher, making it ideal for large data volumes. Early-byte scrambling enhances pattern protection.
-   **🔐 Robust Password Wrapping**:
    -   Combines `SHAKE256` for key derivation and `SHA256` for integrity checking.
-   **🔄 Security Migration (Optimize)**:
    -   Allows dynamic updating of key lengths and passwords even after archive creation.
-   **📂 Decoupled Architecture**:
    -   Separates logical path management from binary layout, ensuring metadata persistence (UID/Timestamp).

---

## 🛠 Quick Start (CLI Manager)

Manage your archives directly via `main.py`.

### 1. Create a New Archive
```bash
# Create with 256-bit (HIGH) key
python main.py create my_secure_data.r4s -p "my_secret_pass" -k 32
```

### 2. Add a File
```bash
python main.py add my_secure_data.r4s important_doc.pdf -p "my_secret_pass"
```

### 3. List Entries
```bash
python main.py list my_secure_data.r4s -p "my_secret_pass"
```

---

## 🏗 Technical Specification

### 4-Layer Structure
The archive adopts a robust 4-layer architecture to ensure both security and operational flexibility:
1.  **Layer 1: Fixed Header** - Contains Magic numbers, Version, UID, and CRC1 integrity.
2.  **Layer 2: Security Layer** - Manages KDF masks, wrapped physical keys, and password verification hashes.
3.  **Layer 3: Entry Index** - A binary manifest managing logical paths, offsets, and metadata.
4.  **Layer 4: Data Payload** - Encrypted content using XOR streaming with initial-byte scrambling.

### Header Structure (256 Bytes)
| Offset | Field | Description |
| :--- | :--- | :--- |
| 0 - 7 | Magic | `R4S_xx__` (xx denotes key length) |
| 10 - 11| Key Length | Specified length (8, 16, 32) |
| 64 - *** | Var Part | Mask, Scrambled Key, Integrity Hash |
| 252 - 255 | CRC32 | Header integrity verification |

---

## ⚖ Disclaimer
This system is designed for educational and verification purposes. For critical data, please conduct thorough security audits.

© 2026 R4S Project Team.
