#!/usr/bin/env python3
"""
medic - 医疗信息本地快速检索工具
==================================
单文件实现，零外部依赖（仅使用 Python 标准库 + SQLite FTS5）。

特性：
  - 支持中英文全文检索（SQLite FTS5）
  - 正则表达式检索
  - 文件类型过滤
  - 匹配行上下文展示 + 行号标注
  - 终端高亮显示
  - 增量索引更新
  - 索引统计

用法:
    python medic.py index <目录>        # 构建/更新索引
    python medic.py index <目录> -u     # 增量更新
    python medic.py search <关键词>     # 全文检索
    python medic.py search <关键词> -e .md,.csv  # 指定文件类型
    python medic.py search -r <正则>    # 正则检索
    python medic.py stats               # 查看索引统计

依赖：Python 3.7+（仅标准库，无第三方包）
作者：lh187git
License：MIT
"""

import argparse
import os
import re
import sqlite3
import sys
from datetime import datetime

__version__ = "0.1.0"

# ── 索引文件位置 ──────────────────────────────────────────────────────
INDEX_DIR = os.path.expanduser("~/.medic")
INDEX_FILE = os.path.join(INDEX_DIR, "medic.db")

# 支持的文件扩展名
SUPPORTED_EXTS = {
    ".txt", ".md", ".csv", ".json", ".xml", ".html", ".htm",
    ".sql", ".py", ".java", ".js", ".ts", ".sh", ".yaml",
    ".yml", ".log", ".ini", ".cfg", ".conf", ".tsv", ".yaml",
}

# 跳过的目录名
SKIP_DIRS = {"node_modules", ".git", "__pycache__", ".venv", "venv",
             "build", "dist", ".idea", ".vscode", ".medic"}


# ── 工具函数 ──────────────────────────────────────────────────────────

def _ensure_index_dir():
    os.makedirs(INDEX_DIR, exist_ok=True)


def _get_conn():
    _ensure_index_dir()
    conn = sqlite3.connect(INDEX_FILE)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("""
        CREATE TABLE IF NOT EXISTS files (
            id INTEGER PRIMARY KEY,
            path TEXT UNIQUE,
            ext TEXT,
            size INTEGER,
            indexed_at TEXT,
            mtime REAL
        )
    """)
    conn.execute("""
        CREATE VIRTUAL TABLE IF NOT EXISTS fts USING fts5(
            path,
            line_no UNINDEXED,
            content,
            tokenize = 'unicode61'
        )
    """)
    return conn


def _tokenize_fts_query(query: str) -> str:
    """将用户输入转为 FTS5 安全查询（多词 AND 语义）。"""
    tokens = []
    for word in re.split(r'\s+', query.strip()):
        if not word:
            continue
        word = word.replace('"', '""')
        tokens.append(f'"{word}"')
    return " AND ".join(tokens) if tokens else None


# ── 索引构建 ──────────────────────────────────────────────────────────

