"""资产备份与恢复（v0.16）。

运行时资产都在 data/ 下且被 .gitignore 忽略，机器一丢或 data 目录误删就无法再生
（尤其 780+ 条人工/机翻译文）。本模块把「不可再生或重建成本高」的资产打成一个
带时间戳的 zip：

纳入备份：
- news_translations.json / translations.json（翻译库，核心资产）
- news-read.json（已读状态）、watch.json（关注词）
- source-health.json、source-suggestions.json（源体检与发现结果）
- news.db（30 天资讯库，重建要重新拉全网）

不纳入：cache/（可重抓）、news-* 时间戳报告与 weekly-*（可重渲染）、
plugin-news.json（由 DB+翻译库重渲染生成）。

纯标准库（zipfile + json），备份文件名 data/backups/backup-YYYYMMDD-HHMMSS.zip，
zip 内保留相对 data/ 的路径，恢复时按同路径写回（先写 .tmp 再 replace）。
"""
from __future__ import annotations

import json
import zipfile
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"
BACKUP_DIR = DATA / "backups"

# 相对 data/ 的路径；存在才打包，缺失跳过（不报错，方便精简部署）
BACKUP_FILES = [
    "news_translations.json",
    "translations.json",
    "news-read.json",
    "source-health.json",
    "source-suggestions.json",
    "sources/watch.json",
    "news.db",
]


def create_backup(dest_dir: Path | None = None, log=None) -> Path:
    """打一个备份 zip，返回 zip 路径。至少要打包到 1 个文件，否则抛错。"""
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    out_dir = dest_dir or BACKUP_DIR
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / f"backup-{stamp}.zip"

    included, missing, sizes = [], [], {}
    with zipfile.ZipFile(out_path, "w", zipfile.ZIP_DEFLATED, compresslevel=6) as zf:
        for rel in BACKUP_FILES:
            src = DATA / rel
            if not src.exists():
                missing.append(rel)
                continue
            zf.write(src, arcname=rel)
            included.append(rel)
            sizes[rel] = src.stat().st_size
        # 清单放在 zip 最后，恢复时可先读
        manifest = {
            "created_at": datetime.now().astimezone().isoformat(timespec="seconds"),
            "engine": "ai-news-radar",
            "included": included,
            "missing": missing,
            "bytes": sizes,
        }
        zf.writestr("backup-manifest.json", json.dumps(manifest, ensure_ascii=False, indent=2))

    if not included:
        out_path.unlink(missing_ok=True)
        raise RuntimeError("没有任何可备份的资产文件（data/ 下备份清单全部缺失）")
    if log:
        log(f"备份 {len(included)} 个资产 → {out_path}（{out_path.stat().st_size // 1024} KB，"
            f"缺失 {len(missing)} 个）")
    return out_path


def list_backups(dest_dir: Path | None = None) -> list[Path]:
    """按时间倒序列出备份 zip。"""
    out_dir = dest_dir or BACKUP_DIR
    if not out_dir.exists():
        return []
    return sorted(out_dir.glob("backup-*.zip"), reverse=True)


def restore_backup(zip_path: Path | None = None, log=None) -> dict:
    """从 zip 恢复资产到 data/。zip_path 为 None 时取最新备份。返回 manifest。"""
    if zip_path is None:
        backs = list_backups()
        if not backs:
            raise FileNotFoundError(f"没有可用备份：{BACKUP_DIR}")
        zip_path = backs[0]
    if not zip_path.exists():
        raise FileNotFoundError(zip_path)

    restored = []
    with zipfile.ZipFile(zip_path) as zf:
        names = [n for n in zf.namelist() if n != "backup-manifest.json"]
        for name in names:
            # 防 zip-slip：arcname 必须是相对路径且不跳出 data/
            rel = Path(name)
            if rel.is_absolute() or ".." in rel.parts:
                raise ValueError(f"备份内含非法路径，拒绝恢复：{name}")
            target = DATA / rel
            target.parent.mkdir(parents=True, exist_ok=True)
            tmp = target.with_suffix(target.suffix + ".restore-tmp")
            tmp.write_bytes(zf.read(name))
            tmp.replace(target)
            restored.append(name)
        try:
            manifest = json.loads(zf.read("backup-manifest.json").decode("utf-8"))
        except KeyError:
            manifest = {"included": restored}
    if log:
        log(f"从 {zip_path.name} 恢复 {len(restored)} 个资产：{', '.join(restored)}")
    return manifest
