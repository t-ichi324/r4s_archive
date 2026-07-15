# Changelog / 変更履歴

All notable changes to this project will be documented in this file.
本プロジェクトにおける重要な変更点はすべてこのファイルに記録されます。

---

## [1.1.0] - 2026-07-15

### Fixed (修正)
- **Extraction API crash**: `extract_entry` / `extract_asset` and bulk extraction crashed with `AttributeError` (`write_buffer_size`).
  - 抽出系 API が `AttributeError` で必ず失敗する不具合を修正。
- **Windows path traversal on extraction**: Logical names containing drive letters (`C:/...`) or absolute paths could escape the output directory. Unsafe path components are now stripped, with a final containment check.
  - 抽出時にドライブレターや絶対パスを含む論理名が出力ディレクトリ外へ書き込まれる脆弱性を修正。
- **Entry corruption when a source file vanished**: `save()` now validates all pending sources *before* touching the archive and aborts with `FileNotFoundError`.
  - 保存前にソースファイルが消えていた場合、書き込み前に検証して中止するように修正（オフセット破損を防止）。
- **Silent load failure destroying data**: A corrupt/unreadable manifest previously loaded as an "empty" archive, and a subsequent `save()` truncated the payload. Loading now raises `R4SCorruptError` instead.
  - マニフェスト破損時に「空アーカイブ」として開いてしまい、その後の保存で全データが消える問題を修正。破損時は `R4SCorruptError` を送出。
- **`optimize()` with `keep_open=True` failed on Windows** (`os.replace` on an open handle). Read handles are now closed and reopened around the replace.
  - `keep_open=True` 時に `optimize()` が Windows で失敗する問題を修正。
- **XOR key-phase fragility**: `fast_xor` now takes an absolute `key_offset`, so obfuscation no longer silently depends on chunk sizes being multiples of the key length.
  - チャンク長が鍵長の倍数であることへの暗黙依存を排除（`key_offset` による位相指定）。

### Added (追加)
- **Crash-safe append-only save**: `save()` no longer truncates before writing. New data + manifest + footer are appended; on load, a damaged tail triggers a backward scan that recovers the most recent valid revision. Dead space is reclaimed by `optimize()`.
  - クラッシュセーフな追記型保存。書き込み途中の異常終了でも直近の正常リビジョンへ自動復旧（後方スキャン）。死領域は `optimize()` で回収。
- **Format v2 (manifest magic `R4S2`)**: per-record CRC32 + mtime, footer CRC32. v1 archives remain readable and are upgraded to v2 on next save.
  - フォーマット v2: エントリごとの CRC32 / 更新日時、フッター CRC32 を追加。v1 は読み込み互換・保存時に自動移行。
- **`verify_entry(identifier, is_asset=False)`**: validates stored data against its recorded CRC32 (`True`/`False`/`None`=no CRC recorded).
  - 保存済み CRC32 との照合 API を追加。

### Changed (変更)
- **Security wording**: the XOR layer is now documented as *obfuscation*, not encryption. Known-plaintext prefixes (e.g. image signatures) allow key recovery, and data beyond `scramble_size` is stored as-is.
  - XOR 層は「暗号化」ではなく「難読化」であることをドキュメントに明記。
- Removed `logging.basicConfig()` side effect at import time (library etiquette).
  - import 時の `logging.basicConfig()` 副作用を削除。

## [1.0.1] - 2026-04-15

### Added (追加)
- **Directory Renaming**: Implemented `R4SArchive.rename_directory(old_dir, new_dir)` to batch rename entries and assets.
  - 指定したフォルダ（プレフィックス）以下の全エントリーとアセットを一括リネームする `R4SArchive.rename_directory` を実装。
- **Directory Removal**: Implemented `R4SArchive.remove_directory(target_dir)` to batch remove entries and assets.
  - 指定したフォルダ以下の全データを一括で削除マークする `R4SArchive.remove_directory` を実装。
- **Asset Renaming**: Implemented `R4SArchive.rename_asset(key, new_key)` for individual asset renaming.
  - アセット個別のリネームに対応する `R4SArchive.rename_asset` を実装。
- **Tree Filtering**: Added filtering support to `R4SArchive.get_tree(parent_path=...)`.
  - 指定したディレクトリを起点とするサブツリー生成機能を追加。

## [1.0.0] - 2026-04-04

### Added (追加)
- **Variable Key Length Support**: Added support for 8 (LOW), 16 (MID), and 32 (HIGH/256-bit) byte keys via `R4SKeyLen` Enum.
  - `R4SKeyLen` Enum による 8 (LOW), 16 (MID), 32 (HIGH/256-bit) バイト鍵のサポート。
- **Professional CLI Manager**: Implemented `main.py` with subcommands (`create`, `add`, `list`, `optimize`).
  - サブコマンド形式の CLI マネージャー (`main.py`) の実装。
- **Comprehensive Documentation**: Added bilingual README and API Reference.
  - 日英二ヶ国語対応の README および API リファレンスの追加。

### Changed (変更)
- **Refactored Core Logic**: Separated binary layout (`R4SLayout`) from high-level API (`R4SArchive`).
  - バイナリ構造 (`R4SLayout`) と高位 API (`R4SArchive`) の分離。
- **Improved Windows Stability**: Enhanced file handle management and added `os.fsync()` after saves.
  - ファイルハンドル管理の適正化および保存時の `os.fsync()` 追加による Windows 環境での安定性向上。

### Fixed (修正)
- **Critical Flag Leak**: Fixed a bug where `_is_ready` was not set in `R4SArchive.open()`, causing `change_password()` to fail silently.
  - `R4SArchive.open()` で `_is_ready` フラグが設定されず、パスワード変更がサイレント無視される重大なバグを修正。
- **Type Mismatch in Hashing**: Fixed potential hash inconsistencies caused by `IntEnum` types in `struct.pack`.
  - `struct.pack` における `IntEnum` 型に起因するハッシュ値の不整合を修正。

---
[1.0.0]: https://github.com/your-username/r4s-project/releases/tag/v1.0.0
