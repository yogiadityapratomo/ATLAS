from __future__ import annotations

import pytest

from atlas.core.config import REPO_ROOT, Secret, load_settings
from atlas.core.errors import ConfigError


def test_defaults_without_any_env():
    s = load_settings(environ={})
    assert s.env == "dev"
    assert s.db_host == "localhost"
    assert s.db_port == 5432
    assert s.db_name == "atlas"
    assert s.db_web.user == "atlas_web"
    assert s.db_app.user == "atlas_app"
    assert (s.db_pool_min, s.db_pool_max) == (2, 5)
    assert s.allow_live_nbu is False
    assert s.log_dir == REPO_ROOT / "logs"


def test_values_are_parsed_and_typed(make_settings):
    s = make_settings(
        ATLAS_ENV="STAGING",
        ATLAS_DB_PORT="5433",
        ATLAS_DB_POOL_MIN="1",
        ATLAS_DB_POOL_MAX="3",
        ATLAS_ALLOW_LIVE_NBU="1",
        ATLAS_LOG_LEVEL="debug",
    )
    assert s.env == "staging"
    assert s.db_port == 5433
    assert (s.db_pool_min, s.db_pool_max) == (1, 3)
    assert s.allow_live_nbu is True
    assert s.log_level == "debug"


def test_all_invalid_values_reported_at_once():
    with pytest.raises(ConfigError) as info:
        load_settings(
            environ={
                "ATLAS_ENV": "production",
                "ATLAS_DB_PORT": "abc",
                "ATLAS_ALLOW_LIVE_NBU": "maybe",
                "ATLAS_DB_POOL_MIN": "5",
                "ATLAS_DB_POOL_MAX": "2",
            }
        )
    invalid = info.value.details["invalid"]
    assert len(invalid) == 4
    joined = " ".join(invalid)
    for key in ("ATLAS_ENV", "ATLAS_DB_PORT", "ATLAS_ALLOW_LIVE_NBU", "ATLAS_DB_POOL_MIN"):
        assert key in joined
    assert info.value.error_id.startswith("ERR-")


def test_prod_requires_db_passwords():
    with pytest.raises(ConfigError, match="wajib diisi di prod"):
        load_settings(environ={"ATLAS_ENV": "prod", "ATLAS_DB_PASSWORD_WEB": "x1y2z3"})
    ok = load_settings(
        environ={"ATLAS_ENV": "prod", "ATLAS_DB_PASSWORD_WEB": "w-pass", "ATLAS_DB_PASSWORD_APP": "a-pass"}
    )
    assert ok.env == "prod"


def test_password_never_appears_in_repr_or_target(make_settings):
    s = make_settings(ATLAS_DB_PASSWORD_WEB="SuperRahasia123", ATLAS_DB_PASSWORD_APP="LainLagi456")
    assert "SuperRahasia123" not in repr(s)
    assert "SuperRahasia123" not in str(s.db_web)
    assert "SuperRahasia123" not in str(s.db_target("web"))
    assert "password" not in s.db_target("web")
    assert s.db_web.password.get() == "SuperRahasia123"
    assert sorted(s.secret_values()) == ["LainLagi456", "SuperRahasia123"]


def test_conninfo_carries_credentials_for_driver_only(make_settings):
    s = make_settings(ATLAS_DB_PASSWORD_APP="AppPass789", ATLAS_DB_PORT="5440")
    info = s.db_conninfo("app", application_name="atlas-test")
    assert "user=atlas_app" in info
    assert "password=AppPass789" in info
    assert "port=5440" in info
    assert "application_name=atlas-test" in info


def test_secret_wrapper():
    assert repr(Secret("abc")) == "Secret('***')"
    assert repr(Secret("")) == "Secret('')"
    assert not Secret("")
    assert Secret("abc") == Secret("abc")


def test_env_file_is_read_and_process_env_wins(tmp_path):
    env_file = tmp_path / ".env"
    env_file.write_text("ATLAS_DB_NAME=dari_file\nATLAS_DB_PORT=6000\n", encoding="utf-8")
    s = load_settings(env_file=env_file, environ={"ATLAS_DB_PORT": "6001"})
    assert s.db_name == "dari_file"
    assert s.db_port == 6001


def test_relative_and_absolute_log_dir(tmp_path):
    assert load_settings(environ={"ATLAS_LOG_DIR": "var/log"}).log_dir == REPO_ROOT / "var/log"
    assert load_settings(environ={"ATLAS_LOG_DIR": str(tmp_path)}).log_dir == tmp_path
