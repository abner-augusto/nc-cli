import importlib.util
import json
import os
import sys
from importlib.machinery import SourceFileLoader
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
NC_PATH = ROOT / "bin" / "nc-cli"


def load_nc(monkeypatch):
    monkeypatch.setenv("NEXTCLOUD_URL", "https://cloud.example.test")
    monkeypatch.setenv("NEXTCLOUD_USER", "hermes-agent")
    monkeypatch.setenv("NEXTCLOUD_APP_PASSWORD", "secret")
    name = f"ncmod_{id(monkeypatch)}"
    loader = SourceFileLoader(name, str(NC_PATH))
    spec = importlib.util.spec_from_loader(name, loader)
    module = importlib.util.module_from_spec(spec)
    loader.exec_module(module)
    return module


class CurlResult:
    def __init__(self, returncode=0, stdout="", stderr=""):
        self.returncode = returncode
        self.stdout = stdout
        self.stderr = stderr


def test_download_timeout_with_partial_file_fails_and_removes_partial(monkeypatch, tmp_path, capsys):
    nc = load_nc(monkeypatch)
    out = tmp_path / "download.bin"

    monkeypatch.setattr(nc, "curl_with_code", lambda *a, **kw: ("content-length: 100\n", "200", ""))

    def fake_curl(*args, **kwargs):
        target = Path(args[args.index("-o") + 1])
        target.write_bytes(b"partial")
        return CurlResult(returncode=28, stdout="000", stderr="Operation timed out")

    monkeypatch.setattr(nc, "curl", fake_curl)

    rc = nc.cmd_download("/remote.bin", str(out), json_mode=False)

    assert rc == nc.EXIT_NETWORK
    assert not out.exists()
    assert "Download failed" in capsys.readouterr().err


def test_download_size_mismatch_fails_and_removes_partial(monkeypatch, tmp_path, capsys):
    nc = load_nc(monkeypatch)
    out = tmp_path / "download.bin"

    monkeypatch.setattr(nc, "curl_with_code", lambda *a, **kw: ("content-length: 100\n", "200", ""))

    def fake_curl(*args, **kwargs):
        target = Path(args[args.index("-o") + 1])
        target.write_bytes(b"short")
        return CurlResult(returncode=0, stdout="200", stderr="")

    monkeypatch.setattr(nc, "curl", fake_curl)

    rc = nc.cmd_download("/remote.bin", str(out), json_mode=False)

    assert rc == nc.EXIT_NETWORK
    assert not out.exists()
    assert "Size mismatch" in capsys.readouterr().err


@pytest.mark.parametrize("argv,patched_name", [
    (["nc-cli", "upload", "local.txt", "/remote.txt", "--json"], "cmd_upload"),
    (["nc-cli", "download", "/remote.txt", "local.txt", "--json"], "cmd_download"),
    (["nc-cli", "mkdir", "/dir", "--json"], "cmd_mkdir"),
    (["nc-cli", "mv", "/a", "/b", "--json"], "cmd_mv"),
    (["nc-cli", "cp", "/a", "/b", "--json"], "cmd_cp"),
    (["nc-cli", "rm", "/file", "--json"], "cmd_rm"),
    (["nc-cli", "share", "/file", "--json"], "cmd_share"),
])
def test_main_passes_json_mode_to_mutating_commands(monkeypatch, argv, patched_name):
    nc = load_nc(monkeypatch)
    seen = {}

    def fake_command(*args, json_mode=False, **kwargs):
        seen["json_mode"] = json_mode
        return nc.EXIT_OK

    monkeypatch.setattr(sys, "argv", argv)
    monkeypatch.setattr(nc, patched_name, fake_command)

    assert nc.main() == nc.EXIT_OK
    assert seen["json_mode"] is True


