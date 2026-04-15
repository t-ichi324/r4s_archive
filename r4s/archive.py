import os
import struct
import secrets
import logging
import hashlib
import json
import contextlib
import time
import binascii
import sys
from enum import IntEnum
from pathlib import Path
from typing import List, Dict, Optional, Union, Iterator, Tuple, Any

import uuid

class R4SKeyLen(IntEnum):
    """Supported Key Lengths for R4S Archive"""
    LOW    = 8   # 64-bit (Standard)
    MID    = 16  # 128-bit (Secure)
    HIGH   = 32  # 256-bit (Ultra-Secure)
    
    @classmethod
    def is_valid(cls, length: int) -> bool:
        return length in cls._value2member_map_

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("r4s")
__version__ = "1.0.0-core"

class R4SBinaryManager:
    def __init__(self, path: Union[str, Path]):
        self.path = Path(path)
        
    @contextlib.contextmanager
    def lock(self):
        mode = "r+b" if self.path.exists() else "w+b"
        f = open(self.path, mode)
        locked = False
        try:
            if os.name == 'nt':
                import msvcrt
                pos = f.tell()
                f.seek(0)
                try:
                    msvcrt.locking(f.fileno(), msvcrt.LK_NBLCK, 0x7FFFFFFF)
                    locked = True
                except OSError:
                    raise BlockingIOError("File is already locked by another process.")
                f.seek(pos)
            else:
                import fcntl
                try:
                    fcntl.flock(f.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                    locked = True
                except OSError:
                    raise BlockingIOError("File is already locked by another process.")
            yield f
        finally:
            if locked:
                try:
                    if os.name == 'nt':
                        import msvcrt
                        f.seek(0)
                        msvcrt.locking(f.fileno(), msvcrt.LK_UNLCK, 0x7FFFFFFF)
                    else:
                        import fcntl
                        fcntl.flock(f.fileno(), fcntl.LOCK_UN)
                except Exception:
                    pass
            f.close()

class R4SLayout:
    HEADER_SIZE = 256
    FOOTER_SIZE = 64
    MANIFEST_HEAD_SIZE = 52
    MAGIC_H_PATTERN = "R4S_{:02d}__" # 8 bytes
    MAGIC_M = b"R4SM"
    MAGIC_F = b"__R4S__"

    @classmethod
    def load(cls, path: Union[str, Path], password: Optional[str] = None) -> 'R4SLayout':
        path = Path(path)
        if not path.exists():
            raise FileNotFoundError(f"Archive not found at {path}")
        if path.stat().st_size < cls.HEADER_SIZE:
            raise ValueError(f"File at {path} is too small to be an R4S archive")
            
        with open(path, "rb") as f:
            buf = f.read(cls.HEADER_SIZE)
        
        # Load logic
        inst = cls(password=password)
        res = inst.parse_header(buf, password)
        if res is False:
            raise ValueError("Invalid R4S header or incorrect password")
        elif res is None:
             raise ValueError("CRC error in R4S header")
        return inst

    def __init__(self, password: Optional[str] = None, key_len: int = 8, scramble_size: int = 4096, uid: bytes = b"\x00"*8, created_at: int = 0):
        self.scramble_size = scramble_size
        self.key_len = key_len
        self.r4s_key: Optional[bytes] = None # None means not yet established
        self.uid = uid
        self.created_at = created_at
        self.version = 0x01
        self.password = password

    @property
    def r4s_key_len(self) -> int:
        """Alias for key_len to maintain compatibility with test cases."""
        return self.key_len

    def fast_xor(self, data: bytes, full: bool = True) -> bytes:
        if not data: return b""
        if self.r4s_key is None: return data # Safety: can't XOR without key
        n = len(data)
        limit = n if full else min(n, self.scramble_size)
        CHUNK_SIZE = 1024 * 1024 
        res_chunks = []
        precalc_key = (self.r4s_key * (CHUNK_SIZE // self.key_len + 1))[:CHUNK_SIZE]
        i_key_full = int.from_bytes(precalc_key, "big")
        
        target = data[:limit]
        for offset in range(0, limit, CHUNK_SIZE):
            chunk = target[offset:offset+CHUNK_SIZE]
            c_len = len(chunk)
            i_data = int.from_bytes(chunk, "big")
            i_key = i_key_full if c_len == CHUNK_SIZE else int.from_bytes(precalc_key[:c_len], "big")
            res_chunk = (i_data ^ i_key).to_bytes(c_len, "big")
            res_chunks.append(res_chunk)
        return b"".join(res_chunks) + data[limit:]

    def parse_header(self, buf: bytes, password: Optional[str]) -> bool:
        if len(buf) < self.HEADER_SIZE: return False
        
        # 1. First CRC check (0-59)
        crc1_claimed = struct.unpack("<I", buf[60:64])[0]
        crc1_actual = binascii.crc32(buf[0:60]) & 0xFFFFFFFF
        if crc1_actual != crc1_claimed:
            return None # Use None to indicate CRC error specifically
            
        # 2. Final CRC check (0-251)
        crc2_claimed = struct.unpack("<I", buf[252:256])[0]
        crc2_actual = binascii.crc32(buf[0:252]) & 0xFFFFFFFF
        if crc2_actual != crc2_claimed:
            return False
            
        # 3. Parse Fixed Part (0-31)
        magic_raw, ver, flags, key_len, scr_size, created_at, uid = struct.unpack("<8sBBHIQ8s", buf[0:32])
        if magic_raw[0:4] != b"R4S_":
            return False
        
        magic = magic_raw.decode("ascii", errors="replace")
        if not magic.startswith("R4S_"):
            return False
            
        # マジックナンバー (R4S_xx__) から仕様を確定
        m_key_len = 0
        if magic == "R4S_08__":
            m_key_len = 8
        elif magic == "R4S_16__":
            m_key_len = 16
        elif magic == "R4S_32__":
            m_key_len = 32
            
        if m_key_len == 0:
            return False
            
        if m_key_len != key_len:
            return False
        
        # 3.5 Metadata sync (ver, scr_size, created_at, uid)
        self.version = ver
        self.scramble_size = scr_size
        self.key_len = int(key_len)
        self.uid = uid
        self.created_at = created_at
        
        # 4. Decrypt Key
        # 64-*** Var Part
        mask_off = 64
        sk_off = mask_off + key_len
        pc_off = sk_off + key_len
        
        mask = buf[mask_off : sk_off]
        scrambled = buf[sk_off : pc_off]
        pass_check = buf[pc_off : pc_off + 8]
        
        has_pass = bool(flags & 0x01)
        u_hash = b"\x00" * int(key_len)
        if has_pass:
            if not password: return False # Password required
            # 鍵導出 (SHAKE256)
            u_hash = hashlib.shake_256(password.encode() + mask[:int(key_len)]).digest(int(key_len))
            # 整合性チェック (SHA256)
            check_hash = hashlib.sha256(u_hash + mask[:int(key_len)]).digest()[:8]
            if check_hash != pass_check:
                return False
            
        self.r4s_key = bytes(a ^ b ^ c for a, b, c in zip(scrambled[:int(key_len)], mask[:int(key_len)], u_hash[:int(key_len)]))
        return True

    def pack_header(self, password: Optional[str]) -> bytes:
        # 保存前に鍵長がサポート対象 (8, 16, 32) か最終チェック
        if self.key_len not in [8, 16, 32]:
            raise ValueError(f"Cannot pack header: Unsupported key length {self.key_len}")

        # 鍵がまだ確立されていない（新規作成時など）場合のみランダム生成
        if self.r4s_key is None or len(self.r4s_key) != self.key_len:
            self.r4s_key = secrets.token_bytes(self.key_len)
            
        magic = self.MAGIC_H_PATTERN.format(self.key_len).encode("ascii")
        flags = 0x01 if password else 0x00
        
        fixed_part = struct.pack("<8sBBHIQ8s28x", magic, self.version, flags, self.key_len, 
                               self.scramble_size, self.created_at, self.uid)
        crc1 = binascii.crc32(fixed_part) & 0xFFFFFFFF
        head_64 = fixed_part + struct.pack("<I", crc1)
        
        mask = secrets.token_bytes(self.key_len)
        u_hash = b"\x00" * self.key_len
        pass_check = b"\x00" * 8
        if password:
            u_hash = hashlib.shake_256(password.encode() + mask).digest(int(self.key_len))
            pass_check = hashlib.sha256(u_hash + mask).digest()[:8]
            
        scrambled_key = bytes(a ^ b ^ c for a, b, c in zip(self.r4s_key[:int(self.key_len)], mask[:int(self.key_len)], u_hash[:int(self.key_len)]))
        
        var_part = mask + scrambled_key + pass_check
        full_buf = (head_64 + var_part).ljust(252, b"\x00")
        
        crc2 = binascii.crc32(full_buf) & 0xFFFFFFFF
        return full_buf + struct.pack("<I", crc2)

    def parse_footer(self, data: bytes) -> Optional[Dict]:
        if len(data) < self.FOOTER_SIZE or data[-7:] != self.MAGIC_F: return None
        unpacked = struct.unpack("<qQQI", data[:28])
        uid_bytes = struct.pack("<Q", unpacked[1]) # Convert back to 8 bytes
        return {"manifest_offset": unpacked[0], "uuid": uid_bytes, "revision": unpacked[2], "flags": unpacked[3]}

    def pack_footer(self, manifest_off: int, revision: int, flags: int = 0) -> bytes:
        uid_int = int.from_bytes(self.uid, "little")
        body = struct.pack("<qQQI", manifest_off, uid_int, revision, flags)
        return body.ljust(self.FOOTER_SIZE - 7, b"\x00") + self.MAGIC_F

    def pack_manifest(self, entries: Dict[int, 'R4SEntry'], assets: Dict[int, 'R4SEntry'], 
                      anno: dict, meta: dict, f_handle) -> bytes:
        res_map = {}
        buf = b"".join([struct.pack("<H", len(e.name.encode("utf-8"))) + e.name.encode("utf-8") + 
                        struct.pack("<QQqb", e.uid, e.offset, e.size, 1 if e.is_deleted else 0) 
                        for e in entries.values()])
        res_map["idx"] = (f_handle.tell(), len(buf))
        f_handle.write(self.fast_xor(buf, True))

        chunks = []
        for a in assets.values():
            name_b, mime_b = a.name.encode("utf-8"), (a.mime or "").encode("utf-8")
            flg = 1 if a.is_deleted else 0
            chunks.append(struct.pack("<H", len(name_b)) + name_b + 
                          struct.pack("<QQqHb", a.uid, a.offset, a.size, len(mime_b), flg) + mime_b)
        buf = b"".join(chunks)
        res_map["asset"] = (f_handle.tell(), len(buf))
        f_handle.write(self.fast_xor(buf, True))

        for k, d in [("anno", anno), ("meta", meta)]:
            buf = json.dumps(d, ensure_ascii=False).encode("utf-8")
            res_map[k] = (f_handle.tell(), len(buf))
            f_handle.write(self.fast_xor(buf, True))

        return struct.pack("<4s qI qI qI qI", self.MAGIC_M,
                           res_map["idx"][0], res_map["idx"][1],
                           res_map["asset"][0], res_map["asset"][1],
                           res_map["anno"][0], res_map["anno"][1],
                           res_map["meta"][0], res_map["meta"][1])

    def parse_manifest_head(self, buf: bytes) -> Dict:
        if len(buf) < self.MANIFEST_HEAD_SIZE or buf[:4] != self.MAGIC_M: return {}
        vals = struct.unpack("<4s qI qI qI qI", buf[:self.MANIFEST_HEAD_SIZE])
        return {k: {"off": vals[i*2+1], "sz": vals[i*2+2]} for i, k in enumerate(["idx", "asset", "anno", "meta"])}

class R4SEntry:
    def __init__(self, uid: int, name: str, offset: int = 0, size: int = 0):
        self.uid = uid; self.name = name; self.offset = offset; self.size = size
        self.mime: Optional[str] = None
        self._is_modified = False
        self.is_deleted = False
        
        # --- Pending Sources ---
        self.pending_source_path: Optional[str] = None
        self.pending_source_bytes: Optional[bytes] = None
        self.pending_staging_info: Optional[Tuple[int, int]] = None  # (offset, size)
        self.pending_source_archive: Optional['R4SArchive'] = None
        self.pending_source_uid: Optional[int] = None
        self.pending_is_asset: bool = False
        
    @property
    def is_new(self) -> bool:
        """新規作成（オフセット未確定）かつ削除されていないエントリ"""
        return self.offset == 0 and not self.is_deleted

    @property
    def is_modified(self) -> bool:
        """データが変更されているか（メモリ上のフラグ）"""
        return self._is_modified

class R4SArchive:
    WRITE_BUFFER_SIZE = 10 * 1024 * 1024
    MAX_MEMORY_BYTES = 5 * 1024 * 1024

    @classmethod
    def create(cls, path: Union[str, Path], password: Optional[str] = None, 
               key_len: int = R4SKeyLen.LOW, scramble_size: int = 4096,
               keep_open: bool = False) -> 'R4SArchive':
        """新規にアーカイブを作成し、インスタンスを返す（既存ファイルがあれば FileExistsError）"""
        path = Path(path)
        if path.exists():
            raise FileExistsError(f"Archive already exists at {path}")
        
        inst = cls(path, password, key_len, scramble_size, keep_open=keep_open)
        inst._is_ready = True
        inst.save()
        return inst

    @classmethod
    def open(cls, path: Union[str, Path], password: Optional[str] = None,
             keep_open: bool = False) -> 'R4SArchive':
        """既存のアーカイブを開き、ロードして返す（ファイルがない場合は FileNotFoundError）"""
        inst = cls(path, password, keep_open=keep_open)
        if not inst.path.exists():
            raise FileNotFoundError(f"Archive not found at {inst.path}")
        if inst.path.stat().st_size < R4SLayout.HEADER_SIZE:
            raise ValueError(f"File at {inst.path} is too small to be an R4S archive")
            
        # 明示的にロード
        inst._load(password)
        inst._is_ready = True
        return inst

    def __init__(self, path: Union[str, Path], password: Optional[str] = None, 
               key_len: int = R4SKeyLen.LOW, scramble_size: int = 4096,
               keep_open: bool = False):
        # 鍵長のバリデーション (fail-fast)
        if not R4SKeyLen.is_valid(key_len):
            raise ValueError(f"Unsupported key length: {key_len}. Use R4SKeyLen.")
            
        self.path = Path(path)
        self._password = password
        self._is_ready = False
        self._is_dirty = False
        self._keep_open = keep_open
        self._f_handle = None

        if self.path.exists():
            # Note: Layout is loaded here, but full manifest logic is in _load()
            self._layout = R4SLayout.load(self.path, password)
        else:
            uid = secrets.token_bytes(8)
            created_at = int(time.time())
            self._layout = R4SLayout(password, key_len, scramble_size, uid, created_at)
            self._is_dirty = True # 新規作成時はヘッダー保存が必要

        self._entries: Dict[int, R4SEntry] = {}
        self._assets: Dict[int, R4SEntry] = {}
        self._path_index: Dict[str, List[int]] = {}
        self._asset_key_index: Dict[str, List[int]] = {}
        self._entry_meta: Dict[str, dict] = {}
        self._archive_meta = {"next_uid": 1}
        self._revision = 1
        self._payload_end_offset = self._layout.HEADER_SIZE
        
        self._staging_file_path = self.path.parent / f"{self.path.name}.{secrets.token_hex(4)}.tmp"

    @property
    def _uuid(self): 
        return self._layout.uid
        
    @property
    def _created_at(self): 
        return self._layout.created_at
        
    @property
    def _revision_num(self): 
        """Property for internal revision management."""
        return self._revision

    # --- Lifecycle ---
    def close(self) -> bool:
        self._is_ready = False
        if self._f_handle:
            try:
                self._f_handle.close()
            except Exception:
                pass
            self._f_handle = None
            
        if self._staging_file_path.exists():
            try:
                os.remove(self._staging_file_path)
            except OSError:
                pass
        return True

    def change_password(self, new_password: Optional[str]):
        """パスワードを変更（ヘッダーの再ラップのみ実行、データ本体の再暗号化は不要）"""
        if not self._is_ready: return
        self._password = new_password
        self._is_dirty = True

    # --- Internal & Helper Methods ---
    def _generate_uid(self) -> int:
        uid = self._archive_meta.get("next_uid", 1)
        self._archive_meta["next_uid"] = uid + 1
        self._is_dirty = True
        return uid

    def _resolve_uid(self, identifier: Union[str, int], is_asset: bool = False) -> Optional[int]:
        index = self._asset_key_index if is_asset else self._path_index
        collection = self._assets if is_asset else self._entries
        if isinstance(identifier, int):
            return identifier if identifier in collection else None
        uids = index.get(identifier, [])
        valid = [u for u in uids if u in collection and not collection[u].is_deleted]
        return max(valid) if valid else None

    def _get_read_handle(self):
        """物理ファイルへの読み込みハンドルを取得します（keep_open に対応）"""
        if not self._keep_open:
            return open(self.path, "rb")
            
        if self._f_handle is None or self._f_handle.closed:
            self._f_handle = open(self.path, "rb")
        return self._f_handle

    def _load(self, password):
        self._entries.clear()
        self._assets.clear()
        self._path_index.clear()
        self._asset_key_index.clear()
        self._entry_meta.clear()
        try:
            f_size = self.path.stat().st_size
            with open(self.path, "rb") as f:
                # 常に最新のレイアウトをロードして差し替える（状態干渉を防止）
                self._layout = R4SLayout.load(self.path, password)
                
                f.seek(f_size - self._layout.FOOTER_SIZE)
                footer_raw = f.read(self._layout.FOOTER_SIZE)
                footer = self._layout.parse_footer(footer_raw)
                if not footer:
                    return
                
                m_off = footer["manifest_offset"]
                f.seek(m_off)
                m_head_raw = self._layout.fast_xor(f.read(self._layout.MANIFEST_HEAD_SIZE), True)
                m_head = self._layout.parse_manifest_head(m_head_raw)
                if not m_head:
                    return

                min_off = m_head.get("idx", {}).get("off", m_off)
                self._revision = footer["revision"]
                self._payload_end_offset = min_off

                # --- Restore Manifest Parsing ---
                if m_head.get("idx", {}).get("sz", 0) > 0:
                    f.seek(m_head["idx"]["off"])
                    buf = self._layout.fast_xor(f.read(m_head["idx"]["sz"]), True)
                    ptr = 0
                    while ptr < len(buf):
                        ln = struct.unpack("<H", buf[ptr:ptr+2])[0]; ptr += 2
                        name = buf[ptr:ptr+ln].decode("utf-8"); ptr += ln
                        uid, off, sz, flg = struct.unpack("<QQqb", buf[ptr:ptr+25]); ptr += 25
                        e = R4SEntry(uid, name, off, sz); e.is_deleted = bool(flg)
                        self._entries[uid] = e; self._path_index.setdefault(name, []).append(uid)
                
                if m_head.get("asset", {}).get("sz", 0) > 0:
                    f.seek(m_head["asset"]["off"])
                    buf = self._layout.fast_xor(f.read(m_head["asset"]["sz"]), True)
                    ptr = 0
                    while ptr < len(buf):
                        ln = struct.unpack("<H", buf[ptr:ptr+2])[0]; ptr += 2
                        name = buf[ptr:ptr+ln].decode("utf-8"); ptr += ln
                        uid, off, sz, mln, flg = struct.unpack("<QQqHb", buf[ptr:ptr+27]); ptr += 27
                        mime = buf[ptr:ptr+mln].decode("utf-8"); ptr += mln
                        a = R4SEntry(uid, name, off, sz); a.mime = mime; a.is_deleted = bool(flg)
                        self._assets[uid] = a; self._asset_key_index.setdefault(name, []).append(uid)
                
                if m_head.get("anno", {}).get("sz", 0) > 0:
                    f.seek(m_head["anno"]["off"])
                    self._entry_meta = json.loads(self._layout.fast_xor(f.read(m_head["anno"]["sz"]), True).decode("utf-8"))
                    
                if m_head.get("meta", {}).get("sz", 0) > 0:
                    f.seek(m_head["meta"]["off"])
                    self._archive_meta = json.loads(self._layout.fast_xor(f.read(m_head["meta"]["sz"]), True).decode("utf-8"))
        except Exception as e:
            logger.error(f"Load failed: {e}")

    def _handle_source_input(self, entry: R4SEntry, source: Union[bytes, str, Path]):
        """入力を bytes, file path, または staging file に振り分ける"""
        if isinstance(source, bytes):
            if len(source) <= self.MAX_MEMORY_BYTES:
                entry.pending_source_bytes = source
                entry.size = len(source)
            else:
                with open(self._staging_file_path, "a+b") as stg:
                    stg_offset = stg.tell()
                    stg.write(source)
                    entry.pending_staging_info = (stg_offset, len(source))
                    entry.size = len(source)
        else:
            p = Path(source)
            entry.pending_source_path = str(p)
            if p.exists(): entry.size = p.stat().st_size
        self._is_dirty = True

    # --- Core State Management ---
    def save(self):
        if not self._is_dirty: return
            
        # 書き込み前に読み取りハンドルがあれば閉じる（Windowsでの衝突回避）
        if self._f_handle:
            try:
                self._f_handle.close()
            except Exception:
                pass
            self._f_handle = None

        bm = R4SBinaryManager(self.path)
        write_buffer = bytearray()
        def flush_buf(f_h):
            if write_buffer: f_h.write(write_buffer); write_buffer.clear()

        with bm.lock() as f:
            # 3. ヘッダーの更新 (常に現在のパスワードで再パックして上書き)
            f.seek(0)
            f.write(self._layout.pack_header(self._password))
            f.flush()
            try:
                os.fsync(f.fileno())
            except Exception:
                pass
            
            # 1. 保存直前のバックアップ
            f.seek(self._payload_end_offset)
            rollback_data = f.read()
            original_payload_pos = self._payload_end_offset
            
            # 2. フタを切り飛ばす
            f.truncate(self._payload_end_offset)
            f.seek(self._payload_end_offset)
            
            try:
                pending = [i for i in list(self._entries.values()) + list(self._assets.values()) 
                           if i.pending_source_path or i.pending_staging_info or getattr(i, 'pending_source_archive', None) or i.pending_source_bytes is not None]
                
                def encrypt_stream(stream):
                    scrambled = 0
                    scramble_limit = self._layout.scramble_size
                    for chunk in stream:
                        if scrambled < scramble_limit:
                            to_scramble = min(len(chunk), scramble_limit - scrambled)
                            yield self._layout.fast_xor(chunk[:to_scramble], full=True)
                            if len(chunk) > to_scramble:
                                yield chunk[to_scramble:]
                            scrambled += to_scramble
                        else:
                            yield chunk

                def file_stream(path):
                    with open(path, "rb") as src:
                        while True:
                            c = src.read(1024 * 1024)
                            if not c: break
                            yield c

                def staging_stream(path, start, length):
                    with open(path, "rb") as src:
                        src.seek(start)
                        rem = length
                        while rem > 0:
                            c = src.read(min(1024 * 1024, rem))
                            if not c: break
                            yield c
                            rem -= len(c)

                # 3. データの直列書き込み
                for item in pending:
                    item.offset = f.tell() + len(write_buffer)
                    
                    if getattr(item, 'pending_source_archive', None):
                        src_stream = item.pending_source_archive.iter_entry(item.pending_source_uid, is_asset=item.pending_is_asset)
                        for chunk in encrypt_stream(src_stream):
                            write_buffer.extend(chunk)
                            if len(write_buffer) >= self.WRITE_BUFFER_SIZE: flush_buf(f)
                        item.pending_source_archive = None

                    elif item.pending_source_path and os.path.exists(item.pending_source_path):
                        for chunk in encrypt_stream(file_stream(item.pending_source_path)):
                            write_buffer.extend(chunk)
                            if len(write_buffer) >= self.WRITE_BUFFER_SIZE: flush_buf(f)
                        item.pending_source_path = None
                        
                    elif item.pending_staging_info:
                        stg_off, stg_sz = item.pending_staging_info
                        for chunk in encrypt_stream(staging_stream(self._staging_file_path, stg_off, stg_sz)):
                            write_buffer.extend(chunk)
                            if len(write_buffer) >= self.WRITE_BUFFER_SIZE: flush_buf(f)
                        item.pending_staging_info = None
                    
                    elif item.pending_source_bytes is not None:
                        for chunk in encrypt_stream([item.pending_source_bytes]):
                            write_buffer.extend(chunk)
                            if len(write_buffer) >= self.WRITE_BUFFER_SIZE: flush_buf(f)
                        item.pending_source_bytes = None
                        
                flush_buf(f)
                
                # 4. マニフェストの再生成
                self._payload_end_offset = f.tell()
                m_head_bytes = self._layout.pack_manifest(self._entries, self._assets, self._entry_meta, self._archive_meta, f)
                m_head_off = f.tell()
                f.write(self._layout.fast_xor(m_head_bytes, True))
                self._revision += 1
                footer_bytes = self._layout.pack_footer(m_head_off, self._revision, 0)
                f.write(footer_bytes)
                f.truncate()
                f.flush(); os.fsync(f.fileno())
                
                for i in list(self._entries.values()) + list(self._assets.values()):
                    i._is_modified = False
                    
                # 5. Stagingファイルのクリーンアップ
                if self._staging_file_path.exists():
                    try: os.remove(self._staging_file_path)
                    except OSError: pass
                    
            except Exception as e:
                # 失敗時のロールバック処理
                f.seek(original_payload_pos)
                f.truncate()
                f.write(rollback_data)
                f.flush(); os.fsync(f.fileno())
                logger.error(f"Save failed, rolled back: {e}"); raise
                
        self._is_dirty = False
        # 書き込み終了後、必要ならハンドルを再開
        if self._keep_open:
            self._get_read_handle()

    def optimize(self, new_key_len: Optional[int] = None, new_scramble_size: Optional[int] = None):
        tmp_path = self.path.with_suffix(".opt_tmp")
        # 移行用パラメータの決定
        target_key_len = new_key_len if new_key_len is not None else self._layout.r4s_key_len
        target_scr_size = new_scramble_size if new_scramble_size is not None else self._layout.scramble_size
        
        # 新しい設定で空のアーカイブ・インスタンスを準備（自動保存なし）
        new_archive = type(self)(tmp_path, self._password, 
                                 key_len=target_key_len, 
                                 scramble_size=target_scr_size)
                                        
        new_archive._layout.uid = self._layout.uid
        new_archive._layout.created_at = int(time.time()) # Optimization/Migrate updates timestamp
        new_archive._archive_meta = self._archive_meta.copy()
        new_archive._entry_meta = self._entry_meta.copy()
        
        for uid, e in self._entries.items():
            if not e.is_deleted:
                new_e = R4SEntry(uid, e.name, size=e.size)
                new_e.pending_source_archive = self
                new_e.pending_source_uid = uid
                new_e.pending_is_asset = False
                new_archive._entries[uid] = new_e
                new_archive._path_index.setdefault(e.name, []).append(uid)
                
        for uid, a in self._assets.items():
            if not a.is_deleted:
                new_a = R4SEntry(uid, a.name, size=a.size)
                new_a.mime = a.mime
                new_a.pending_source_archive = self
                new_a.pending_source_uid = uid
                new_a.pending_is_asset = True
                new_archive._assets[uid] = new_a
                new_archive._asset_key_index.setdefault(a.name, []).append(uid)
        
        new_archive._is_dirty = True
        new_archive.save()
        new_archive.close() # 明示的にクローズしてロックを解除
        # 最適化したファイルを既存のものと入れ替え、再ロード
        os.replace(tmp_path, self.path)
        self._load(self._password)

    # --- Entry API ---
    def set_entry(self, logical_path: str, source: Union[bytes, str, Path]) -> int:
        uid = self._resolve_uid(logical_path)
        if uid is not None:
            entry = self._entries[uid]
        else:
            uid = self._generate_uid()
            entry = R4SEntry(uid, logical_path)
            self._entries[uid] = entry
            self._path_index.setdefault(logical_path, []).append(uid)
        self._handle_source_input(entry, source)
        return uid

    def remove_entry(self, identifier: Union[str, int]):
        uid = self._resolve_uid(identifier)
        if uid is not None and not self._entries[uid].is_deleted:
            self._entries[uid].is_deleted = True
            self._is_dirty = True

    def rename_entry(self, identifier: Union[str, int], new_name: str):
        uid = self._resolve_uid(identifier)
        if uid is None: return
        entry = self._entries[uid]
        old_name = entry.name
        if old_name in self._path_index: self._path_index[old_name].remove(uid)
        entry.name = new_name
        self._path_index.setdefault(new_name, []).append(uid)
        self._is_dirty = True

    def rename_directory(self, old_dir: str, new_dir: str):
        """
        ディレクトリパス（プレフィックス）を一括で置換します。
        エントリーとアセットの両方が対象となります。
        """
        target_old = old_dir.replace("\\", "/").strip("/")
        target_new = new_dir.replace("\\", "/").strip("/")
        if not target_old: return

        # 1. エントリーのリネーム
        e_items = self.list_entries(target_old, recursive=True)
        for uid, name in e_items:
            norm_name = name.replace("\\", "/")
            if norm_name.startswith(target_old + "/"):
                new_name = target_new + "/" + norm_name[len(target_old)+1:]
                self.rename_entry(uid, new_name)
            elif norm_name == target_old:
                self.rename_entry(uid, target_new)

        # 2. アセットのリネーム
        a_items = self.list_assets(target_old, recursive=True)
        for uid, name in a_items:
            norm_name = name.replace("\\", "/")
            if norm_name.startswith(target_old + "/"):
                new_name = target_new + "/" + norm_name[len(target_old)+1:]
                self.rename_asset(uid, new_name)
            elif norm_name == target_old:
                self.rename_asset(uid, target_new)

    def remove_directory(self, target_dir: str):
        """
        指定したディレクトリパス（プレフィックス）を持つすべての
        エントリーとアセットを一括で削除（削除マーク）します。
        """
        target = target_dir.replace("\\", "/").strip("/")
        if not target: return

        for uid, _ in self.list_entries(target, recursive=True):
            self.remove_entry(uid)

        for uid, _ in self.list_assets(target, recursive=True):
            self.remove_asset(uid)

    def get_entry(self, identifier: Union[str, int]) -> Optional[bytes]:
        if self._resolve_uid(identifier) is None: return None
        return b"".join(list(self.iter_entry(identifier)))

    def iter_entry(self, identifier: Union[str, int], chunk_size: int = 1024 * 1024, is_asset: bool = False) -> Iterator[bytes]:
        uid = self._resolve_uid(identifier, is_asset=is_asset)
        if uid is None: return
        entry = (self._assets if is_asset else self._entries)[uid]
        
        if entry.pending_source_bytes is not None:
            for i in range(0, len(entry.pending_source_bytes), chunk_size):
                yield entry.pending_source_bytes[i : i + chunk_size]
            return

        if entry.pending_source_path and os.path.exists(entry.pending_source_path):
            with open(entry.pending_source_path, "rb") as f:
                while True:
                    data = f.read(chunk_size)
                    if not data: break
                    yield data
            return

        if entry.pending_staging_info:
            stg_off, stg_sz = entry.pending_staging_info
            if self._staging_file_path.exists():
                with open(self._staging_file_path, "rb") as stg:
                    stg.seek(stg_off)
                    rem = stg_sz
                    while rem > 0:
                        chunk = stg.read(min(chunk_size, rem))
                        if not chunk: break
                        yield chunk
                        rem -= len(chunk)
            return

        if entry.pending_source_archive:
            yield from entry.pending_source_archive.iter_entry(entry.pending_source_uid, chunk_size, entry.pending_is_asset)
            return

        if not self.path.exists(): return
        
        f = self._get_read_handle()
        try:
            f.seek(entry.offset)
            remaining = entry.size
            scrambled_len = min(remaining, self._layout.scramble_size)
            if scrambled_len > 0:
                scrambled_data = self._layout.fast_xor(f.read(scrambled_len), full=False)
                for i in range(0, len(scrambled_data), chunk_size):
                    yield scrambled_data[i:i+chunk_size]
                remaining -= scrambled_len
            while remaining > 0:
                data = f.read(min(chunk_size, remaining))
                yield data
                remaining -= len(data)
        finally:
            if not self._keep_open:
                f.close()

    def list_entries(self, parent_path: Optional[str] = None, recursive: bool = True) -> List[Tuple[int, str]]:
        """
        アーカイブ内のエントリ一覧を返します。
        :param parent_path: フィルタリングする親ディレクトリパス。
        :param recursive: Trueの場合、サブディレクトリ内も含みます。
        """
        items = [(e.uid, e.name) for e in self._entries.values() if not e.is_deleted]
        if parent_path is None:
            return items
            
        target_parent = parent_path.replace("\\", "/").rstrip("/")
        if target_parent == ".": target_parent = ""

        results = []
        for uid, name in items:
            norm_name = name.replace("\\", "/")
            if target_parent == "":
                if recursive or "/" not in norm_name:
                    results.append((uid, name))
            elif norm_name.startswith(target_parent + "/"):
                rel_path = norm_name[len(target_parent)+1:]
                if recursive or "/" not in rel_path:
                    results.append((uid, name))
        return results

    # --- Asset API ---
    def set_asset(self, key: str, source: Union[bytes, str, Path], mime: str = "application/octet-stream") -> int:
        uid = self._resolve_uid(key, is_asset=True)
        if uid is not None:
            asset = self._assets[uid]
        else:
            uid = self._generate_uid()
            asset = R4SEntry(uid, key)
            self._assets[uid] = asset
            self._asset_key_index.setdefault(key, []).append(uid)
        asset.mime = mime
        self._handle_source_input(asset, source)
        return uid

    def remove_asset(self, identifier: Union[str, int]):
        uid = self._resolve_uid(identifier, is_asset=True)
        if uid is None and identifier in self._assets: uid = identifier # UID直指定の救済
        if uid is not None and not self._assets[uid].is_deleted:
            self._assets[uid].is_deleted = True
            self._is_dirty = True

    def rename_asset(self, identifier: Union[str, int], new_name: str):
        uid = self._resolve_uid(identifier, is_asset=True)
        if uid is None: return
        asset = self._assets[uid]
        old_name = asset.name
        if old_name in self._asset_key_index: self._asset_key_index[old_name].remove(uid)
        asset.name = new_name
        self._asset_key_index.setdefault(new_name, []).append(uid)
        self._is_dirty = True

    def get_asset(self, identifier: Union[str, int]) -> Optional[bytes]:
        if self._resolve_uid(identifier, is_asset=True) is None: return None
        return b"".join(list(self.iter_entry(identifier, is_asset=True)))

    def list_assets(self, parent_path: Optional[str] = None, recursive: bool = True) -> List[Tuple[int, str]]:
        """
        アーカイブ内のアセット一覧を返します。
        :param parent_path: フィルタリングする親ディレクトリパス。
        :param recursive: Trueの場合、サブディレクトリ内も含みます。
        """
        items = [(a.uid, a.name) for a in self._assets.values() if not a.is_deleted]
        if parent_path is None:
            return items
            
        target_parent = parent_path.replace("\\", "/").rstrip("/")
        if target_parent == ".": target_parent = ""

        results = []
        for uid, name in items:
            norm_name = name.replace("\\", "/")
            if target_parent == "":
                if recursive or "/" not in norm_name:
                    results.append((uid, name))
            elif norm_name.startswith(target_parent + "/"):
                rel_path = norm_name[len(target_parent)+1:]
                if recursive or "/" not in rel_path:
                    results.append((uid, name))
        return results

    # --- Metadata API ---
    def get_entry_meta(self, identifier: Union[str, int], key: Optional[str] = None, default: Any = None) -> Any:
        uid = self._resolve_uid(identifier)
        if not uid: return default if key else {}
        data = self._entry_meta.get(str(uid), {})
        if key: return data.get(key, default)
        return data

    def set_entry_meta(self, identifier: Union[str, int], data: Union[dict, str], value: Any = None):
        uid = self._resolve_uid(identifier)
        if not uid: return
        current = self._entry_meta.setdefault(str(uid), {})
        if isinstance(data, str): current[data] = value
        else: current.update(data)
        self._is_dirty = True

    def get_archive_meta(self, key: Optional[str] = None, default: Any = None) -> Any:
        data = {k: v for k, v in self._archive_meta.items() if k != "next_uid"}
        if key: return data.get(key, default)
        return data

    def set_archive_meta(self, data: Union[dict, str], value: Any = None):
        next_uid = self._archive_meta.get("next_uid", 1)
        if isinstance(data, str): self._archive_meta[data] = value
        else: self._archive_meta.update(data)
        self._archive_meta["next_uid"] = next_uid
        self._is_dirty = True

    @staticmethod
    def get_archive_meta_from_file(path: Union[str, Path], password: Optional[str] = None) -> dict:
        target = Path(path)
        if not target.exists(): return {}
        layout = R4SLayout()
        try:
            f_size = target.stat().st_size
            with open(target, "rb") as f:
                if not layout.parse_header(f.read(layout.HEADER_SIZE), password): return {}
                f.seek(f_size - layout.FOOTER_SIZE)
                footer = layout.parse_footer(f.read(layout.FOOTER_SIZE))
                if not footer: return {}
                f.seek(footer["manifest_offset"])
                m_head = layout.parse_manifest_head(layout.fast_xor(f.read(layout.MANIFEST_HEAD_SIZE), True))
                if m_head.get("meta", {}).get("sz", 0) > 0:
                    f.seek(m_head["meta"]["off"])
                    raw_meta = json.loads(layout.fast_xor(f.read(m_head["meta"]["sz"]), True).decode("utf-8"))
                    return {k: v for k, v in raw_meta.items() if k != "next_uid"}
        except Exception as e:
            logger.error(f"Failed to read metadata from {path}: {e}")
        return {}

    # --- Extraction API ---
    def _extract_single(self, identifier: Union[str, int], output_path: Union[str, Path], is_asset: bool) -> bool:
        """単一エントリの抽出コア処理"""
        uid = self._resolve_uid(identifier, is_asset=is_asset)
        if uid is None: return False
        
        out_p = Path(output_path)
        out_p.parent.mkdir(parents=True, exist_ok=True) # 親ディレクトリを自動生成
        
        with open(out_p, "wb") as f:
            for chunk in self.iter_entry(uid, chunk_size=self.write_buffer_size, is_asset=is_asset):
                f.write(chunk)
        return True

    def _extract_bulk(self, identifiers: List[Union[str, int]], output_dir: Union[str, Path], is_asset: bool) -> List[str]:
        """複数エントリの抽出コア処理"""
        out_dir = Path(output_dir)
        extracted_paths = []
        
        for ident in identifiers:
            uid = self._resolve_uid(ident, is_asset=is_asset)
            if uid is None: continue
            
            # アーカイブ内の論理パス（name）を使ってディレクトリ構造を再現
            entry = self._assets[uid] if is_asset else self._entries[uid]
            # セキュリティ対策: 絶対パス扱いや上位階層への移動(../)を防ぐ
            safe_name = str(Path(entry.name.lstrip("/"))).replace("..", "_")
            out_path = out_dir / safe_name
            
            if self._extract_single(uid, out_path, is_asset):
                extracted_paths.append(str(out_path))
                
        return extracted_paths

    def extract_entry(self, identifier: Union[str, int], output_path: Union[str, Path]) -> bool:
        return self._extract_single(identifier, output_path, is_asset=False)

    def extract_asset(self, identifier: Union[str, int], output_path: Union[str, Path]) -> bool:
        return self._extract_single(identifier, output_path, is_asset=True)

    def extract_entries(self, identifiers: List[Union[str, int]], output_dir: Union[str, Path]) -> List[str]:
        return self._extract_bulk(identifiers, output_dir, is_asset=False)

    def extract_assets(self, identifiers: List[Union[str, int]], output_dir: Union[str, Path]) -> List[str]:
        return self._extract_bulk(identifiers, output_dir, is_asset=True)

    def extract_all_entries(self, output_dir: Union[str, Path]) -> List[str]:
        valid_uids = [uid for uid, e in self._entries.items() if not e.is_deleted]
        return self.extract_entries(valid_uids, output_dir)

    def extract_all_assets(self, output_dir: Union[str, Path]) -> List[str]:
        valid_uids = [uid for uid, a in self._assets.items() if not a.is_deleted]
        return self.extract_assets(valid_uids, output_dir)

    # --- Navigation & Status ---
    def get_tree(self, parent_path: Optional[str] = None, include_deleted: bool = False) -> dict:
        root_label = "/"
        target_entries = self._entries.items()
        
        prefix = ""
        if parent_path:
            prefix = parent_path.replace("\\", "/").strip("/")
            root_label = prefix.split("/")[-1]
            # list_entries を使って対象UIDを抽出
            uids = [u for u, n in self.list_entries(prefix, recursive=True)]
            target_entries = [(u, self._entries[u]) for u in uids]
        
        root = {"type": "directory", "name": root_label, "children": {}}
        for uid, entry in target_entries:
            if not include_deleted and entry.is_deleted: continue
            
            fullname = entry.name.replace("\\", "/").strip("/")
            if prefix:
                if fullname.startswith(prefix + "/"):
                    rel_name = fullname[len(prefix)+1:]
                elif fullname == prefix:
                    continue # 親ディレクトリ自身は含めない（children構造のため）
                else:
                    continue
                parts = rel_name.split("/")
            else:
                parts = fullname.split("/")
                
            curr = root
            for i, p in enumerate(parts):
                if i == len(parts) - 1:
                    curr["children"][p] = {"type": "file", "uid": uid, "name": p}
                else:
                    if p not in curr["children"]:
                        curr["children"][p] = {"type": "directory", "name": p, "children": {}}
                    curr = curr["children"][p]
        return root

    def get_stats(self) -> dict:
        return {
            "path": str(self.path),
            "size": self.path.stat().st_size if self.path.exists() else 0,
            "entries": len(self.list_entries()),
            "assets": len(self.list_assets()),
            "is_dirty": self._is_dirty,
            "revision": self._revision
        }

    def get_debug_info(self) -> dict:
        return {
            "uuid": self._uuid.hex() if isinstance(self._uuid, bytes) else str(self._uuid),
            "revision": self._revision,
            "payload_end": self._payload_end_offset,
            "is_dirty": self._is_dirty,
            "entries_count": len(self._entries),
            "assets_count": len(self._assets),
            "archive_meta": self._archive_meta,
            "entry_meta": self._entry_meta
        }
