#!/usr/bin/env python3
"""
Sakura Backup Manager
ローカルディレクトリをさくらインターネットのレンタルサーバーに
暗号化ストリーミングバックアップするCLIツール
"""

import subprocess
import sys
import os
import hashlib
import threading
import shutil
import getpass
from datetime import datetime, timezone, timedelta
from pathlib import Path
from uuid import uuid4

try:
    import yaml
except ImportError:
    print("Error: pyyaml が必要です。pip install pyyaml を実行してください。")
    sys.exit(1)

# Paths
SCRIPT_DIR = Path(__file__).parent
ENV_PATH = SCRIPT_DIR / ".env"
ARCHIVES_PATH = SCRIPT_DIR / "archives.yaml"

# Constants
CHUNK_SIZE = 65536
JST = timezone(timedelta(hours=9))


# ─────────────────────────────────────────────
# Configuration
# ─────────────────────────────────────────────

def load_env():
    """Load .env file and return config dict."""
    if not ENV_PATH.exists():
        print(f"Error: .env が見つかりません: {ENV_PATH}")
        print(".env.sample をコピーして .env を作成してください。")
        sys.exit(1)

    config = {}
    with open(ENV_PATH, "r") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            if "=" in line:
                key, value = line.split("=", 1)
                config[key.strip()] = value.strip()

    required = ["SAKURA_HOST", "SAKURA_USER", "SAKURA_PASSWORD", "SAKURA_BACKUP_DIR"]
    for key in required:
        if key not in config:
            print(f"Error: .env に {key} が設定されていません。")
            sys.exit(1)

    return config


def check_dependencies():
    """Check required CLI tools."""
    for cmd in ["sshpass", "openssl", "tar"]:
        if shutil.which(cmd) is None:
            print(f"Error: {cmd} がインストールされていません。")
            sys.exit(1)


# ─────────────────────────────────────────────
# Archives management
# ─────────────────────────────────────────────

def load_archives():
    """Load archives.yaml."""
    if not ARCHIVES_PATH.exists():
        return {"backups": []}
    with open(ARCHIVES_PATH, "r", encoding="utf-8") as f:
        data = yaml.safe_load(f)
    if not data or "backups" not in data:
        return {"backups": []}
    return data


def save_archives(data):
    """Save archives.yaml."""
    with open(ARCHIVES_PATH, "w", encoding="utf-8") as f:
        yaml.dump(data, f, default_flow_style=False, allow_unicode=True, sort_keys=False)


def next_id(archives):
    """Get next backup ID."""
    if not archives["backups"]:
        return 1
    return max(b["id"] for b in archives["backups"]) + 1


# ─────────────────────────────────────────────
# SSH operations
# ─────────────────────────────────────────────

def ssh_command(config, cmd):
    """Execute remote SSH command."""
    full_cmd = [
        "sshpass", "-p", config["SAKURA_PASSWORD"],
        "ssh", "-o", "StrictHostKeyChecking=no",
        "-o", "ConnectTimeout=10",
        f"{config['SAKURA_USER']}@{config['SAKURA_HOST']}",
        cmd
    ]
    result = subprocess.run(full_cmd, capture_output=True, text=True, timeout=60)
    return result.stdout, result.stderr, result.returncode


def ensure_remote_dir(config):
    """Ensure remote backup directory exists."""
    _, _, rc = ssh_command(config, f"mkdir -p '{config['SAKURA_BACKUP_DIR']}'")
    if rc != 0:
        print(f"Error: リモートディレクトリの作成に失敗しました。")
        return False
    return True


def ssh_remote_sha1(config, remote_path):
    """Get SHA1 hash of remote file using PHP."""
    cmd = f"""php -r 'echo sha1_file("{remote_path}");'"""
    stdout, stderr, rc = ssh_command(config, cmd)
    if rc != 0:
        return None
    return stdout.strip()


def ssh_remote_size(config, remote_path):
    """Get remote file size in bytes."""
    stdout, _, rc = ssh_command(config, f"wc -c < '{remote_path}'")
    if rc != 0:
        return None
    try:
        return int(stdout.strip())
    except ValueError:
        return None


def ssh_remote_exists(config, remote_path):
    """Check if remote file exists."""
    _, _, rc = ssh_command(config, f"test -f '{remote_path}'")
    return rc == 0


def ssh_remote_delete(config, remote_path):
    """Delete remote file."""
    _, _, rc = ssh_command(config, f"rm -f '{remote_path}'")
    return rc == 0


