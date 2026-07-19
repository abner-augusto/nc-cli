# nc-cli — JSON Output Reference (v3.1.0)

All commands support `--json` and emit the same wrapper:

```json
{
  "ok": true,
  "http_code": "207",
  "data": {},
  "error": null
}
```

- `ok`: boolean, always present
- `http_code`: HTTP status string; `"000"` means network/curl failure
- `data`: command-specific payload, or null on failure
- `error`: null on success, human-readable string on failure

Agent parsing rule: check `.ok` and the process exit code. Do not scrape human stderr.

## Commands

### `ls [path] --json`

```json
{
  "ok": true,
  "http_code": "207",
  "data": {
    "path": "/HERMES-DROP",
    "items": [
      {
        "name": "report.pdf",
        "type": "file",
        "path": "/HERMES-DROP/report.pdf",
        "dav_href": "/remote.php/dav/files/hermes-agent/HERMES-DROP/report.pdf",
        "size": 15558560,
        "modified": "Mon, 25 May 2026 15:58:08 GMT",
        "etag": "f504439b53"
      }
    ]
  },
  "error": null
}
```

`--recursive` keeps the same schema and includes descendants. The listed directory itself is excluded.

### `info <path> --json`

Returns rich WebDAV metadata:

```json
{
  "ok": true,
  "http_code": "207",
  "data": {
    "path": "/HERMES-DROP/file.pdf",
    "type": "file",
    "size": 15558560,
    "modified": "Thu, 04 Jun 2026 16:15:25 GMT",
    "etag": "6a21a4969df17",
    "fileid": 1129061,
    "permissions": "SRGDNVW",
    "mount_type": "shared",
    "encrypted": false,
    "content_type": "application/pdf"
  },
  "error": null
}
```

Permission flags: `G` read, `W` write, `D` delete, `N` rename, `V` move, `C` create files, `K` create folders, `S/R/M` sharing/mount flags.

### `upload <local> <remote> --json`

```json
{
  "ok": true,
  "http_code": "201",
  "data": {
    "operation": "upload",
    "path": "/HERMES-DROP/file.bin",
    "bytes": 2109497,
    "chunked": true,
    "chunks": 3
  },
  "error": null
}
```

Single PUT uploads omit `chunks` and set `chunked: false`.

### `download <remote> <local> --json`

```json
{
  "ok": true,
  "http_code": "200",
  "data": {
    "operation": "download",
    "remote_path": "/HERMES-DROP/file.bin",
    "local_path": "/home/hermes-vm/file.bin",
    "bytes": 2109497
  },
  "error": null
}
```

Safety behavior: downloads write to `<local>.part`, validate HTTP status and content length, then atomically rename. Curl failures and size mismatches delete the partial file and return exit 6.

### `mkdir <path> --json`

```json
{"ok": true, "http_code": "201", "data": {"operation": "mkdir", "path": "/dir"}, "error": null}
```

Existing directory is success with `already_exists: true` and HTTP `405`.

### `mv <src> <dst> --json` / `cp <src> <dst> --json`

```json
{"ok": true, "http_code": "201", "data": {"operation": "mv", "src": "/a", "dst": "/b", "overwrite": false}, "error": null}
```

Use `--overwrite` to replace an existing destination. Without it, HTTP 409/412 returns exit 4.

### `rm <path> --json`

```json
{"ok": true, "http_code": "204", "data": {"operation": "rm", "path": "/file", "type": "file"}, "error": null}
```

Safety rules:

- `nc-cli rm /` is refused and cannot be overridden.
- Directory deletion requires `--recursive`.
- Default protected top-level paths (`/HERMES-DROP`, `/Obsidian`, `/_INTEGRARTE.ARQ`) require `--force` in addition to `--recursive`.
- Override protected paths with comma-separated `NC_PROTECTED_DELETE_PATHS`, e.g. `NC_PROTECTED_DELETE_PATHS="/Backups,/Team Share"`. Empty string disables protected-path checks except for `/`.

### `share <path> --json`

```json
{
  "ok": true,
  "http_code": "200",
  "data": {
    "operation": "share",
    "path": "/HERMES-DROP/report.pdf",
    "url": "https://nextcloud.example/s/abc123",
    "password_protected": false
  },
  "error": null
}
```

Password options:

- `--pw PASS` — supported but visible in argv; avoid for sensitive values.
- `--password-env ENV_VAR` — preferred for automation.
- `--password-stdin` — preferred for one-off secret input.

`--pw` without a value exits 7 and does not create a public share.

### `search <query> [path] --json`

Same `items` schema as `ls`. XML literals are escaped before sending the WebDAV SEARCH body.

If SEARCH is unsupported, returns exit 5 with fallback instructions.

### `quota [path] --json`

```json
{"ok": true, "http_code": "207", "data": {"path": "/", "used": 1014304, "available": -3}, "error": null}
```

Sentinels: `-1` uncomputed, `-2` unknown, `-3` unlimited.

## Exit Code Quick Reference

- `0`: success
- `2`: not found / HTTP 404
- `3`: auth failure / HTTP 401 or 403
- `4`: conflict / HTTP 409 or 412
- `5`: server error / HTTP 5xx or unsupported server method
- `6`: network, curl failure, timeout, or incomplete download
- `7`: usage error / unsafe operation refused
- `8`: size limit / HTTP 413
- `9`: checksum mismatch / HTTP 400 on checksum-checked upload
