# R4S Archive API Reference (English Version)

[Japanese version (API_ja.md)](./API_ja.md) | [Back to README](./README.md)

Detailed specifications for the primary methods of the `r4s.archive.R4SArchive` class.

---

## 🏗 Instance Management

### `R4SArchive.create(path, password=None, key_len=R4SKeyLen.LOW, scramble_size=4096)`
Creates a new encrypted archive.
- **Arguments**:
    - `path`: Target file path (`str` or `Path`).
    - `password`: Encryption password. Optional.
    - `key_len`: Internal key length. Choose from `R4SKeyLen.LOW(8)`, `MID(16)`, or `HIGH(32)`.
    - `scramble_size`: XOR scramble size at the beginning of each file (default: 4096 bytes).
- **Returns**: `R4SArchive` instance.
- **Exceptions**: `FileExistsError` if the file already exists.

### `R4SArchive.open(path, password=None)`
Loads an existing archive.
- **Arguments**:
    - `path`: Existing archive file path.
    - `password`: Password required for loading.
- **Returns**: `R4SArchive` instance.
- **Exceptions**: `ValueError` for password mismatches or corrupted headers.

---

## 📂 Entry Operations (File Management)

### `set_entry(logical_path, source)`
Registers or updates a file within the archive.
- **Arguments**:
    - `logical_path`: Logical path (filename) inside the archive.
    - `source`: Data content (`bytes`) or original source file path (`str`/`Path`).
- **Returns**: Assigned `UID` (integer).
- **Note**: Changes are staged in memory/temporary files and only committed by `save()`.

### `get_entry(identifier)`
Retrieves data from the archive.
- **Arguments**: `identifier`: Logical path (string) or `UID` (integer).
- **Returns**: Content (`bytes`). Returns `None` if not found.

---

## ⚡ Security & Optimization

### `change_password(new_password)`
Updates the encryption password.
- **Note**: Re-wraps only the header (key wrapping), making it instantaneous even for massive archives. Requires `save()`.

### `optimize(new_key_len=None, new_scramble_size=None)`
Reconstructs the archive (Garbage collection & re-encryption).
- **Arguments**:
    - `new_key_len`: Updated key length.
    - `new_scramble_size`: Updated scramble size.
- **Usage**: Used for physical removal of deleted data and security migration.

---

## 💾 Save & Close

### `save()`
Commits all changes (new files, deletions, security updates) to the physical file.

### `close()`
Closes all handles and temporary files. Essential on Windows before re-opening.