# ─────────────────────────────────────────────
# Utility
# ─────────────────────────────────────────────

def human_size(size_bytes):
    """Convert bytes to human-readable size."""
    for unit in ["B", "KB", "MB", "GB", "TB"]:
        if size_bytes < 1024:
            return f"{size_bytes:.1f} {unit}"
        size_bytes /= 1024
    return f"{size_bytes:.1f} PB"


def get_dir_size(path):
    """Get total size of directory in bytes."""
    result = subprocess.run(["du", "-sb", path], capture_output=True, text=True)
    if result.returncode == 0:
        return int(result.stdout.split()[0])
    return 0


def get_file_count(path):
    """Get number of files in directory."""
    count = 0
    for root, dirs, files in os.walk(path):
        count += len(files)
    return count


def print_header():
    """Print application header."""
    print()
    print("╔══════════════════════════════════════╗")
    print("║        Sakura Backup Manager         ║")
    print("╠══════════════════════════════════════╣")
    print("║  [1] Backup  - ローカル → さくら    ║")
    print("║  [2] Restore - さくら → ローカル    ║")
    print("║  [3] List    - バックアップ一覧     ║")
    print("║  [4] Verify  - リモートファイル検証 ║")
    print("║  [q] Quit                           ║")
    print("╚══════════════════════════════════════╝")
    print()


def print_progress(current, total, prefix="進捗"):
    """Print progress bar."""
    if total == 0:
        return
    pct = min(current / total * 100, 100)
    bar_len = 30
    filled = int(bar_len * current / total)
    filled = min(filled, bar_len)
    bar = "█" * filled + "░" * (bar_len - filled)
    sys.stderr.write(f"\r  {prefix}: [{bar}] {pct:.1f}% ({human_size(current)} / {human_size(total)})  ")
    sys.stderr.flush()


# ─────────────────────────────────────────────
# Backup
# ─────────────────────────────────────────────

def stream_backup(config, source_path, password):
    """
    Streaming backup: tar → openssl enc → ssh
    Returns (sha1_hex, encrypted_size, temp_remote_name) or raises on error.
    """
    parent = os.path.dirname(source_path)
    dirname = os.path.basename(source_path)
    temp_name = f"tmp_{uuid4().hex[:12]}.tar.gz.enc"
    remote_path = f"{config['SAKURA_BACKUP_DIR']}/{temp_name}"

    total_size = get_dir_size(source_path)

    env_with_pass = os.environ.copy()
    env_with_pass["BACKUP_PASS"] = password

    # Process 1: tar (PAX format preserves nanosecond timestamps)
    p_tar = subprocess.Popen(
        ["tar", "--format=posix", "-czf", "-", "-C", parent, dirname],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )

    # Process 2: openssl encrypt
    p_enc = subprocess.Popen(
        ["openssl", "enc", "-aes-256-cbc", "-pbkdf2", "-salt", "-pass", "env:BACKUP_PASS"],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        env=env_with_pass,
    )

    # Process 3: ssh upload
    p_ssh = subprocess.Popen(
        [
            "sshpass", "-p", config["SAKURA_PASSWORD"],
            "ssh", "-o", "StrictHostKeyChecking=no",
            "-o", "ConnectTimeout=10",
            f"{config['SAKURA_USER']}@{config['SAKURA_HOST']}",
            f"cat > '{remote_path}'"
        ],
        stdin=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )

    sha1 = hashlib.sha1()
    encrypted_size = 0
    tar_read_bytes = 0
    error_occurred = None

    def tar_to_enc():
        """Relay tar stdout to openssl stdin."""
        nonlocal tar_read_bytes
        try:
            while True:
                chunk = p_tar.stdout.read(CHUNK_SIZE)
                if not chunk:
                    break
                tar_read_bytes += len(chunk)
                p_enc.stdin.write(chunk)
                print_progress(tar_read_bytes, total_size)
            p_enc.stdin.close()
        except Exception as e:
            nonlocal error_occurred
            error_occurred = e

    def enc_to_ssh():
        """Relay openssl stdout to ssh stdin, computing SHA1."""
        nonlocal encrypted_size
        try:
            while True:
                chunk = p_enc.stdout.read(CHUNK_SIZE)
                if not chunk:
                    break
                sha1.update(chunk)
                p_ssh.stdin.write(chunk)
                encrypted_size += len(chunk)
            p_ssh.stdin.close()
        except Exception as e:
            nonlocal error_occurred
            error_occurred = e

    t1 = threading.Thread(target=tar_to_enc, daemon=True)
    t2 = threading.Thread(target=enc_to_ssh, daemon=True)
    t1.start()
    t2.start()
    t1.join()
    t2.join()

    rc_tar = p_tar.wait()
    rc_enc = p_enc.wait()
    rc_ssh = p_ssh.wait()

    sys.stderr.write("\n")

    if error_occurred:
        # Cleanup partial remote file
        ssh_remote_delete(config, remote_path)
        raise RuntimeError(f"ストリーミング中にエラーが発生: {error_occurred}")

    if rc_tar != 0:
        tar_err = p_tar.stderr.read().decode() if p_tar.stderr else ""
        ssh_remote_delete(config, remote_path)
        raise RuntimeError(f"tar に失敗しました (rc={rc_tar}): {tar_err}")

    if rc_enc != 0:
        enc_err = p_enc.stderr.read().decode() if p_enc.stderr else ""
        ssh_remote_delete(config, remote_path)
        raise RuntimeError(f"暗号化に失敗しました (rc={rc_enc}): {enc_err}")

    if rc_ssh != 0:
        ssh_err = p_ssh.stderr.read().decode() if p_ssh.stderr else ""
        raise RuntimeError(f"SSH転送に失敗しました (rc={rc_ssh}): {ssh_err}")

    return sha1.hexdigest(), encrypted_size, temp_name


