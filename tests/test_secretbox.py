"""SEC-14: site secrets are encrypted in the database and decrypted only where they are used."""
import pytest
from cryptography.fernet import Fernet

KEY_A, KEY_B = Fernet.generate_key().decode(), Fernet.generate_key().decode()


@pytest.fixture
def svc(tmp_path, monkeypatch):
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{tmp_path / 'sb.db'}")
    monkeypatch.setenv("SECRETS_KEY", KEY_A)
    import lib.db as db
    if db._engine is not None:
        db._engine.dispose()
    db._engine = None
    db._SessionLocal = None
    from sdk import service
    service.init()
    yield service
    if db._engine is not None:
        db._engine.dispose()
    db._engine = None
    db._SessionLocal = None


def test_round_trip_legacy_plaintext_and_no_key(monkeypatch):
    from lib import secretbox as sb
    monkeypatch.setenv("SECRETS_KEY", KEY_A)
    tok = sb.encrypt("hunter2")
    assert tok.startswith("enc:v1:") and "hunter2" not in tok and sb.decrypt(tok) == "hunter2"
    assert sb.encrypt(tok) == tok                                  # idempotent
    assert sb.decrypt("plain-legacy") == "plain-legacy" and sb.decrypt("") == "" and sb.encrypt("") == ""
    monkeypatch.delenv("SECRETS_KEY")
    assert sb.encrypt("x") == "x"                                  # no key: unchanged, as before
    with pytest.raises(sb.SecretError):
        sb.decrypt(tok)                                            # but an encrypted value needs the key


def test_a_wrong_key_fails_without_echoing_the_value(monkeypatch):
    from lib import secretbox as sb
    monkeypatch.setenv("SECRETS_KEY", KEY_A)
    tok = sb.encrypt("topsecret")
    monkeypatch.setenv("SECRETS_KEY", KEY_B)
    with pytest.raises(sb.SecretError) as e:
        sb.decrypt(tok)
    assert "topsecret" not in str(e.value) and tok not in str(e.value)


def test_key_rotation_new_first_old_still_decrypts(monkeypatch):
    from lib import secretbox as sb
    monkeypatch.setenv("SECRETS_KEY", KEY_A)
    old = sb.encrypt("v")
    monkeypatch.setenv("SECRETS_KEY", f"{KEY_B},{KEY_A}")
    assert sb.decrypt(old) == "v"
    assert sb.decrypt(sb.encrypt("w")) == "w"


def test_site_secrets_are_stored_encrypted_but_used_in_plaintext(svc):
    from lib.db import Site, get_session
    svc.upsert_site("enc-site", "E", "wordpress", "https://e.test",
                    {"wp": {"base_url": "https://wp.e.test", "username": "ed", "app_password": "abcd efgh ijkl"},
                     "indexing": {"indexnow_key": "INDEXNOWKEY123"}, "posting_frequency": "weekly"})
    s = get_session()
    try:
        site = s.query(Site).filter_by(slug="enc-site").one()
        raw = site.settings
        assert raw["wp"]["app_password"].startswith("enc:v1:") and "abcd" not in str(raw)
        assert raw["indexing"]["indexnow_key"].startswith("enc:v1:")
        assert raw["wp"]["username"] == "ed" and raw["posting_frequency"] == "weekly"     # non-secrets stay readable
        assert svc._wp_config(site).app_password == "abcd efgh ijkl"                       # decrypted at use
        assert svc._indexing_keys(site)["indexnow_key"] == "INDEXNOWKEY123"
    finally:
        s.close()
    listed = str(svc.list_sites())
    assert "abcd" not in listed and "enc:v1" not in listed and "INDEXNOW" not in listed    # never in a response


def test_resending_a_blank_secret_keeps_the_stored_encrypted_one(svc):
    from lib.db import Site, get_session
    svc.upsert_site("keep", "K", "wordpress", "https://k.test",
                    {"wp": {"base_url": "https://k-wp.test", "username": "u", "app_password": "first-secret"}})
    svc.upsert_site("keep", settings={"wp": {"username": "u2", "app_password": ""}})
    s = get_session()
    try:
        site = s.query(Site).filter_by(slug="keep").one()
        assert site.settings["wp"]["username"] == "u2"
        assert svc._wp_config(site).app_password == "first-secret"
    finally:
        s.close()


def test_the_migration_script_encrypts_existing_plaintext_rows_and_is_idempotent(svc, monkeypatch):
    from lib.db import Site, get_session
    monkeypatch.delenv("SECRETS_KEY")                               # a legacy deployment: plaintext rows
    svc.upsert_site("legacy", "L", "wordpress", "https://l.test",
                    {"wp": {"base_url": "https://l-wp.test", "username": "u", "app_password": "legacy-pass"}})
    monkeypatch.setenv("SECRETS_KEY", KEY_A)
    from scripts import encrypt_site_secrets as mig
    assert mig.run(dry_run=True) == {"sites_changed": 1, "fields_encrypted": 1, "dry_run": True}
    s = get_session()
    try:
        assert s.query(Site).filter_by(slug="legacy").one().settings["wp"]["app_password"] == "legacy-pass"
    finally:
        s.close()
    assert mig.run()["fields_encrypted"] == 1
    assert mig.run()["fields_encrypted"] == 0                       # second run: nothing left to do
    s = get_session()
    try:
        site = s.query(Site).filter_by(slug="legacy").one()
        assert site.settings["wp"]["app_password"].startswith("enc:v1:")
        assert svc._wp_config(site).app_password == "legacy-pass"
    finally:
        s.close()


def test_the_migration_refuses_to_run_without_a_key(monkeypatch):
    monkeypatch.delenv("SECRETS_KEY", raising=False)
    from scripts import encrypt_site_secrets as mig
    assert "SECRETS_KEY is not set" in mig.run()["error"]