def build_index(target_dir: str, rebuild: bool = False):
    """扫描 target_dir 下所有支持的文件，写入 FTS5 索引。"""
    target_dir = os.path.abspath(target_dir)
    if not os.path.isdir(target_dir):
        print(f"❌ 目录不存在: {target_dir}")
        sys.exit(1)

    conn = _get_conn()
    if rebuild:
        conn.execute("DELETE FROM files")
        conn.execute("DELETE FROM fts")
        conn.commit()

    now = datetime.now().isoformat()
    indexed = 0
    skipped = 0

    for root, dirs, files in os.walk(target_dir):
        dirs[:] = [d for d in dirs if d not in SKIP_DIRS]
        for fname in files:
            ext = os.path.splitext(fname)[1].lower()
            if ext not in SUPPORTED_EXTS:
                skipped += 1
                continue
            fpath = os.path.join(root, fname)
            try:
                size = os.path.getsize(fpath)
                if size > 10 * 1024 * 1024:
                    skipped += 1
                    continue
                mtime = os.path.getmtime(fpath)
                with open(fpath, "r", encoding="utf-8", errors="ignore") as f:
                    lines = f.readlines()
            except (OSError, PermissionError):
                skipped += 1
                continue

            conn.execute(
                "INSERT OR REPLACE INTO files (path, ext, size, indexed_at, mtime) "
                "VALUES (?, ?, ?, ?, ?)",
                (fpath, ext, size, now, mtime),
            )
            fts_rows = []
            for line_no, line in enumerate(lines, 1):
                stripped = line.rstrip("\n")
                if stripped.strip():
                    fts_rows.append((fpath, str(line_no), stripped))
            if fts_rows:
                conn.executemany(
                    "INSERT INTO fts (path, line_no, content) VALUES (?, ?, ?)",
                    fts_rows,
                )
            conn.commit()
            indexed += 1

    conn.close()
    print(f"✅ 索引完成: 共 {indexed} 个文件, 跳过 {skipped} 个")
    print(f"📍 索引位置: {INDEX_FILE}")


def update_index(target_dir: str):
    """增量更新：只索引新文件或删除已不存在的文件。"""
    target_dir = os.path.abspath(target_dir)
    conn = _get_conn()

    # 删除已不存在的文件记录
    existing = set(
        r[0] for r in conn.execute(
            "SELECT path FROM files WHERE path LIKE ?",
            (target_dir.replace(os.sep, "/") + "%",)
        ).fetchall()
    )

    actual_files = set()
    for root, dirs, files in os.walk(target_dir):
        dirs[:] = [d for d in dirs if d not in SKIP_DIRS]
        for fname in files:
            ext = os.path.splitext(fname)[1].lower()
            if ext in SUPPORTED_EXTS:
                actual_files.add(os.path.join(root, fname))

    for gone in existing - actual_files:
        conn.execute("DELETE FROM files WHERE path = ?", (gone,))
        conn.execute("DELETE FROM fts WHERE path = ?", (gone,))

    now = datetime.now().isoformat()
    updated = 0
    for fpath in sorted((actual_files - existing) | (actual_files & existing)):
        try:
            mtime = os.path.getmtime(fpath)
            row = conn.execute(
                "SELECT mtime FROM files WHERE path = ?", (fpath,)
            ).fetchone()
            if row:
                if mtime > row[0]:
                    conn.execute("DELETE FROM fts WHERE path = ?", (fpath,))
                    conn.execute("DELETE FROM files WHERE path = ?", (fpath,))
                    row = None
            if row is None:
                conn.execute(
                    "INSERT INTO files (path, ext, size, indexed_at, mtime) "
                    "VALUES (?, ?, ?, ?, ?)",
                    (fpath, os.path.splitext(fpath)[1].lower(),
                     os.path.getsize(fpath), now, mtime),
                )
                with open(fpath, "r", encoding="utf-8", errors="ignore") as f:
                    lines = f.readlines()
                fts_rows = [
                    (fpath, str(i), line.rstrip("\n"))
                    for i, line in enumerate(lines, 1) if line.strip()
                ]
                if fts_rows:
                    conn.executemany(
                        "INSERT INTO fts (path, line_no, content) VALUES (?, ?, ?)",
                        fts_rows,
                    )
                updated += 1
        except (OSError, PermissionError):
            pass
    conn.commit()
    conn.close()
    print(f"✅ 增量更新: 新增/更新 {updated} 个文件")


# ── 搜索 ─────────────────────────────────────────────────────────────