def backup_single(config, source, password):
    """Backup a single directory. Returns entry dict on success, None on failure."""
    source = os.path.realpath(source)
    dir_size = get_dir_size(source)
    file_count = get_file_count(source)

    print(f"\n  --- {os.path.basename(source)} ---")
    print(f"  パス: {source}")
    print(f"  サイズ: {human_size(dir_size)}, ファイル数: {file_count:,}")

    # Stream backup
    print(f"  ストリーミングバックアップ中...")
    try:
        sha1_hex, enc_size, temp_name = stream_backup(config, source, password)
    except RuntimeError as e:
        print(f"\n  Error: {e}")
        return None

    # Rename to hash-based name
    temp_remote = f"{config['SAKURA_BACKUP_DIR']}/{temp_name}"
    final_name = f"{sha1_hex}.tar.gz.enc"
    final_remote = f"{config['SAKURA_BACKUP_DIR']}/{final_name}"

    _, _, rc = ssh_command(config, f"mv '{temp_remote}' '{final_remote}'")
    if rc != 0:
        print(f"  Error: リモートファイルのリネームに失敗しました。")
        return None

    # Verify remote
    print(f"  リモートファイルを検証中...")
    remote_sha1 = ssh_remote_sha1(config, final_remote)
    remote_size = ssh_remote_size(config, final_remote)

    if remote_sha1 != sha1_hex:
        print(f"  Error: SHA1不一致! ローカル={sha1_hex}, リモート={remote_sha1}")
        return None

    if remote_size != enc_size:
        print(f"  Error: サイズ不一致! ローカル={enc_size}, リモート={remote_size}")
        return None

    print(f"  ✅ 完了! → {final_name} ({human_size(enc_size)})")

    # Update archives
    archives = load_archives()
    entry = {
        "id": next_id(archives),
        "source_path": source,
        "remote_filename": final_name,
        "sha1": sha1_hex,
        "size_bytes": enc_size,
        "original_size_bytes": dir_size,
        "file_count": file_count,
        "datetime": datetime.now(JST).isoformat(),
        "local_deleted": False,
    }
    archives["backups"].append(entry)
    save_archives(archives)

    return entry


