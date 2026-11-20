# Medic

医疗信息本地快速检索工具 | Zero-dependency full-text search for medical & knowledge base docs.

一个用 **纯 Python 标准库** 实现的本地全文检索工具，专为医院信息科场景设计，
也适用于任何需要快速搜索本地文档/代码/知识库的场景。

## ✨ 特性

- **零依赖**：只用 Python 内置的 `sqlite3`（FTS5）+ `re`，无第三方包
- **单文件**：整个工具就是一个 `.py` 文件，拷到任何机器就能用
- **中英文全文检索**：基于 SQLite FTS5 `unicode61` 分词器
- **正则检索**：支持 `re` 语法，逐文件逐行匹配
- **文件类型过滤**：`-e .md,.csv` 按扩展名过滤
- **上下文展示**：匹配行前后 N 行，行号标注，关键词高亮
- **增量更新**：`-u` 模式只索引新增/修改的文件
- **索引统计**：查看文件数、行数、类型分布、索引大小

## 🚀 快速开始

```bash
# 无需安装，直接运行
python medic.py index /path/to/your/docs

# 全文检索
python medic.py search 人员证件类型

# 指定文件类型 + 减少上下文
python medic.py search 费用 -e .md,.csv -c 1

# 正则检索
python medic.py search -r "psn_id\\d+"

# 查看索引统计
python medic.py stats
```

### 索引位置

默认索引存于 `~/.medic/medic.db`（SQLite 文件）。

## 📦 支持的文档类型

| 类别 | 扩展名 |
|---|---|
| 文档 | `.md` `.txt` `.html` `.htm` |
| 数据 | `.csv` `.tsv` `.json` `.xml` |
| 代码 | `.py` `.java` `.js` `.ts` `.sh` `.sql` |
| 配置 | `.yaml` `.yml` `.ini` `.cfg` `.conf` |
| 日志 | `.log` |

单个文件超过 10MB 或位于 `node_modules`、`.git`、`__pycache__` 等目录会自动跳过。

## 🏗️ 工作原理

```
目录扫描 → 逐行读取 → 写入 FTS5 虚拟表（path, line_no, content）
            ↓
搜索时 → FTS5 MATCH（全文）或 逐行正则匹配
        → 按文件分组 → 读原文取上下文 → 高亮输出
```

**FTS5 vs 正则模式对比**：

| 模式 | 原理 | 速度 | 适用场景 |
|---|---|---|---|
| 全文（默认） | SQLite FTS5 倒排索引 | ⚡ 毫秒级 | 关键词搜索 |
| 正则 `-r` | 逐文件逐行 `re.search` | 🐢 较慢 | 模式匹配、提取 |

## 📁 项目结构

```
medic/
├── medic.py          # 主程序（单文件，~350 行）
├── tests/
│   └── test_medic.py # 单元测试
├── examples/
│   └── demo_data/    # 示例数据
├── README.md
├── LICENSE
└── pyproject.toml
```

## 🔌 作为库使用

```python
import medic

# 构建索引
medic.build_index("/path/to/docs")

# 全文检索
medic.search("诊断", ext_filter=".md,.csv", context=3)

# 正则检索
medic.search(r"psn_id\d+", use_regex=True)

# 查看统计
medic.stats()
```

## ⚙️ 自定义配置

可修改 `medic.py` 顶部的常量来自定义行为：

```python
INDEX_DIR   = os.path.expanduser("~/.medic")   # 索引目录
INDEX_FILE  = os.path.join(INDEX_DIR, "medic.db")
SUPPORTED_EXTS = {".md", ".csv", ...}          # 支持的文件类型
SKIP_DIRS   = {"node_modules", ".git", ...}    # 跳过的目录
```

## 🧪 测试

```bash
python -m pytest tests/ -v
# 或
python -m unittest discover -s tests -v
```

## 📄 License

MIT License — 见 [LICENSE](LICENSE)

## 🙏 致谢

- [SQLite FTS5](https://www.sqlite.org/fts5.html) — 全文检索引擎
- 专为医院信息科日常工作设计，适用于医保接口文档、HIS 表结构、运维知识库等场景
