# Sakura Backup Manager

ローカルディレクトリをさくらインターネットのレンタルサーバーに暗号化ストリーミングバックアップするCLIツール。

## 特徴

- **ストリーミングバックアップ**: ローカルに一時ファイルを作成せずSSH経由で直接転送
- **AES-256暗号化**: openssl AES-256-CBC + PBKDF2 による強力な暗号化
- **完全なメタデータ保持**: tar でタイムスタンプ・権限・所有者情報を保存
- **SHA1整合性検証**: リモートファイルのハッシュ検証（PHP経由、FreeBSD対応）
- **対話型UI**: バックアップ・リストア・一覧・検証をメニュー操作

## セットアップ

```bash
# 1. .envファイルを作成
cp .env.sample .env
# .env を編集してSSH認証情報を入力

# 2. 依存パッケージ
pip install pyyaml

# 3. 必要なCLIツール
# sshpass, openssl, tar が必要
```

## 使い方

```bash
python3 sakura_backup.py
```

## アーカイブ形式

- `tar czf` (gzip圧縮、全メタデータ保持) + `openssl enc -aes-256-cbc -pbkdf2` (AES-256暗号化)
- ファイル名: `<SHA1ハッシュ>.tar.gz.enc`
- バックアップ台帳: `archives.yaml`

## パイプライン

```
[Backup]  tar → openssl enc → ssh "cat > remote"
[Restore] ssh "cat remote" → openssl dec → tar extract
```
