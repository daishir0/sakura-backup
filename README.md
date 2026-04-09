# Sakura Backup Manager

ローカルディレクトリをさくらインターネットのレンタルサーバーに暗号化ストリーミングバックアップするCLIツール。

## 特徴

- **ストリーミングバックアップ**: ローカルに一時ファイルを作成せずSSH経由で直接転送
- **AES-256暗号化**: openssl AES-256-CBC + PBKDF2 による強力な暗号化
- **完全なメタデータ保持**: tar でタイムスタンプ・権限・所有者情報を保存
- **SHA1整合性検証**: リモートファイルのハッシュ検証（PHP経由、FreeBSD対応）
- **対話型UI**: バックアップ・リストア・一覧・検証をメニュー操作
- **CLIモード**: `backup` サブコマンドで非対話実行（cron / systemd timer 向け）
- **任意ファイル名**: CLIでは `--name` で固定ファイル名指定、台帳は同名エントリを自動更新（1ファイル1エントリ維持）

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

### メインメニュー

```
╔══════════════════════════════════════╗
║        Sakura Backup Manager         ║
╠══════════════════════════════════════╣
║  [1] Backup  - ローカル → さくら    ║
║  [2] Restore - さくら → ローカル    ║
║  [3] List    - バックアップ一覧     ║
║  [4] Verify  - リモートファイル検証 ║
║  [q] Quit                           ║
╚══════════════════════════════════════╝

  選択 > 1
```

### 例1: 単一ディレクトリをバックアップ

```
=== Backup: ローカル → さくら ===

  バックアップ元ディレクトリをフルパスで入力してください。
  (複数ある場合は1行ずつ入力、空行で入力完了)

  [1] パス (空行で完了): /home/user/projects/my-app
  [2] パス (空行で完了):

  === 対象ディレクトリ (1件) ===
  [1] /home/user/projects/my-app
      512.3 MB, 8,421 files

  合計: 512.3 MB

  暗号化パスワード: ********
  パスワード確認: ********

  1件のバックアップを開始しますか？ [y/N]: y

  ━━━ [1/1] ━━━

  --- my-app ---
  パス: /home/user/projects/my-app
  サイズ: 512.3 MB, ファイル数: 8,421
  ストリーミングバックアップ中...
  進捗: [██████████████████████████████] 100.0% (512.3 MB / 512.3 MB)
  リモートファイルを検証中...
  ✅ 完了! → a1b2c3d4e5f6.tar.gz.enc (198.7 MB)

  ローカルの /home/user/projects/my-app を削除しますか？ [y/N]: y
  ✅ 削除: /home/user/projects/my-app
```

### 例2: 複数ディレクトリを一括バックアップ

```
  [1] パス (空行で完了): /home/user/data/dataset-A
  [2] パス (空行で完了): /home/user/data/dataset-B
  [3] パス (空行で完了): /home/user/data/dataset-C
  [4] パス (空行で完了):

  === 対象ディレクトリ (3件) ===
  [1] /home/user/data/dataset-A
      1.2 GB, 15,230 files
  [2] /home/user/data/dataset-B
      3.5 GB, 42,100 files
  [3] /home/user/data/dataset-C
      890.0 MB, 7,800 files

  合計: 5.6 GB

  暗号化パスワード: ********       ← パスワードは1回だけ入力
  パスワード確認: ********

  3件のバックアップを開始しますか？ [y/N]: y

  ━━━ [1/3] ━━━
  --- dataset-A ---
  ✅ 完了! → f1e2d3c4b5a6.tar.gz.enc (420.5 MB)

  ━━━ [2/3] ━━━
  --- dataset-B ---
  ✅ 完了! → 9a8b7c6d5e4f.tar.gz.enc (1.1 GB)

  ━━━ [3/3] ━━━
  --- dataset-C ---
  ✅ 完了! → 1122334455aa.tar.gz.enc (310.2 MB)

  ═══════════════════════════════
  バックアップ結果: 3/3 成功

  ローカルディレクトリの削除:
    [a] 全て削除
    [s] 個別に選択          ← 個別に削除/保持を選べる
    [n] 削除しない
  選択 > s
  /home/user/data/dataset-A を削除？ [y/N]: y
  ✅ 削除: /home/user/data/dataset-A
  /home/user/data/dataset-B を削除？ [y/N]: y
  ✅ 削除: /home/user/data/dataset-B
  /home/user/data/dataset-C を削除？ [y/N]: n
    → 保持
```

### 例3: リストア

```
  選択 > 2

=== Restore: さくら → ローカル ===

  利用可能なバックアップ:
    ID  日時                    サイズ      ソースパス
  ────  ──────────────────────  ──────────  ────────────────
     1  2026-03-23T14:30:00     512.3 MB   /home/user/projects/my-app [削除済]
     2  2026-03-23T15:00:00       1.2 GB   /home/user/data/dataset-A [削除済]
     3  2026-03-23T15:10:00       3.5 GB   /home/user/data/dataset-B [削除済]

  リストアするバックアップID: 1
  復元先ディレクトリ [/home/user/projects]:

  リモートファイルを検証中...
  SHA1検証OK: a1b2c3d4e5f6...

  復号パスワード: ********

  ストリーミングリストア中...
  ダウンロード: [██████████████████████████████] 100.0% (198.7 MB / 198.7 MB)

  ✅ リストア完了!
  復元先: /home/user/projects/my-app
  サイズ: 512.3 MB
  ファイル数: 8,421
```

### 例4: バックアップ一覧と検証

