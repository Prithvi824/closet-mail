"""Smoke test proving the package imports and the test runner works."""

# 3rd party imports
from typer.testing import CliRunner

# local imports
from mailalias import __version__
from mailalias.cli import app


def test_cli_version_prints_package_version() -> None:
    """The `version` command prints the package version.

    Returns:
        None.
    """
    result = CliRunner().invoke(app, ["version"])
    assert result.exit_code == 0
    assert result.stdout.strip() == __version__
