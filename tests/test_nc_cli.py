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


# ── Names with edge whitespace and 404 suggestions ───────────────────────────

SPACED = " Aracati - Ceará.zip"


def fake_server(monkeypatch, nc, directory, names):
    """Serve one directory listing; every other request answers 404."""
    listing = multistatus(
        nc.dav_href(directory) + "/",
        *[(nc.dav_href(f"{directory}/{n}"), False, 1) for n in names],
    )
    listing_url = nc.build_url(directory).rstrip("/") + "/"

    def fake_curl_with_code(*args, **kwargs):
        if "PROPFIND" in args and args[-1] == listing_url:
            return listing, "207", ""
        return "", "404", ""

    monkeypatch.setattr(nc, "curl_with_code", fake_curl_with_code)


def test_ls_human_quotes_names_with_edge_whitespace_only(monkeypatch, capsys):
    nc = load_nc(monkeypatch)
    fake_server(monkeypatch, nc, "/D", [SPACED, "Aracati.zip"])

    assert nc.cmd_ls("/D") == nc.EXIT_OK

    lines = capsys.readouterr().out.splitlines()
    assert f'📄 "{SPACED}"' in lines
    assert "📄 Aracati.zip" in lines


def test_ls_human_quotes_names_with_control_characters(monkeypatch, capsys):
    nc = load_nc(monkeypatch)
    fake_server(monkeypatch, nc, "/D", ["a\tb.txt"])

    nc.cmd_ls("/D")

    assert '📄 "a\\tb.txt"' in capsys.readouterr().out.splitlines()


def test_ls_json_keeps_exact_names(monkeypatch, capsys):
    nc = load_nc(monkeypatch)
    fake_server(monkeypatch, nc, "/D", [SPACED, "Aracati.zip"])

    nc.cmd_ls("/D", json_mode=True)

    items = json.loads(capsys.readouterr().out)["data"]["items"]
    assert [i["name"] for i in items] == [SPACED, "Aracati.zip"]


def test_download_404_suggests_name_with_edge_space(monkeypatch, tmp_path, capsys):
    nc = load_nc(monkeypatch)
    fake_server(monkeypatch, nc, "/D", [SPACED])

    rc = nc.cmd_download("/D/Aracati - Ceará.zip", str(tmp_path / "out"))

    assert rc == 2
    err = capsys.readouterr().err
    assert "File not found: /D/Aracati - Ceará.zip (HTTP 404)" in err
    assert f'"/D/{SPACED}"' in err


def test_download_404_json_carries_suggestions(monkeypatch, tmp_path, capsys):
    nc = load_nc(monkeypatch)
    fake_server(monkeypatch, nc, "/D", [SPACED])

    rc = nc.cmd_download("/D/Aracati - Ceará.zip", str(tmp_path / "out"), json_mode=True)

    assert rc == 2
    payload = json.loads(capsys.readouterr().out)
    assert payload["ok"] is False
    assert payload["suggestions"] == [f"/D/{SPACED}"]


def test_suggestion_matches_nfd_request_against_nfc_server_name(monkeypatch, tmp_path, capsys):
    import unicodedata
    nc = load_nc(monkeypatch)
    fake_server(monkeypatch, nc, "/D", [SPACED])
    requested = unicodedata.normalize("NFD", "/D/Aracati - Ceará.zip")

    nc.cmd_download(requested, str(tmp_path / "out"), json_mode=True)

    assert json.loads(capsys.readouterr().out)["suggestions"] == [f"/D/{SPACED}"]


def test_suggestion_ignores_case(monkeypatch, tmp_path, capsys):
    nc = load_nc(monkeypatch)
    fake_server(monkeypatch, nc, "/D", ["ARACATI.ZIP"])

    nc.cmd_download("/D/aracati.zip", str(tmp_path / "out"), json_mode=True)

    assert json.loads(capsys.readouterr().out)["suggestions"] == ["/D/ARACATI.ZIP"]


def test_404_without_candidate_keeps_current_output(monkeypatch, tmp_path, capsys):
    nc = load_nc(monkeypatch)
    fake_server(monkeypatch, nc, "/D", ["other.zip"])

    rc = nc.cmd_download("/D/Aracati.zip", str(tmp_path / "out"))
    human = capsys.readouterr()
    rc_json = nc.cmd_download("/D/Aracati.zip", str(tmp_path / "out"), json_mode=True)
    payload = json.loads(capsys.readouterr().out)

    assert rc == rc_json == 2
    assert human.err == "ERROR: File not found: /D/Aracati.zip (HTTP 404)\n"
    assert payload == {"ok": False, "http_code": "404", "data": None,
                       "error": "File not found: /D/Aracati.zip (HTTP 404)"}


