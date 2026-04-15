# R4S Archive API リファレンス (日本語版)

[English version (API.md)](./API.md) | [READMEに戻る](./README_ja.md)

`r4s.archive.R4SArchive` クラスの主要なメソッド仕様について解説します。

---

## 🏗 インスタンス管理

### `R4SArchive.create(path, password=None, key_len=R4SKeyLen.LOW, scramble_size=4096)`
新規に暗号化アーカイブを作成します。
- **引数**:
    - `path`: 作成するファイルのパス（`str` または `Path`）。
    - `password`: 暗号化パスワード。省略時はパスワードなし。
    - `key_len`: 内部鍵の長さ。`R4SKeyLen.LOW(8)`, `MID(16)`, `HIGH(32)` から選択。
    - `scramble_size`: 各ファイルの先頭で XOR スクランブルを行うサイズ（デフォルト 4096バイト）。
- **戻り値**: `R4SArchive` インスタンス。
- **例外**: ファイルが既に存在する場合は `FileExistsError`。

### `R4SArchive.open(path, password=None)`
既存のアーカイブをロードします。
- **引数**:
    - `path`: 既存のアーカイブファイルのパス。
    - `password`: ロードに必要なパスワード。
- **戻り値**: `R4SArchive` インスタンス。
- **例外**: パスワード不一致やヘッダー破損時は `ValueError`。

---

## 📂 エントリー操作 (ファイル管理)

### `set_entry(logical_path, source)`
アーカイブ内にファイルを登録または更新します。
- **引数**:
    - `logical_path`: アーカイブ内での論理パス（ファイル名）。
    - `source`: 追加するデータ（`bytes`）または元のファイルパス（`str`/`Path`）。
- **戻り値**: 割り当てられた `UID`（整数）。
- **注意**: この時点ではメモリ/ステージングに保持され、`save()` で物理ファイルに書き込まれます。

### `rename_entry(identifier, new_name)`
単一のエントリーの名前を変更します。

### `rename_directory(old_dir, new_dir)`
指定したディレクトリプレフィックスを持つすべてのエントリーとアセットを一括でリネーム（移動）します。
- **引数**:
    - `old_dir`: 変更前のディレクトリパス。
    - `new_dir`: 変更後のディレクトリパス。

### `remove_directory(target_dir)`
指定したディレクトリ（プレフィックス）以下のすべてのエントリーとアセットを一括で削除マークします。

### `get_entry(identifier)`
アーカイブ内のデータを取得します。
- **引数**: `identifier`: 論理パス（文字列）または `UID`（整数）。
- **戻り値**: データ本体（`bytes`）。存在しない場合は `None`。

### `remove_entry(identifier)`
エントリーを削除マークします。
- **注意**: インデックス上は削除されますが、物理的な詰め直しは `optimize()` 実行時まで行われません。

### `list_entries(parent_path=None, recursive=True)`
アーカイブ内のエントリ（ファイル）一覧を取得します。
- **引数**:
    - `parent_path`: フィルタリングする親ディレクトリパス（論理パス）。
    - `recursive`: `True` の場合、指定ディレクトリ以下を再帰的に取得します。`False` の場合は直下のみ。
- **戻り値**: `(UID, 論理パス)` のタプルのリスト。

---

## 💎 アセット操作

### `set_asset(key, source, mime="application/octet-stream")`
アーカイブ内にアセット（サムネイルやメタデータ等）を登録します。

### `get_asset(identifier)`
アセットのデータを取得します。

### `rename_asset(identifier, new_key)`
単一のアセットをリネーム（キーの変更）します。

### `list_assets(parent_path=None, recursive=True)`
アーカイブ内のアセット一覧を取得します。
- **引数**: フィルタリングの挙動は `list_entries` と同様です。
- **戻り値**: `(UID, キー)` のタプルのリスト。

### `remove_asset(identifier)`
アセットを削除マークします。

---

## ⚡ セキュリティ & 最適化

### `change_password(new_password)`
暗号化パスワードを変更します。
- **注意**: ヘッダー（鍵のラッピング）のみを更新するため、大容量データであっても一瞬で完了します。`save()` の実行が必要です。

### `optimize(new_key_len=None, new_scramble_size=None)`
アーカイブの全データを再構成（ガベージコレクション・再暗号化）します。
- **引数**:
    - `new_key_len`: 変更後の鍵長。省略時は現在値を維持。
    - `new_scramble_size`: 変更後のスクランブルサイズ。
- **用途**: 削除済みデータの物理削除や、セキュリティ強度（鍵長）のマイグレーションに利用します。

---

## 🔍 ユーティリティ

### `get_tree(parent_path=None, include_deleted=False)`
アーカイブ内の構造をツリー形式（辞書）で取得します。
- **引数**:
    - `parent_path`: 指定した場合、そのディレクトリをルートとする部分木を返します。
    - `include_deleted`: 削除済みエントリーを含めるかどうか。
- **戻り値**: `{"type": "directory/file", "name": "...", "children": {...}}` 形式の辞書。

### `get_stats()`
アーカイブの統計情報（ファイル数、サイズ、リビジョン等）を取得します。

### `save()`
すべての変更（新ファイル、削除、セキュリティ更新）を物理ファイルに確定させます。

### `close()`
すべてのハンドルと一時ファイルをクローズします。Windows 環境では再オープン前に必ず呼ぶ必要があります。