def do_backup(config):
    """Interactive backup flow (supports multiple directories)."""
    print("\n=== Backup: ローカル → さくら ===\n")

    # 1. Collect source paths (one per line, empty line to finish)
    print("  バックアップ元ディレクトリをフルパスで入力してください。")
    print("  (複数ある場合は1行ずつ入力、空行で入力完了)")
    print()

    sources = []
    while True:
        prompt = f"  [{len(sources) + 1}] パス (空行で完了): "
        line = input(prompt).strip()
        if not line:
            break
        path = os.path.expanduser(line)
        if not os.path.isdir(path):
            print(f"      ⚠ ディレクトリが存在しません: {path}")
            continue
        sources.append(os.path.realpath(path))

    if not sources:
        print("  キャンセルしました。")
        return

    # 2. Show summary
    print(f"\n  === 対象ディレクトリ ({len(sources)}件) ===")
    total_size = 0
    for i, src in enumerate(sources, 1):
        size = get_dir_size(src)
        count = get_file_count(src)
        total_size += size
        print(f"  [{i}] {src}")
        print(f"      {human_size(size)}, {count:,} files")
    print(f"\n  合計: {human_size(total_size)}")

    # 3. Password (once for all)
    print()
    password = getpass.getpass("  暗号化パスワード: ")
    if not password:
        print("  Error: パスワードが空です。")
        return
    password_confirm = getpass.getpass("  パスワード確認: ")
    if password != password_confirm:
        print("  Error: パスワードが一致しません。")
        return

    # 4. Confirm
    print()
    confirm = input(f"  {len(sources)}件のバックアップを開始しますか？ [y/N]: ").strip().lower()
    if confirm != "y":
        print("  キャンセルしました。")
        return

    # 5. Ensure remote dir
    if not ensure_remote_dir(config):
        return

    # 6. Process each directory
    succeeded = []
    failed = []
    for i, src in enumerate(sources, 1):
        print(f"\n  ━━━ [{i}/{len(sources)}] ━━━")
        entry = backup_single(config, src, password)
        if entry:
            succeeded.append(entry)
        else:
            failed.append(src)

    # 7. Summary
    print(f"\n  ═══════════════════════════════")
    print(f"  バックアップ結果: {len(succeeded)}/{len(sources)} 成功")
    if failed:
        print(f"  ❌ 失敗:")
        for f in failed:
            print(f"     - {f}")

    if not succeeded:
        return

    # 8. Delete sources
    print()
    if len(succeeded) == 1:
        src = succeeded[0]["source_path"]
        delete = input(f"  ローカルの {src} を削除しますか？ [y/N]: ").strip().lower()
        if delete == "y":
            _delete_source(succeeded[0])
        else:
            print("  ローカルディレクトリは保持されます。")
    else:
        print("  ローカルディレクトリの削除:")
        print("    [a] 全て削除")
        print("    [s] 個別に選択")
        print("    [n] 削除しない")
        choice = input("  選択 > ").strip().lower()

        if choice == "a":
            for entry in succeeded:
                _delete_source(entry)
        elif choice == "s":
            for entry in succeeded:
                d = input(f"  {entry['source_path']} を削除？ [y/N]: ").strip().lower()
                if d == "y":
                    _delete_source(entry)
                else:
                    print(f"    → 保持")
        else:
            print("  ローカルディレクトリは保持されます。")


def _delete_source(entry):
    """Delete local source directory and update archives."""
    try:
        shutil.rmtree(entry["source_path"])
        entry["local_deleted"] = True
        archives = load_archives()
        for b in archives["backups"]:
            if b["id"] == entry["id"]:
                b["local_deleted"] = True
                break
        save_archives(archives)
        print(f"  ✅ 削除: {entry['source_path']}")
    except Exception as e:
        print(f"  Error: 削除失敗 ({entry['source_path']}): {e}")


# ─────────────────────────────────────────────
# Restore
# ─────────────────────────────────────────────

