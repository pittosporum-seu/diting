"""谛听 · CLI 冒烟测试

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
        assert "0.1.0" in result.output

    def test_l0_symbols(self):
        """diting l0 --symbols 002475 退出码 0。"""
        runner = CliRunner()
        result = runner.invoke(cli, ["l0", "--symbols", "002475"])
        assert result.exit_code == 0
        assert "002475" in result.output

    def test_l0_multi_symbols(self):
        """diting l0 --symbols 多只标的。"""
        runner = CliRunner()
        result = runner.invoke(cli, ["l0", "--symbols", "002475,603659"])
        assert result.exit_code == 0
        assert "002475" in result.output
        assert "603659" in result.output

    def test_l1_with_engines(self):
        """diting l1 显示引擎列表和错误处理。"""
        runner = CliRunner()
        result = runner.invoke(
            cli, ["l1", "--symbols", "002475", "--engines", "wyckoff,vmd_rsi"]
        )
        # 数据源不可用时优雅降级，输出中应包含标的代码
        assert "002475" in result.output
        # 检查是否输出了可用引擎信息
        assert any(w in result.output for w in ["wyckoff", "引擎", "L1"])

    def test_l2_with_watchlist(self):
        """diting l2 显示基本信息。"""
        runner = CliRunner()
        result = runner.invoke(
            cli, ["l2", "--watchlist", "config/watchlist.example.csv"]
        )
        assert "L2" in result.output

    def test_run_command(self):
        """diting run 输出包含层级信息。"""
        runner = CliRunner()
        result = runner.invoke(cli, ["run", "--symbols", "002475"])
        assert "层级" in result.output or "谛听" in result.output


