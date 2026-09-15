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


# ── PROPFIND self-entry filtering ────────────────────────────────────────────
#
# The server echoes the requested collection as the first <d:response>, so ls has to
# drop it. The filter compares the href against the requested path; when those two are
# in different encodings it silently fails to match, and the directory is listed as its
# own child.

def _response(href, is_dir=True, size=0):
    tipo = "<d:collection/>" if is_dir else ""
    return (
        "<d:response>"
        f"<d:href>{href}</d:href>"
        "<d:propstat><d:prop>"
        f"<d:resourcetype>{tipo}</d:resourcetype>"
        f"<d:getcontentlength>{size}</d:getcontentlength>"
        "</d:prop></d:propstat>"
        "</d:response>"
    )


def multistatus(*entradas):
    """Build a PROPFIND multistatus body.

    Each entry is either an href string (a collection) or a tuple
    ``(href, is_dir, size)`` when the response must describe a file.
    """
    blocos = [_response(*e) if isinstance(e, tuple) else _response(e) for e in entradas]
    return f'<d:multistatus xmlns:d="DAV:">{"".join(blocos)}</d:multistatus>'


def ls_json(monkeypatch, capsys, nc, path, body):
    """Run `ls --json` against a canned PROPFIND body, return the parsed payload."""
    def fake_curl_with_code(*args, **kwargs):
        return body, "207", ""
    monkeypatch.setattr(nc, "curl_with_code", fake_curl_with_code)

    rc = nc.cmd_ls(path, json_mode=True)
    assert rc == nc.EXIT_OK
    return json.loads(capsys.readouterr().out)


def test_ls_drops_self_entry_when_path_needs_encoding(monkeypatch, capsys):
    """Empty directory whose path contains spaces must list zero entries.

    Before the fix the self-filter compared an unquoted href against a quoted
    self_href, never matched, and an EMPTY directory reported itself as one child —
    enough to send a recursive walker into an infinite loop.
    """
    nc = load_nc(monkeypatch)
    path = "/10 - CENTRO DE CULTUR/0CROQUIS"
    payload = ls_json(monkeypatch, capsys, nc, path, multistatus(nc.dav_href(path) + "/"))

    assert payload["data"]["items"] == []


def test_ls_keeps_real_children_alongside_self_entry(monkeypatch, capsys):
    nc = load_nc(monkeypatch)
    path = "/10 - CENTRO DE CULTUR"
    body = multistatus(
        nc.dav_href(path) + "/",
        nc.dav_href(path + "/0CROQUIS") + "/",
    )
    payload = ls_json(monkeypatch, capsys, nc, path, body)

    assert [item["name"] for item in payload["data"]["items"]] == ["0CROQUIS"]


def test_ls_keeps_child_that_shares_the_parent_name(monkeypatch, capsys):
    """The path-based filter exists for exactly this case — a same-named child.

    It must survive the filter that drops the parent's own entry.
    """
    nc = load_nc(monkeypatch)
    path = "/Obra Nova"
    body = multistatus(
        nc.dav_href(path) + "/",
        nc.dav_href(f"{path}/Obra Nova") + "/",
    )
    payload = ls_json(monkeypatch, capsys, nc, path, body)

    assert [item["name"] for item in payload["data"]["items"]] == ["Obra Nova"]
    assert payload["data"]["items"][0]["path"] == "/Obra Nova/Obra Nova"


def test_ls_self_filter_survives_lowercase_hex_encoding(monkeypatch, capsys):
    """Nextcloud encodes with lowercase hex (%c3%94), Python's quote() uses uppercase.

    Comparing encoded strings cannot work; decoding both sides makes the case
    difference irrelevant. This is why the comparison must not be done pre-decode.
    """
    nc = load_nc(monkeypatch)
    path = "/3MAQUETE ELETRÔNICA"
    server_href = nc.dav_href(path).replace("%C3%94", "%c3%94") + "/"
    payload = ls_json(monkeypatch, capsys, nc, path, multistatus(server_href))

    assert payload["data"]["items"] == []


def test_ls_self_filter_unchanged_for_plain_path(monkeypatch, capsys):
    """Control: paths needing no encoding behaved correctly before and must still."""
    nc = load_nc(monkeypatch)
    path = "/HERMES-DROP"
    body = multistatus(
        nc.dav_href(path) + "/",
        nc.dav_href(path + "/_teste-vazio") + "/",
    )
    payload = ls_json(monkeypatch, capsys, nc, path, body)

    assert [item["name"] for item in payload["data"]["items"]] == ["_teste-vazio"]


def test_decoded_dav_path_normalises_hex_case(monkeypatch):
    nc = load_nc(monkeypatch)

    assert nc.decoded_dav_path("/remote.php/dav/files/hermes-agent/%c3%94") == \
        nc.decoded_dav_path("/remote.php/dav/files/hermes-agent/%C3%94")


def test_ls_on_a_file_returns_that_file(monkeypatch, capsys):
    """`ls <arquivo>` must show the file, whether or not the path needs encoding.

    The self-filter exists to drop a directory that echoes itself. A file does not
    echo a second copy — its single response IS the item asked for — so filtering it
    too made `ls <arquivo>` print nothing, and only for paths that needed encoding,
    since the filter never matched otherwise.
    """
    nc = load_nc(monkeypatch)

    for path in ("/HERMES-DROP/quickstart.md",
                 "/10 - CENTRO DE CULTUR/5APRES/000_APRES00_0000.pptx"):
        payload = ls_json(monkeypatch, capsys, nc, path,
                          multistatus((nc.dav_href(path), False, 45)))
        itens = payload["data"]["items"]
        assert [i["type"] for i in itens] == ["file"], path
        assert itens[0]["name"] == path.rsplit("/", 1)[-1], path


def test_ls_still_hides_a_directory_that_echoes_itself(monkeypatch, capsys):
    """The guard must not weaken the original fix: a self-echoing directory goes."""
    nc = load_nc(monkeypatch)
    path = "/10 - CENTRO DE CULTUR/0CROQUIS"
    payload = ls_json(monkeypatch, capsys, nc, path, multistatus(nc.dav_href(path) + "/"))

    assert payload["data"]["items"] == []
