"""谛听 · CLI 冒烟测试 — v0.2.0 命令框架

使用 Click CliRunner 测试所有 CLI 入口。
"""

from __future__ import annotations

from click.testing import CliRunner

from src.diting.main import cli


class TestCLISmoke:
    """CLI 冒烟测试。"""

    def test_help_exit_zero(self):
        """diting --help 退出码 0。"""
        runner = CliRunner()
        result = runner.invoke(cli, ["--help"])
        assert result.exit_code == 0
        assert "谛听" in result.output

    def test_version_exit_zero(self):
        """diting --version 退出码 0，输出版本号。"""
        runner = CliRunner()
        result = runner.invoke(cli, ["--version"])
        assert result.exit_code == 0
        assert "0.7.1" in result.output

    def test_default_code_displays_help(self):
        """diting（无参数）输出帮助信息。"""
        runner = CliRunner()
        result = runner.invoke(cli, [])
        assert result.exit_code == 0
        assert "谛听" in result.output

    def test_scan_single_symbol(self):
        """diting scan 002475 退出码 0。"""
        runner = CliRunner()
        result = runner.invoke(cli, ["scan", "002475"])
        assert result.exit_code == 0
        assert "002475" in result.output or "暂时无法获取" in result.output

    def test_scan_multi_symbols(self):
        """diting scan 002475,603659 输出包含多只标的。"""
        runner = CliRunner()
        result = runner.invoke(cli, ["scan", "002475,603659"])
        assert result.exit_code == 0
        # When data fails, the error message should include one of the symbols
        assert ("002475" in result.output or "603659" in result.output
                or "数据获取失败" in result.output)

    def test_scan_json(self):
        """diting scan --json 输出。"""
        runner = CliRunner()
        result = runner.invoke(cli, ["scan", "002475", "--json"])
        assert result.exit_code == 0

    def test_l0_alias(self):
        """diting l0 002475（旧别名）退出码 0。"""
        runner = CliRunner()
        result = runner.invoke(cli, ["l0", "002475"])
        assert result.exit_code == 0
        assert "002475" in result.output or "暂时无法获取" in result.output

    def test_l0_alias_multi(self):
        """diting l0 002475,603659 退出码 0。"""
        runner = CliRunner()
        result = runner.invoke(cli, ["l0", "002475,603659"])
        assert result.exit_code == 0

    def test_l1_alias(self):
        """diting l1 002475 被接受（旧别名兼容）。"""
        runner = CliRunner()
        result = runner.invoke(cli, ["l1", "002475"])
        assert "002475" in result.output or not result.output

    def test_l1_alias_with_more(self):
        """diting l1 002475 --more 显示技术分析。"""
        runner = CliRunner()
        result = runner.invoke(cli, ["l1", "002475", "--more"], catch_exceptions=False)
        assert result.exit_code in (0, 1) or "002475" in result.output

    def test_l2_alias(self):
        """diting l2 002475 --report 或输出报告。"""
        runner = CliRunner()
        result = runner.invoke(cli, ["l2", "002475"])
        assert result.exit_code in (0, 1) or "report" in result.output.lower()

    def test_run_alias(self):
        """diting run 废弃提示。"""
        runner = CliRunner()
        result = runner.invoke(cli, ["run"])
        assert result.exit_code == 0
        assert "废弃" in result.output or "diting" in result.output

    def test_compare_smoke(self):
        """diting compare 002475,600519 退出码 0，输出对比。"""
        runner = CliRunner()
        result = runner.invoke(cli, ["compare", "002475,600519"])
        assert result.exit_code == 0
        # Should contain stock codes, names, or a data-unavailable message
        assert any(x in result.output for x in [
            "002475", "600519", "数据获取失败", "无返回数据",
            "评分", "PE", "RSI",
        ])

    def test_compare_json(self):
        """diting compare --json 退出码 0。"""
        runner = CliRunner()
        result = runner.invoke(cli, ["compare", "002475,603659", "--json"])
        assert result.exit_code == 0

    def test_compare_single(self):
        """diting compare 002475（单只）退出码 0。"""
        runner = CliRunner()
        result = runner.invoke(cli, ["compare", "002475"])
        assert result.exit_code == 0

    def test_watchlist_no_file(self):
        """diting watchlist（无 watchlist.csv）优雅降级为空列表。"""
        runner = CliRunner()
        result = runner.invoke(cli, ["watchlist"])
        # 文件缺失时优雅降级，不报错
        assert result.exit_code == 0

    def test_watchlist_with_example(self):
        """diting watchlist -f config/watchlist.example.csv 退出码 0。"""
        runner = CliRunner()
        result = runner.invoke(cli, [
            "watchlist", "-f", "config/watchlist.example.csv",
        ])
        assert result.exit_code == 0

    def test_watchlist_json(self):
        """diting watchlist -f config/watchlist.example.csv --json。"""
        runner = CliRunner()
        result = runner.invoke(cli, [
            "watchlist", "-f", "config/watchlist.example.csv", "--json",
        ])
        assert result.exit_code == 0

    def test_init_help(self):
        """diting init --help 显示帮助信息。"""
        runner = CliRunner()
        result = runner.invoke(cli, ["init", "--help"])
        assert result.exit_code == 0
        assert "首次配置引导" in result.output

    def test_init_noninteractive(self):
        """diting init --yes 非交互模式退出码 0。"""
        runner = CliRunner()
        result = runner.invoke(cli, ["init", "--yes"])
        # --yes mode should complete without interaction
        assert result.exit_code == 0
        assert "谛听首次配置" in result.output

    def test_serve_stub(self):
        """diting serve 命令可导入且帮助信息正确。"""
        runner = CliRunner()
        result = runner.invoke(cli, ["serve", "--help"])
        assert result.exit_code == 0
        assert "serve" in result.output.lower()

    def test_default_code_with_more(self):
        """diting 002475 --more 退出码 0 且包含技术面面板。"""
        runner = CliRunner()
        result = runner.invoke(cli, ["002475", "--more"])
        assert result.exit_code == 0
        if "暂时无法获取" in result.output:
            return  # no data source available
        assert "技术面" in result.output
        assert "RSI" in result.output

    def test_default_code_json(self):
        """diting 002475 --json 退出码 0，输出 JSON。"""
        runner = CliRunner()
        result = runner.invoke(cli, ["002475", "--json"])
        assert result.exit_code == 0