def search(query: str, ext_filter: str = None,
           context: int = 2, limit: int = 20,
           use_regex: bool = False):
    """全文检索。use_regex=True 时用正则模式。"""
    conn = _get_conn()
    if not os.path.exists(INDEX_FILE):
        print("⚠️  尚无索引，请先运行: python medic.py index <目录>")
        conn.close()
        sys.exit(1)

    exts = []
    ext_clause = ""
    if ext_filter:
        exts = [e.strip().lower() for e in ext_filter.split(",")]
        placeholders = ",".join("?" * len(exts))
        ext_clause = f" AND f.ext IN ({placeholders})"

    if use_regex:
        # 正则检索
        try:
            compiled = re.compile(query, re.IGNORECASE)
        except re.error as e:
            print(f"❌ 正则表达式错误: {e}")
            conn.close()
            return

        if ext_filter:
            sql = f"""
                SELECT f.path, f.ext, f.size
                FROM files f
                WHERE f.path IS NOT NULL
                AND f.ext IN ({",".join('?' * len(exts))})
            """
            params = list(exts)
        else:
            sql = "SELECT path, ext, size FROM files WHERE path IS NOT NULL"
            params = []

        rows = conn.execute(sql, params).fetchall()
        print(f"\n🔍 正则「{query}」→ {len(rows)} 个候选文件\n")
        shown = 0
        total_found = 0
        for path, ext, size in rows:
            try:
                with open(path, "r", encoding="utf-8", errors="ignore") as f:
                    lines = f.readlines()
            except (OSError, PermissionError):
                continue
            matches_in_file = []
            for line_no, line in enumerate(lines, 1):
                if compiled.search(line):
                    matches_in_file.append((line_no, line.rstrip("\n")))
            if matches_in_file:
                total_found += len(matches_in_file)
                print(f"\n── {path} ──")
                for line_no, content in matches_in_file[:limit]:
                    highlighted = _highlight_regex(content, compiled)
                    print(f"  {line_no:>5d}  ✨ {highlighted}")
                    shown += 1
                    if shown >= limit:
                        break
                if shown >= limit:
                    break
        if not total_found:
            print("（无匹配结果）")
        elif total_found > shown:
            print(f"\n⚠️  只显示前 {shown} 处，共 {total_found} 处匹配")

    else:
        # 普通全文检索
        fts_query = _tokenize_fts_query(query)
        if not fts_query:
            print("⚠️  检索词为空")
            conn.close()
            return

        sql = f"""
            SELECT fts.path, fts.line_no, fts.content, f.ext
            FROM fts
            JOIN files f ON f.path = fts.path
            WHERE fts MATCH ? {ext_clause}
            LIMIT ?
        """
        params = [fts_query] + list(exts) + [limit * (context + 1) * 2]
        rows = conn.execute(sql, params).fetchall()

        by_file = {}
        for path, line_no, content, ext in rows:
            if path not in by_file:
                by_file[path] = {"ext": ext, "matches": []}
            by_file[path]["matches"].append((int(line_no), content))

        total_matches = sum(len(v["matches"]) for v in by_file.values())
        print(f"\n🔍 检索「{query}」→ {total_matches} 处匹配, "
              f"{len(by_file)} 个文件\n")
        shown = 0
        for path in sorted(by_file.keys()):
            info = by_file[path]
            print(f"\n── {path} ({info['ext']}) ──")
            for line_no, content in info["matches"][:limit]:
                try:
                    with open(path, "r", encoding="utf-8",
                              errors="ignore") as f:
                        all_lines = f.readlines()
                    ctx_start = max(1, line_no - context)
                    ctx_end = min(line_no + context, len(all_lines))
                    for ctx_ln in range(ctx_start, ctx_end + 1):
                        ctx_content = all_lines[ctx_ln - 1].rstrip("\n")
                        if ctx_ln == line_no:
                            highlighted = _highlight(ctx_content, query)
                            print(f"  {ctx_ln:>5d}  ✨ {highlighted}")
                        else:
                            print(f"  {ctx_ln:>5d}     {ctx_content}")
                except (OSError, PermissionError):
                    print(f"  {line_no:>5d}  ✨ {content}")
                shown += 1
                if shown >= limit:
                    break
            if shown >= limit:
                break
        if total_matches > shown:
            print(f"\n⚠️  只显示前 {shown} 处，共 {total_matches} 处匹配")

    conn.close()


