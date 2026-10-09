"""The operator CLI against the test database (and the fake lab for ``discover``)."""

import re
import uuid

import pytest
import typer.rich_utils
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from typer.testing import CliRunner

from netops.cli import app
from netops.db import models as m
from netops.netaccess import set_target_resolver
from netops_fakes.local import LocalLab
from netops_fakes.topology import load
from tests.integration.support import FAKELAB_TOPOLOGY, PASSWORD, USERNAME, run

pytestmark = pytest.mark.integration

runner = CliRunner()

_ANSI = re.compile(r"\x1b\[[0-9;]*m")
_BOX = re.compile(r"[\u2500-\u257f]")  # Rich panel borders


@pytest.fixture(autouse=True)
def render_like_ci(monkeypatch: pytest.MonkeyPatch) -> None:
    """Typer forces Rich terminal output (colours, boxed errors) when GITHUB_ACTIONS is
    set; render that way here too, so local runs see what CI sees."""
    monkeypatch.setattr(typer.rich_utils, "FORCE_TERMINAL", True)


def plain(output: str) -> str:
    """CLI output without colours, panel borders and line wrapping."""
    return " ".join(_BOX.sub(" ", _ANSI.sub("", output)).split())


def test_credentials_are_read_from_stdin_and_never_shown(profiles: list[uuid.UUID]) -> None:
    secret = "cli-" + uuid.uuid4().hex
    added = runner.invoke(
        app,
        ["credentials", "add", "campus-ro", "--username", "netops-ro", "--password-stdin"],
        input=f"{secret}\n",
    )
    assert added.exit_code == 0, added.output
    assert secret not in plain(added.output)

    async def stored(session: AsyncSession) -> m.CredentialProfile | None:
        return await session.scalar(
            select(m.CredentialProfile).where(m.CredentialProfile.name == "campus-ro")
        )

    profile = run(stored)
    assert profile is not None
    assert profile.password is not None
    assert profile.password.get_secret_value() == secret

    listed = runner.invoke(app, ["credentials", "list"])
    assert listed.exit_code == 0
    assert "campus-ro" in plain(listed.output)
    assert secret not in plain(listed.output)

    again = runner.invoke(
        app,
        ["credentials", "add", "campus-ro", "--username", "x", "--password-stdin"],
        input="other\n",
    )
    assert again.exit_code == 2
    assert "exists (use --update to replace it)" in plain(again.output)
    unchanged = run(stored)
    assert unchanged is not None
    assert unchanged.username == "netops-ro"


def test_passwords_cannot_be_given_as_arguments(profiles: list[uuid.UUID]) -> None:
    result = runner.invoke(
        app, ["credentials", "add", "p", "--username", "u", "--password", "visible"]
    )
    assert result.exit_code == 2  # usage error: there is no such option


def test_discover_inline_and_list_devices(profiles: list[uuid.UUID]) -> None:
    with LocalLab(load(FAKELAB_TOPOLOGY), USERNAME, PASSWORD) as lab:
        set_target_resolver(lab.resolve)
        try:
            result = runner.invoke(
                app,
                [
                    "discover",
                    "--seed",
                    "10.255.0.2",
                    "--subnet",
                    "10.255.0.0/24",
                    "--profile",
                    "lab-outdated",
                    "--profile",
                    "lab",
                    "--inline",
                ],
            )
        finally:
            set_target_resolver(None)
    assert result.exit_code == 0, result.output
    assert "8 discovered" in plain(result.output)
    assert "1 duplicate" in plain(result.output)
    assert PASSWORD not in plain(result.output)

    listed = runner.invoke(app, ["devices", "list"])
    assert listed.exit_code == 0
    assert "11 devices" in plain(listed.output)
    assert "out_of_scope" in plain(listed.output)
    one = runner.invoke(app, ["devices", "list", "--q", "FOC1111D003"])
    assert "dist2" in plain(one.output)
    assert "1 devices" in plain(one.output)