def stream_restore(config, entry, password, dest_path):
    """
    Streaming restore: ssh → openssl dec → tar
    """
    remote_file = f"{config['SAKURA_BACKUP_DIR']}/{entry['remote_filename']}"

    env_with_pass = os.environ.copy()
    env_with_pass["BACKUP_PASS"] = password

    # Process 1: ssh download
    p_ssh = subprocess.Popen(
        [
            "sshpass", "-p", config["SAKURA_PASSWORD"],
            "ssh", "-o", "StrictHostKeyChecking=no",
            "-o", "ConnectTimeout=10",
            f"{config['SAKURA_USER']}@{config['SAKURA_HOST']}",
            f"cat '{remote_file}'"
        ],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )

    # Process 2: openssl decrypt
    p_dec = subprocess.Popen(
        ["openssl", "enc", "-d", "-aes-256-cbc", "-pbkdf2", "-pass", "env:BACKUP_PASS"],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        env=env_with_pass,
    )

    # Process 3: tar extract
    # --same-owner requires root; use --preserve-permissions at minimum
    tar_opts = ["tar", "xzf", "-", "-C", dest_path, "--preserve-permissions"]
    if os.geteuid() == 0:
        tar_opts.append("--same-owner")

    p_tar = subprocess.Popen(
        tar_opts,
        stdin=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )

    total_size = entry.get("size_bytes", 0)
    downloaded = 0
    error_occurred = None

    def ssh_to_dec():
        """Relay ssh stdout to openssl stdin."""
        nonlocal downloaded
        try:
            while True:
                chunk = p_ssh.stdout.read(CHUNK_SIZE)
                if not chunk:
                    break
                downloaded += len(chunk)
                p_dec.stdin.write(chunk)
                print_progress(downloaded, total_size, prefix="ダウンロード")
            p_dec.stdin.close()
        except Exception as e:
            nonlocal error_occurred
            error_occurred = e

    def dec_to_tar():
        """Relay openssl stdout to tar stdin."""
        try:
            while True:
                chunk = p_dec.stdout.read(CHUNK_SIZE)
                if not chunk:
                    break
                p_tar.stdin.write(chunk)
            p_tar.stdin.close()
        except Exception as e:
            nonlocal error_occurred
            error_occurred = e

    t1 = threading.Thread(target=ssh_to_dec, daemon=True)
    t2 = threading.Thread(target=dec_to_tar, daemon=True)
    t1.start()
    t2.start()
    t1.join()
    t2.join()

    rc_ssh = p_ssh.wait()
    rc_dec = p_dec.wait()
    rc_tar = p_tar.wait()

    sys.stderr.write("\n")

    if error_occurred:
        raise RuntimeError(f"リストア中にエラーが発生: {error_occurred}")

    if rc_ssh != 0:
        ssh_err = p_ssh.stderr.read().decode() if p_ssh.stderr else ""
        raise RuntimeError(f"SSH転送に失敗 (rc={rc_ssh}): {ssh_err}")

    if rc_dec != 0:
        dec_err = p_dec.stderr.read().decode() if p_dec.stderr else ""
        raise RuntimeError(f"復号に失敗しました。パスワードが正しいか確認してください。(rc={rc_dec}): {dec_err}")

    if rc_tar != 0:
        tar_err = p_tar.stderr.read().decode() if p_tar.stderr else ""
        raise RuntimeError(f"展開に失敗 (rc={rc_tar}): {tar_err}")


def do_restore(config):
    """Interactive restore flow."""
    print("\n=== Restore: さくら → ローカル ===\n")

    archives = load_archives()
    if not archives["backups"]:
        print("  バックアップが見つかりません。")
        return

    # 1. Show list
    print("  利用可能なバックアップ:")
    print(f"  {'ID':>4}  {'日時':<22}  {'サイズ':>10}  {'ソースパス'}")
    print(f"  {'─'*4}  {'─'*22}  {'─'*10}  {'─'*40}")
    for b in archives["backups"]:
        dt = b.get("datetime", "不明")[:19]
        size = human_size(b.get("original_size_bytes", b.get("size_bytes", 0)))
        deleted = " [削除済]" if b.get("local_deleted") else ""
        print(f"  {b['id']:>4}  {dt:<22}  {size:>10}  {b['source_path']}{deleted}")
    print()

    # 2. Select
    try:
        bid = int(input("  リストアするバックアップID: ").strip())
    except (ValueError, EOFError):
        print("  キャンセルしました。")
        return

    entry = next((b for b in archives["backups"] if b["id"] == bid), None)
    if not entry:
        print(f"  Error: ID {bid} が見つかりません。")
        return

    # 3. Destination
    default_dest = os.path.dirname(entry["source_path"])
    dest_input = input(f"  復元先ディレクトリ [{default_dest}]: ").strip()
    dest = dest_input if dest_input else default_dest

    if not os.path.isdir(dest):
        create = input(f"  {dest} が存在しません。作成しますか？ [y/N]: ").strip().lower()
        if create == "y":
            os.makedirs(dest, exist_ok=True)
        else:
            print("  キャンセルしました。")
            return

    restored_dir = os.path.join(dest, os.path.basename(entry["source_path"]))
    if os.path.exists(restored_dir):
        overwrite = input(f"  {restored_dir} が既に存在します。上書きしますか？ [y/N]: ").strip().lower()
        if overwrite != "y":
            print("  キャンセルしました。")
            return
        shutil.rmtree(restored_dir)

    # 4. Verify remote
    print(f"\n  リモートファイルを検証中...")
    remote_file = f"{config['SAKURA_BACKUP_DIR']}/{entry['remote_filename']}"
    if not ssh_remote_exists(config, remote_file):
        print(f"  Error: リモートファイルが存在しません: {entry['remote_filename']}")
        return

    remote_sha1 = ssh_remote_sha1(config, remote_file)
    if remote_sha1 != entry["sha1"]:
        print(f"  Error: リモートファイルのSHA1が不一致!")
        print(f"    記録: {entry['sha1']}")
        print(f"    実際: {remote_sha1}")
        return
    print(f"  SHA1検証OK: {remote_sha1}")

    # 5. Password
    password = getpass.getpass("\n  復号パスワード: ")
    if not password:
        print("  Error: パスワードが空です。")
        return

    if os.geteuid() != 0:
        print("\n  ⚠ root権限がないため、ファイル所有者の復元はできません。")
        print("    権限・タイムスタンプは可能な範囲で復元されます。")

    # 6. Stream restore
    print(f"\n  ストリーミングリストア中...")
    try:
        stream_restore(config, entry, password, dest)
    except RuntimeError as e:
        print(f"\n  Error: {e}")
        return

    # 7. Verify
    if os.path.isdir(restored_dir):
        restored_size = get_dir_size(restored_dir)
        restored_count = get_file_count(restored_dir)
        print(f"\n  ✅ リストア完了!")
        print(f"  復元先: {restored_dir}")
        print(f"  サイズ: {human_size(restored_size)}")
        print(f"  ファイル数: {restored_count:,}")

        # Update local_deleted status
        if entry.get("local_deleted") and restored_dir == entry["source_path"]:
            entry["local_deleted"] = False
            save_archives(archives)
    else:
        print(f"\n  Warning: 復元されたディレクトリが確認できません: {restored_dir}")