def test_404_with_missing_parent_keeps_current_output(monkeypatch, capsys):
    nc = load_nc(monkeypatch)
    monkeypatch.setattr(nc, "curl_with_code", lambda *a, **kw: ("", "404", ""))

    rc = nc.cmd_info("/nowhere/x.zip")

    assert rc == 2
    assert capsys.readouterr().err == "ERROR: Not found: /nowhere/x.zip (HTTP 404)\n"


@pytest.mark.parametrize("call", [
    lambda nc, p: nc.cmd_info(p),
    lambda nc, p: nc.cmd_rm(p),
    lambda nc, p: nc.cmd_mv(p, "/D/new.zip"),
    lambda nc, p: nc.cmd_cp(p, "/D/new.zip"),
    lambda nc, p: nc.cmd_share(p),
])
def test_other_path_commands_suggest_on_404(monkeypatch, capsys, call):
    nc = load_nc(monkeypatch)
    fake_server(monkeypatch, nc, "/D", [SPACED])

    rc = call(nc, "/D/Aracati - Ceará.zip")

    assert rc == 2
    assert f'"/D/{SPACED}"' in capsys.readouterr().err


def test_ls_404_suggests_sibling_directory(monkeypatch, capsys):
    nc = load_nc(monkeypatch)
    fake_server(monkeypatch, nc, "/", [" Pasta"])

    rc = nc.cmd_ls("/Pasta", json_mode=True)

    assert rc == 2
    assert json.loads(capsys.readouterr().out)["suggestions"] == ["/ Pasta"]


class FakeDav:
    """In-memory single-file WebDAV server behind the curl/_curl_put seams."""

    def __init__(self, nc, monkeypatch, content=None, conflicts=(), lie_about_size=False,
                 put_response=None, write_after_put=None, hide_head_length=False, put_parent_missing=False):
        self.content = content
        self.version = 1
        self.conflicts = list(conflicts)
        self.lie_about_size = lie_about_size
        self.put_response = put_response
        self.write_after_put = write_after_put
        self.hide_head_length = hide_head_length
        self.put_parent_missing = put_parent_missing
        self.put_headers = []
        self.puts_accepted = 0
        monkeypatch.setattr(nc, "curl", self.curl)
        monkeypatch.setattr(nc, "curl_with_code", self.head)
        monkeypatch.setattr(nc, "_curl_put", self.put)

    def curl(self, *args, **kwargs):
        if self.content is None:
            return CurlResult(0, "\n" + self.marker + "404")
        Path(args[args.index("-o") + 1]).write_bytes(self.content)
        Path(args[args.index("-D") + 1]).write_text(f'HTTP/1.1 200 OK\r\nETag: "v{self.version}"\r\n\r\n')
        return CurlResult(0, "\n" + self.marker + "200")

    def head(self, *args, **kwargs):
        if self.content is None:
            return "", "404", ""
        size = len(self.content) + (1 if self.lie_about_size else 0)
        length = "" if self.hide_head_length else f"Content-Length: {size}\n"
        return f'{length}ETag: "v{self.version}"\n', "200", ""

    def put(self, file_path, url, extra_headers, max_time, show_progress, retries=None, header_file=None):
        self.put_headers.append(extra_headers[0])
        self.put_retries = retries
        if self.put_parent_missing:
            return "409", ""
        if self.conflicts:
            self.content = self.conflicts.pop(0)
            self.version += 1
            return "412", ""
        expected = extra_headers[0]
        if expected == "If-None-Match: *":
            assert self.content is None
        else:
            assert expected == f'If-Match: "v{self.version}"'
        self.content = Path(file_path).read_bytes()
        self.version += 1
        self.puts_accepted += 1
        if header_file:
            Path(header_file).write_text(f'HTTP/1.1 204 No Content\r\nETag: "v{self.version}"\r\n\r\n')
        if self.write_after_put:
            self.content += self.write_after_put
            self.version += 1
        return self.put_response or "204", ""


def append_setup(monkeypatch, tmp_path, **kwargs):
    nc = load_nc(monkeypatch)
    FakeDav.marker = nc.HTTP_CODE_MARKER
    dav = FakeDav(nc, monkeypatch, **kwargs)
    local = tmp_path / "new.txt"
    local.write_bytes(b"new\n")
    return nc, dav, str(local)


def test_append_to_file_ending_in_newline_adds_no_extra_line(monkeypatch, tmp_path):
    nc, dav, local = append_setup(monkeypatch, tmp_path, content=b"old\n")
    assert nc.cmd_append("/log.md", local) == nc.EXIT_OK
    assert dav.content == b"old\nnew\n"


def test_append_to_file_without_final_newline_inserts_exactly_one(monkeypatch, tmp_path):
    nc, dav, local = append_setup(monkeypatch, tmp_path, content=b"old")
    assert nc.cmd_append("/log.md", local) == nc.EXIT_OK
    assert dav.content == b"old\nnew\n"


