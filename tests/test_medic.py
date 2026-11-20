"""medic 单元测试"""

import os
import shutil
import sqlite3
import sys
import tempfile
import unittest
from unittest.mock import patch

# 把 medic.py 所在目录加入 sys.path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import medic


class MedicTestCase(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        """创建临时测试目录和文件。"""
        cls.tmpdir = tempfile.mkdtemp(prefix="medic_test_")
        cls.data_dir = os.path.join(cls.tmpdir, "data")
        os.makedirs(cls.data_dir, exist_ok=True)

        # 创建测试文件
        f1 = os.path.join(cls.data_dir, "test1.md")
        with open(f1, "w", encoding="utf-8") as f:
            f.write("# 测试文件 1\n人员证件类型 psn_cert_type 代码：\n01 居民身份证\n02 军官证\n")

        f2 = os.path.join(cls.data_dir, "test2.csv")
        with open(f2, "w", encoding="utf-8") as f:
            f.write("医疗类别 med_type 代码：\n11 门诊\n12 住院\n结算时填写 med_type。\n")

        f3 = os.path.join(cls.data_dir, "ignored.txt")
        os.makedirs(os.path.join(cls.data_dir, "node_modules"), exist_ok=True)
        with open(os.path.join(cls.data_dir, "node_modules", "skip.md"),
                  "w", encoding="utf-8") as f:
            f.write("这个文件应该在 node_modules 里，会被跳过\n")

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.tmpdir, ignore_errors=True)

    def _point_index_to_tmp(self):
        """把 medic.INDEX_DIR/INDEX_FILE 指向临时目录。"""
        idx_dir = os.path.join(self.tmpdir, "index")
        idx_file = os.path.join(idx_dir, "medic.db")
        patcher_dir = patch.object(medic, "INDEX_DIR", idx_dir)
        patcher_file = patch.object(medic, "INDEX_FILE", idx_file)
        patcher_dir.start()
        patcher_file.start()
        self.addCleanup(patcher_dir.stop)
        self.addCleanup(patcher_file.stop)
        return idx_file

    # ── 索引构建测试 ───────────────────────────────────────────────────

    def test_build_index_creates_db(self):
        idx_file = self._point_index_to_tmp()
        medic.build_index(self.data_dir, rebuild=True)
        self.assertTrue(os.path.exists(idx_file))

    def test_build_index_file_count(self):
        self._point_index_to_tmp()
        medic.build_index(self.data_dir, rebuild=True)
        conn = sqlite3.connect(medic.INDEX_FILE)
        rows = conn.execute(
            "SELECT COUNT(*) FROM files"
        ).fetchone()[0]
        # test1.md + test2.csv = 2（node_modules 里的 skip.md 被跳过）
        self.assertEqual(rows, 2)
        conn.close()

    def test_build_index_line_count(self):
        self._point_index_to_tmp()
        medic.build_index(self.data_dir, rebuild=True)
        conn = sqlite3.connect(medic.INDEX_FILE)
        rows = conn.execute("SELECT COUNT(*) FROM fts").fetchone()[0]
        self.assertGreater(rows, 0)
        conn.close()

    # ── 全文检索测试 ───────────────────────────────────────────────────

    def test_fts_search_found(self):
        self._point_index_to_tmp()
        medic.build_index(self.data_dir, rebuild=True)
        # 捕获 search 的输出
        import io
        from unittest.mock import patch
        with patch("sys.stdout", new_callable=io.StringIO) as mock_out:
            medic.search("人员证件类型")
        output = mock_out.getvalue()
        self.assertIn("人员证件类型", output)
        self.assertIn("psn_cert_type", output)

    def test_fts_search_no_match(self):
        self._point_index_to_tmp()
        medic.build_index(self.data_dir, rebuild=True)
        import io
        from unittest.mock import patch
        with patch("sys.stdout", new_callable=io.StringIO) as mock_out:
            medic.search("这个关键词不应该存在xyz123")
        output = mock_out.getvalue()
        self.assertIn("0 处匹配", output)

    def test_fts_search_with_ext_filter(self):
        self._point_index_to_tmp()
        medic.build_index(self.data_dir, rebuild=True)
        import io
        from unittest.mock import patch
        with patch("sys.stdout", new_callable=io.StringIO) as mock_out:
            medic.search("med_type", ext_filter=".csv")
        output = mock_out.getvalue()
        self.assertIn("test2.csv", output)
        # test1.md 不应该出现
        self.assertNotIn("test1.md", output)

    # ── 正则检索测试 ───────────────────────────────────────────────────

    def test_regex_search_found(self):
        self._point_index_to_tmp()
        medic.build_index(self.data_dir, rebuild=True)
        import io
        from unittest.mock import patch
        with patch("sys.stdout", new_callable=io.StringIO) as mock_out:
            medic.search(r"psn_cert_type", use_regex=True)
        output = mock_out.getvalue()
        self.assertIn("psn_cert_type", output)

    def test_regex_search_invalid_pattern(self):
        self._point_index_to_tmp()
        medic.build_index(self.data_dir, rebuild=True)
        import io
        from unittest.mock import patch
        with patch("sys.stdout", new_callable=io.StringIO) as mock_out:
            medic.search(r"[invalid", use_regex=True)
        output = mock_out.getvalue()
        self.assertIn("正则表达式错误", output)

    # ── 上下文测试 ─────────────────────────────────────────────────────

    def test_context_shows_surrounding_lines(self):
        self._point_index_to_tmp()
        medic.build_index(self.data_dir, rebuild=True)
        import io
        from unittest.mock import patch
        with patch("sys.stdout", new_callable=io.StringIO) as mock_out:
            medic.search("med_type", context=1)
        output = mock_out.getvalue()
        # 上下文=1 时，匹配行前后各 1 行都应出现
        self.assertIn("住院", output)

    # ── 统计测试 ──────────────────────────────────────────────────────

    def test_stats_output(self):
        self._point_index_to_tmp()
        medic.build_index(self.data_dir, rebuild=True)
        import io
        from unittest.mock import patch
        with patch("sys.stdout", new_callable=io.StringIO) as mock_out:
            medic.stats()
        output = mock_out.getvalue()
        self.assertIn("索引统计", output)
        self.assertIn(".md", output)

    # ── _tokenize_fts_query 测试 ───────────────────────────────────────

    def test_tokenize_fts_query_single(self):
        result = medic._tokenize_fts_query("诊断")
        self.assertEqual(result, '"诊断"')

    def test_tokenize_fts_query_multi(self):
        result = medic._tokenize_fts_query("费用 结算")
        self.assertEqual(result, '"费用" AND "结算"')

    def test_tokenize_fts_query_empty(self):
        result = medic._tokenize_fts_query("   ")
        self.assertIsNone(result)

    # ── _highlight 测试 ────────────────────────────────────────────────

    def test_highlight_found(self):
        text = "人员证件类型 psn_cert_type 代码"
        result = medic._highlight(text, "人员证件类型")
        self.assertIn("\033[1;33m", result)
        self.assertIn("人员证件类型", result)

    def test_highlight_not_found(self):
        text = "这里没有匹配的词"
        result = medic._highlight(text, "不存在的词")
        self.assertEqual(result, text)


if __name__ == "__main__":
    unittest.main()
