# `nc-cli` v3.1 Changelog

Patch date: 2026-06-09.

## Fixes and Features

### Atomic, verified downloads

`nc-cli download` now writes to `<target>.part`, validates curl success and `Content-Length`, then atomically renames with `os.replace()`.

- curl/network failure → partial file removed, exit 6
- size mismatch → partial file removed, exit 6
- 404 before download → no target file created, exit 2

This fixes the old false-success case where a timeout could leave a short local file and still return exit 0.

### JSON for all commands

Mutating commands now accept `--json` and emit the standard wrapper:

- `upload`
- `download`
- `mkdir`
- `mv`
- `cp`
- `rm`
- `share`

Existing query commands (`ls`, `info`, `search`, `quota`) keep the same wrapper.

### Safer delete semantics

`rm` now performs a WebDAV PROPFIND preflight before DELETE.

Rules:

- refuses `/` unconditionally
- deleting directories requires `--recursive`
- default protected top-level paths require `--force` too:
  - `/HERMES-DROP`
  - `/Obsidian`
  - `/_INTEGRARTE.ARQ`
- override protected paths with comma-separated `NC_PROTECTED_DELETE_PATHS`, e.g. `NC_PROTECTED_DELETE_PATHS="/Backups,/Team Share"`

### Robust curl HTTP-code parsing

Curl now appends a sentinel marker:

```text
\nNC_HTTP_CODE:%{http_code}
```

The parser splits on that marker instead of guessing from the final newline. This avoids body/code ambiguity when a WebDAV body does not end with a newline.

### Escaped SEARCH literals

`nc-cli search` escapes XML literals with `html.escape(query, quote=True)` before embedding the query inside the WebDAV SEARCH request body.

### Safer share password handling

`nc-cli share` now refuses `--pw` without a value. It also supports:

```bash
nc-cli share /path --password-env NC_SHARE_PASSWORD
printf '%s' "$password" | nc-cli share /path --password-stdin
```

Use these instead of `--pw` for sensitive passwords because argv is visible to local process inspection.

### Version command

```bash
nc-cli --version
nc-cli version
```

prints the CLI version.

## Tests Added

`tests/test_nc_cli.py` covers:

- partial download timeout deletes partial and exits 6
- size mismatch deletes partial and exits 6
- `main()` forwards `--json` to all mutating commands
- `rm /` refuses before WebDAV
- directory delete requires `--recursive`
- protected top-level delete requires `--force`
- curl HTTP-code sentinel parsing
- XML escaping in `search`
- missing `--pw` value returns usage error
- `--version` output

Run:

```bash
cd ~/.hermes/skills/devops/nextcloud
uv run --with pytest pytest -q tests/test_nc_cli.py
python3 -m py_compile bin/nc-cli
```

Live WebDAV smoke tests were also run against `/HERMES-DROP/.nc-review-*`, including single upload/download, JSON output validation, safe directory delete refusal, forced recursive cleanup, and forced 1 MB chunked upload with SHA1 compare.