def test_rm_refuses_root_without_curl(monkeypatch, capsys):
    nc = load_nc(monkeypatch)

    def fail_if_called(*args, **kwargs):
        raise AssertionError("rm / must not touch WebDAV")

    monkeypatch.setattr(nc, "curl_with_code", fail_if_called)

    rc = nc.cmd_rm("/", json_mode=False)

    assert rc == nc.EXIT_USAGE
    assert "Refusing to delete root" in capsys.readouterr().err


def test_rm_refuses_directory_without_recursive(monkeypatch, capsys):
    nc = load_nc(monkeypatch)

    monkeypatch.setattr(nc, "_remote_type", lambda path: ("dir", "207", ""))

    rc = nc.cmd_rm("/HERMES-DROP/some-dir", recursive=False, force=False, json_mode=False)

    assert rc == nc.EXIT_USAGE
    assert "requires --recursive" in capsys.readouterr().err


def test_rm_refuses_protected_top_level_without_force(monkeypatch, capsys):
    nc = load_nc(monkeypatch)

    monkeypatch.setattr(nc, "_remote_type", lambda path: ("dir", "207", ""))

    rc = nc.cmd_rm("/Obsidian", recursive=True, force=False, json_mode=False)

    assert rc == nc.EXIT_USAGE
    assert "protected path" in capsys.readouterr().err


def test_protected_delete_paths_can_be_overridden_by_env(monkeypatch, capsys):
    monkeypatch.setenv("NC_PROTECTED_DELETE_PATHS", "/Critical,/Team Share")
    nc = load_nc(monkeypatch)

    monkeypatch.setattr(nc, "_remote_type", lambda path: ("dir", "207", ""))
    monkeypatch.setattr(nc, "curl_with_code", lambda *a, **kw: ("", "204", ""))

    assert nc.cmd_rm("/Obsidian", recursive=True, force=False, json_mode=False) == nc.EXIT_OK
    assert nc.cmd_rm("/Critical", recursive=True, force=False, json_mode=False) == nc.EXIT_USAGE
    assert "protected path" in capsys.readouterr().err


def test_curl_with_code_parses_body_without_trailing_newline(monkeypatch):
    nc = load_nc(monkeypatch)

    def fake_run(cmd, input=None, capture_output=True, text=True, timeout=None):
        assert any("NC_HTTP_CODE:%{http_code}" in part for part in cmd)
        return CurlResult(returncode=0, stdout="<xml>body</xml>\nNC_HTTP_CODE:207", stderr="")

    monkeypatch.setattr(nc.subprocess, "run", fake_run)

    body, code, stderr = nc.curl_with_code("-X", "PROPFIND", "https://cloud.example.test")

    assert body == "<xml>body</xml>"
    assert code == "207"
    assert stderr == ""


def test_search_escapes_xml_literal(monkeypatch):
    nc = load_nc(monkeypatch)
    captured = {}

    def fake_curl(*args, **kwargs):
        captured["args"] = args
        return CurlResult(returncode=0, stdout="<d:multistatus xmlns:d=\"DAV:\"></d:multistatus>\nNC_HTTP_CODE:207", stderr="")

    monkeypatch.setattr(nc, "curl", fake_curl)

    rc = nc.cmd_search("a&b<c>", "/", json_mode=True)

    assert rc == nc.EXIT_OK
    body = captured["args"][captured["args"].index("-d") + 1]
    assert "a&amp;b&lt;c&gt;" in body
    assert "a&b<c>" not in body


def test_share_password_flag_requires_value(monkeypatch, capsys):
    nc = load_nc(monkeypatch)
    monkeypatch.setattr(sys, "argv", ["nc-cli", "share", "/file", "--pw"])

    rc = nc.main()

    assert rc == nc.EXIT_USAGE
    assert "--pw requires a password" in capsys.readouterr().err


def test_version_flag_prints_version(monkeypatch, capsys):
    nc = load_nc(monkeypatch)
    monkeypatch.setattr(sys, "argv", ["nc-cli", "--version"])

    rc = nc.main()

    assert rc == nc.EXIT_OK
    out = capsys.readouterr().out.strip()
    assert out.startswith("nc-cli ")
    assert nc.VERSION in out