def _highlight(text: str, query: str) -> str:
    """在文本中高亮查询词（普通模式）。"""
    words = [w for w in re.split(r'\s+', query.strip()) if w]
    result = text
    for word in words:
        escaped = re.escape(word)
        result = re.sub(escaped,
                         f"\033[1;33m{word}\033[0m",
                         result, flags=re.IGNORECASE)
    return result


def _highlight_regex(text: str, compiled) -> str:
    """正则模式下的匹配高亮。"""
    return compiled.sub(
        lambda m: f"\033[1;33m{m.group()}\033[0m", text
    )


# ── 统计 ──────────────────────────────────────────────────────────────

def stats():
    conn = _get_conn()
    if not os.path.exists(INDEX_FILE):
        print("⚠️  尚无索引")
        return

    total_files = conn.execute("SELECT COUNT(*) FROM files").fetchone()[0]
    total_lines = conn.execute("SELECT COUNT(*) FROM fts").fetchone()[0]
    ext_breakdown = conn.execute(
        "SELECT ext, COUNT(*) AS cnt FROM files "
        "GROUP BY ext ORDER BY cnt DESC"
    ).fetchall()
    index_size = (os.path.getsize(INDEX_FILE)
                  if os.path.exists(INDEX_FILE) else 0)

    print(f"\n📊 索引统计")
    print(f"   文件总数: {total_files}")
    print(f"   总行数:   {total_lines:,}")
    print(f"   索引大小: {index_size / 1024 / 1024:.1f} MB")
    print(f"   位置:     {INDEX_FILE}")
    print(f"\n   文件类型分布:")
    for ext, cnt in ext_breakdown[:15]:
        print(f"     {ext:>10s}  {cnt:>6d}")
    conn.close()


# ── CLI 入口 ─────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        description="medic - 医疗信息本地快速检索工具（零依赖，纯 Python）",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
示例:
  %(prog)s index /path/to/docs        # 全量重建索引
  %(prog)s index /path/to/docs -u     # 增量更新
  %(prog)s search 诊断                # 全文检索
  %(prog)s search 费用 -e .md,.csv    # 指定文件类型
  %(prog)s search -r "psn_id\\\\d+"    # 正则检索
  %(prog)s stats                       # 查看索引统计
        """
    )
    sub = parser.add_subparsers(dest="cmd")

    # index
    p_idx = sub.add_parser("index", help="构建/更新索引")
    p_idx.add_argument("target", help="要索引的目录")
    p_idx.add_argument(
        "-u", "--update", action="store_true",
        help="增量更新（默认全量重建）",
    )

    # search
    p_srch = sub.add_parser("search", help="全文检索")
    p_srch.add_argument("query", help="检索关键词或正则表达式")
    p_srch.add_argument(
        "-r", action="store_true", help="正则模式"
    )
    p_srch.add_argument(
        "-e", "--ext", default=None,
        help="文件扩展名过滤，逗号分隔，如 .md,.csv",
    )
    p_srch.add_argument(
        "-c", "--context", type=int, default=2,
        help="显示匹配行前后各 N 行上下文（默认 2）",
    )
    p_srch.add_argument(
        "-l", "--limit", type=int, default=20,
        help="最大显示结果数（默认 20）",
    )

    # stats
    sub.add_parser("stats", help="查看索引统计")

    args = parser.parse_args()

    if args.cmd == "index":
        if args.update:
            update_index(args.target)
        else:
            build_index(args.target, rebuild=True)
    elif args.cmd == "search":
        search(
            args.query,
            ext_filter=args.ext,
            context=args.context,
            limit=args.limit,
            use_regex=args.r,
        )
    elif args.cmd == "stats":
        stats()
    else:
        parser.print_help()
        sys.exit(1)


if __name__ == "__main__":
    main()