```
  選択 > 3                        ← 一覧表示

=== バックアップ一覧 ===

  ┌─ ID: 1
  │ ソース:   /home/user/projects/my-app
  │ 日時:     2026-03-23T14:30:00
  │ 元サイズ: 512.3 MB (8421 files)
  │ 暗号化:   198.7 MB
  │ SHA1:     a1b2c3d4e5f6...
  │ リモート: a1b2c3d4e5f6.tar.gz.enc
  │ 状態:     ✅ 削除済
  └─

  選択 > 4                        ← リモート検証

=== リモートファイル検証 ===

  ID   1: a1b2c3d4e5f6.tar.gz.enc ... ✅ OK (198.7 MB)
  ID   2: f1e2d3c4b5a6.tar.gz.enc ... ✅ OK (420.5 MB)
  ID   3: 9a8b7c6d5e4f.tar.gz.enc ... ✅ OK (1.1 GB)

  全てのバックアップファイルが正常です。
```

## CLIモード（非対話）

cron や systemd timer からの自動実行向け。引数ありで起動するとCLIモードになり、引数なしだと従来の対話メニューが起動します。

### `backup` サブコマンド

```bash
python3 sakura_backup.py backup \
    --source /path/to/target/dir \
    --name my-backup \
    --password 'YOUR_PASSWORD' \
    [--delete-source] \
    [--quiet]
```

| オプション | 必須 | 説明 |
|---|---|---|
| `--source PATH` | ✓ | バックアップ対象ディレクトリ（絶対パス推奨） |
| `--name NAME` | ✓ | リモートファイル名。`.tar.gz.enc` 自動付与。同名ファイルは常に上書き |
| `--password PASS` | ✓ | 暗号化パスワード（`ps aux` で可視化される点に注意） |
| `--delete-source` | ー | 成功時にローカルを削除（既定OFF） |
| `--quiet` | ー | 進捗バーを抑制（cronログ向け） |

### ファイル名の制約

`--name` は `[a-zA-Z0-9-_.]` のみ許可（シェルインジェクション対策）。`/`, `..`, スペース, シェルメタ文字は拒否。

### 終了コード

| コード | 意味 |
|---|---|
| 0 | 成功 |
| 1 | 引数エラー（必須欠如、ファイル名不正、ソース未存在） |
| 2 | 環境/依存エラー（`.env` 不備、`sshpass` 不在、リモート接続失敗） |
| 3 | バックアップ失敗（tar/openssl/ssh 失敗、検証不一致） |

### 対話モードとの関係

- **CLIモードでバックアップ** → `archives.yaml` に同名エントリとして登録（既存あれば更新、なければ追加）
- **対話モードでリストア** → CLIでバックアップしたファイルもそのまま ID 指定で復元可能
- リストア機能はCLI化されていません（対話モード `[2] Restore` から実行）

## systemd timer での自動運用

### 構成例（週次バックアップ）

ラッパースクリプト `cron-backup.sh` が同梱されており、バックアップ実行と Slack 通知（成功・失敗両方）をまとめて行います。

**`/etc/systemd/system/sakura-backup-example.service`**

```ini
[Unit]
Description=Sakura backup: example
After=network-online.target
Wants=network-online.target

[Service]
Type=oneshot
User=your-user
Group=your-user
WorkingDirectory=/path/to/sakura-backup
Environment=HOME=/home/your-user
ExecStart=/path/to/sakura-backup/cron-backup.sh /path/to/target my-backup-name 'YOUR_PASSWORD'
```

**`/etc/systemd/system/sakura-backup-example.timer`**

```ini
[Unit]
Description=Sakura backup example - weekly Thu 00:00

[Timer]
OnCalendar=Thu *-*-* 00:00:00
Persistent=false
Unit=sakura-backup-example.service

[Install]
WantedBy=timers.target
```

### 登録と確認

```bash
# タイマー有効化
sudo systemctl daemon-reload
sudo systemctl enable --now sakura-backup-example.timer

# 次回実行時刻を確認
systemctl list-timers sakura-backup-example.timer

# 手動で即時実行
sudo systemctl start sakura-backup-example.service

# ログ確認
journalctl -u sakura-backup-example.service -n 100
```

### cron-backup.sh の役割

```
cron-backup.sh <source> <name> <password>
  ↓
sakura_backup.py backup --source ... --name ... --password ... --quiet
  ↓
結果を整形して Slack に通知（成功・失敗どちらも）
  ↓
バックアップの exit code をそのまま返却
```

Slack 通知には `send_slack.py`（別途 `~/.claude/skills/slack-notify/`）を使用。環境に合わせてパスを調整してください。

### 大容量ファイル対応

SHA1検証（リモート側 `php sha1_file()` 実行）は、10GB級の暗号化ファイルでも完走するよう最大1時間のタイムアウトに設定されています。

## アーカイブ形式

- `tar --format=posix -czf` (gzip圧縮、PAXフォーマットでナノ秒精度のタイムスタンプ含む全メタデータ保持) + `openssl enc -aes-256-cbc -pbkdf2` (AES-256暗号化)
- ファイル名:
  - **対話モード**: `<SHA1ハッシュ>.tar.gz.enc`（内容ベースで自動ユニーク化）
  - **CLIモード**: `<--nameで指定>.tar.gz.enc`（固定名、同名は上書き）
- バックアップ台帳: `archives.yaml`

## パイプライン

```
[Backup]  tar → openssl enc → ssh "cat > remote"
[Restore] ssh "cat remote" → openssl dec → tar extract
```