def test_append_preserves_crlf_bytes(monkeypatch, tmp_path):
    nc, dav, local = append_setup(monkeypatch, tmp_path, content=b"a\r\n")
    assert nc.cmd_append("/log.md", local) == nc.EXIT_OK
    assert dav.content == b"a\r\nnew\n"


def test_append_retries_after_412_and_keeps_concurrent_write(monkeypatch, tmp_path, capsys):
    nc, dav, local = append_setup(monkeypatch, tmp_path, content=b"old\n", conflicts=[b"old\nother\n"])
    assert nc.cmd_append("/log.md", local, json_mode=True) == nc.EXIT_OK
    data = json.loads(capsys.readouterr().out)["data"]
    assert data == {"path": "/log.md", "bytes_appended": 4, "size": 14, "attempts": 2}
    assert dav.content == b"old\nother\nnew\n"


def test_append_gives_up_with_conflict_after_three_412s(monkeypatch, tmp_path):
    nc, dav, local = append_setup(
        monkeypatch, tmp_path, content=b"old\n", conflicts=[b"a\n", b"b\n", b"c\n"]
    )
    assert nc.cmd_append("/log.md", local) == nc.EXIT_CONFLICT
    assert len(dav.put_headers) == 3
    assert dav.puts_accepted == 0
    assert dav.content == b"c\n"


def test_append_missing_remote_without_create_exits_not_found(monkeypatch, tmp_path):
    nc, dav, local = append_setup(monkeypatch, tmp_path, content=None)
    monkeypatch.setattr(nc, "suggest_paths", lambda path: [])
    assert nc.cmd_append("/log.md", local) == nc.EXIT_NOT_FOUND
    assert dav.put_headers == []


def test_append_create_uses_if_none_match(monkeypatch, tmp_path):
    nc, dav, local = append_setup(monkeypatch, tmp_path, content=None)
    assert nc.cmd_append("/log.md", local, create=True) == nc.EXIT_OK
    assert dav.put_headers == ["If-None-Match: *"]
    assert dav.content == b"new\n"


def test_append_size_mismatch_on_read_back_exits_checksum(monkeypatch, tmp_path):
    nc, dav, local = append_setup(monkeypatch, tmp_path, content=b"old\n", lie_about_size=True)
    assert nc.cmd_append("/log.md", local) == nc.EXIT_CHECKSUM


def test_append_dash_reads_stdin(monkeypatch, tmp_path):
    import io

    nc, dav, _ = append_setup(monkeypatch, tmp_path, content=b"old\n")

    class Stdin:
        buffer = io.BytesIO(b"from stdin\n")

    monkeypatch.setattr(sys, "stdin", Stdin)
    assert nc.cmd_append("/log.md", "-") == nc.EXIT_OK
    assert dav.content == b"old\nfrom stdin\n"


def test_main_routes_append_with_create_flag(monkeypatch):
    nc = load_nc(monkeypatch)
    seen = {}
    monkeypatch.setattr(sys, "argv", ["nc-cli", "append", "/r.md", "-", "--create", "--json"])
    monkeypatch.setattr(nc, "cmd_append", lambda *a, **kw: seen.update(args=a, kw=kw) or nc.EXIT_OK)
    assert nc.main() == nc.EXIT_OK
    assert seen["args"] == ("/r.md", "-")
    assert seen["kw"] == {"create": True, "json_mode": True}


def test_help_lists_append(monkeypatch, capsys):
    nc = load_nc(monkeypatch)
    nc.cmd_help()
    assert "append" in capsys.readouterr().out


def test_append_does_not_retry_put_and_never_duplicates_on_lost_response(monkeypatch, tmp_path, capsys):
    nc, dav, local = append_setup(monkeypatch, tmp_path, content=b"old\n", put_response="502")
    assert nc.cmd_append("/log.md", local) == nc.EXIT_SERVER
    assert dav.content == b"old\nnew\n"
    assert dav.put_retries == 0
    assert len(dav.put_headers) == 1
    assert "uncertain" in capsys.readouterr().err


def test_append_put_network_failure_exits_network_with_uncertain_state(monkeypatch, tmp_path, capsys):
    nc, dav, local = append_setup(monkeypatch, tmp_path, content=b"old\n", put_response="000")
    assert nc.cmd_append("/log.md", local) == nc.EXIT_NETWORK
    assert "uncertain" in capsys.readouterr().err


def test_append_succeeds_when_another_agent_appends_after_our_put(monkeypatch, tmp_path, capsys):
    nc, dav, local = append_setup(monkeypatch, tmp_path, content=b"old\n", write_after_put=b"theirs\n")
    assert nc.cmd_append("/log.md", local, json_mode=True) == nc.EXIT_OK
    data = json.loads(capsys.readouterr().out)["data"]
    assert data["concurrent_after"] is True
    assert data["size"] == len(b"old\nnew\ntheirs\n")