# ─────────────────────────────────────────────
# List / Verify
# ─────────────────────────────────────────────

def do_list(config):
    """Show all archived backups."""
    print("\n=== バックアップ一覧 ===\n")

    archives = load_archives()
    if not archives["backups"]:
        print("  バックアップが登録されていません。")
        return

    for b in archives["backups"]:
        dt = b.get("datetime", "不明")[:19]
        enc_size = human_size(b.get("size_bytes", 0))
        orig_size = human_size(b.get("original_size_bytes", 0))
        deleted = "✅ 削除済" if b.get("local_deleted") else "📁 ローカル存在"
        print(f"  ┌─ ID: {b['id']}")
        print(f"  │ ソース:   {b['source_path']}")
        print(f"  │ 日時:     {dt}")
        print(f"  │ 元サイズ: {orig_size} ({b.get('file_count', '?')} files)")
        print(f"  │ 暗号化:   {enc_size}")
        print(f"  │ SHA1:     {b.get('sha1', '不明')}")
        print(f"  │ リモート: {b.get('remote_filename', '不明')}")
        print(f"  │ 状態:     {deleted}")
        print(f"  └─")
        print()


def do_verify(config):
    """Verify remote backup files."""
    print("\n=== リモートファイル検証 ===\n")

    archives = load_archives()
    if not archives["backups"]:
        print("  バックアップが登録されていません。")
        return

    all_ok = True
    for b in archives["backups"]:
        remote_file = f"{config['SAKURA_BACKUP_DIR']}/{b['remote_filename']}"
        sys.stdout.write(f"  ID {b['id']:>3}: {b['remote_filename']} ... ")
        sys.stdout.flush()

        if not ssh_remote_exists(config, remote_file):
            print("❌ ファイルなし")
            all_ok = False
            continue

        remote_size = ssh_remote_size(config, remote_file)
        if remote_size != b.get("size_bytes"):
            print(f"❌ サイズ不一致 (記録:{b.get('size_bytes')}, 実際:{remote_size})")
            all_ok = False
            continue

        remote_sha1 = ssh_remote_sha1(config, remote_file)
        if remote_sha1 != b.get("sha1"):
            print(f"❌ SHA1不一致")
            all_ok = False
            continue

        print(f"✅ OK ({human_size(remote_size)})")

    print()
    if all_ok:
        print("  全てのバックアップファイルが正常です。")
    else:
        print("  ⚠ 一部のバックアップに問題があります。")


# ─────────────────────────────────────────────
# Main
# ─────────────────────────────────────────────

def main():
    check_dependencies()
    config = load_env()

    while True:
        print_header()
        choice = input("  選択 > ").strip().lower()

        if choice == "1":
            do_backup(config)
        elif choice == "2":
            do_restore(config)
        elif choice == "3":
            do_list(config)
        elif choice == "4":
            do_verify(config)
        elif choice in ("q", "quit", "exit"):
            print("\n  さようなら!\n")
            break
        else:
            print("  無効な選択です。")

        print()
        input("  [Enter] でメニューに戻る...")


if __name__ == "__main__":
    main()
