import pytest
from fastapi import HTTPException
from pydantic import ValidationError

from forge.models import Credentials, RunInput
from forge.security import PASSWORDS, contained_file


@pytest.mark.parametrize(
    "name", ["../secret", "/tmp/x", "app/../x", "app//x", "a\\x", ".env", "a/.env", "a\x00b"]
)
def test_paths_reject_escape_and_hidden(tmp_path, name):
    with pytest.raises(HTTPException):
        contained_file(tmp_path, name)


def test_symlink_inside_root_is_rejected(tmp_path):
    (tmp_path / "source").mkdir()
    (tmp_path / "link").symlink_to(tmp_path / "source", target_is_directory=True)
    with pytest.raises(HTTPException):
        contained_file(tmp_path, "link/page.tsx")


def test_relative_source_is_allowed(tmp_path):
    assert contained_file(tmp_path, "app/page.tsx") == tmp_path / "app/page.tsx"


def test_password_hash_is_argon2id_and_verifies():
    encoded = PASSWORDS.hash("isolated-test-password")
    assert encoded.startswith("$argon2id$v=19$m=19456,t=2,p=1$")
    assert PASSWORDS.verify(encoded, "isolated-test-password")


def test_clients_cannot_select_role_or_owner():
    with pytest.raises(ValidationError):
        Credentials(username="tester", password="isolated-test-password", role="admin")
    with pytest.raises(ValidationError):
        RunInput(prompt="todo", owner_id="client-selected")