def test_append_size_mismatch_message_when_content_length_missing(monkeypatch, tmp_path, capsys):
    nc, dav, local = append_setup(monkeypatch, tmp_path, content=b"old\n", hide_head_length=True)
    assert nc.cmd_append("/log.md", local) == nc.EXIT_CHECKSUM
    err = capsys.readouterr().err
    assert "None" not in err and "unknown" in err


def test_append_create_race_retries_with_if_match_and_keeps_both_writes(monkeypatch, tmp_path, capsys):
    nc, dav, local = append_setup(monkeypatch, tmp_path, content=None)
    original_put = dav.put

    def racing_put(file_path, url, extra_headers, *a, **kw):
        if dav.content is None:
            dav.content = b"theirs\n"
            dav.version += 1
            dav.put_headers.append(extra_headers[0])
            return "412", ""
        return original_put(file_path, url, extra_headers, *a, **kw)

    monkeypatch.setattr(nc, "_curl_put", racing_put)
    assert nc.cmd_append("/log.md", local, create=True, json_mode=True) == nc.EXIT_OK
    assert json.loads(capsys.readouterr().out)["data"]["attempts"] == 2
    assert dav.put_headers[0] == "If-None-Match: *"
    assert dav.put_headers[1].startswith("If-Match:")
    assert dav.content == b"theirs\nnew\n"


def test_append_empty_input_is_noop(monkeypatch, tmp_path, capsys):
    nc, dav, _ = append_setup(monkeypatch, tmp_path, content=b"old\n")
    empty = tmp_path / "empty.txt"
    empty.write_bytes(b"")
    assert nc.cmd_append("/log.md", str(empty), json_mode=True) == nc.EXIT_OK
    assert json.loads(capsys.readouterr().out)["data"]["bytes_appended"] == 0
    assert dav.put_headers == []


def test_append_get_timeout_exits_network(monkeypatch, tmp_path):
    import subprocess
    nc, dav, local = append_setup(monkeypatch, tmp_path, content=b"old\n")

    def timing_out(*a, **kw):
        raise subprocess.TimeoutExpired("curl", 1)

    monkeypatch.setattr(nc, "curl", timing_out)
    assert nc.cmd_append("/log.md", local) == nc.EXIT_NETWORK


def test_append_create_with_missing_parent_exits_not_found(monkeypatch, tmp_path, capsys):
    nc, dav, local = append_setup(monkeypatch, tmp_path, content=None, put_parent_missing=True)
    monkeypatch.setattr(nc, "suggest_paths", lambda path: [])
    assert nc.cmd_append("/nope/log.md", local, create=True) == nc.EXIT_NOT_FOUND
    assert "Parent folder" in capsys.readouterr().err


def test_suggestion_parent_in_nfd_does_not_list_parent_as_child(monkeypatch, tmp_path, capsys):
    import unicodedata
    nc = load_nc(monkeypatch)
    parent_nfc = "/Relatório"
    parent_nfd = unicodedata.normalize("NFD", parent_nfc)
    server_parent_href = nc.dav_href(parent_nfc).replace("%C3%B3", "%c3%b3") + "/"
    listing = multistatus(server_parent_href, (nc.dav_href(parent_nfc + "/a.zip"), False, 1))
    monkeypatch.setattr(nc, "curl_with_code", lambda *a, **kw: (listing, "207", ""))

    assert nc.suggest_paths(parent_nfd + "/A.ZIP") == [parent_nfc + "/a.zip"]
    assert nc.suggest_paths(parent_nfd + "/Relatório") == []


def test_suggestion_on_stderr_is_escaped(monkeypatch, tmp_path, capsys):
    nc = load_nc(monkeypatch)
    fake_server(monkeypatch, nc, "/D", ['A "x" $HOME `id`.zip'])

    nc.cmd_download("/D/a \"x\" $home `id`.zip", str(tmp_path / "out"))

    assert '"/D/A \\"x\\" $HOME `id`.zip"' in capsys.readouterr().err


def test_suggestion_propfind_is_short_lived_and_minimal(monkeypatch):
    nc = load_nc(monkeypatch)
    seen = {}

    def fake(*args, **kwargs):
        seen["args"], seen["kwargs"] = args, kwargs
        return "", "207", ""

    monkeypatch.setattr(nc, "curl_with_code", fake)
    nc.suggest_paths("/D/x")
    assert seen["kwargs"] == {"max_time": 15, "retries": 0}
    assert "<d:resourcetype/>" in seen["args"][seen["args"].index("-d") + 1]


def test_display_name_quotes_format_characters(monkeypatch):
    nc = load_nc(monkeypatch)
    assert nc.display_name("a\u202eb.txt") == json.dumps("a\u202eb.txt", ensure_ascii=False)
