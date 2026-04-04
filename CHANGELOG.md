# Changelog / 変更履歴

All notable changes to this project will be documented in this file.
本プロジェクトにおける重要な変更点はすべてこのファイルに記録されます。

---

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
