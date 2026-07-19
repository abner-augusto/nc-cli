# nc-cli

A small, dependency-free Nextcloud WebDAV CLI for automation and agent workflows.

It is intentionally boring: one Python script, curl under the hood, semantic exit codes, JSON output, chunked uploads, and atomic verified downloads.

## Why this exists

Most Nextcloud automation snippets are fragile curl one-liners. They often save XML error pages as files, treat 404s as success, leak credentials in process argv, or break on large uploads.

This CLI is designed to be safe enough for scripts and autonomous agents:

- semantic exit codes for reliable branching
- `--json` output for every command
- credentials passed to curl through stdin config, not `-u user:token` argv
- chunked upload support for large files
- atomic `.part` downloads with size validation
- safer delete semantics for directories and protected roots
- no Python package dependencies

## Install

Clone and install:

```bash
git clone https://github.com/abner-augusto/nc-cli.git
cd nc-cli
./install.sh
```

Default command name is `nc-cli`, because `nc` usually means netcat on Unix systems.

If you intentionally want the short name:

```bash
./install.sh --as-nc
```

Or run directly:

```bash
./bin/nc-cli --version
```

## Configuration

Set these environment variables:

```bash
export NEXTCLOUD_URL="https://cloud.example.com"
export NEXTCLOUD_USER="your-nextcloud-username"
export NEXTCLOUD_APP_PASSWORD="your-nextcloud-app-password"
```

The script also reads `~/.hermes/.env` for Hermes Agent deployments. For general use, exporting variables in your shell, systemd unit, or secret manager is cleaner.

Create a Nextcloud app password under:

```text
Settings → Security → App passwords
```

## Quick start

```bash
nc-cli ls /
nc-cli mkdir /Backups
nc-cli upload ./backup.zip /Backups/backup.zip
nc-cli download /Backups/backup.zip ./backup.zip
nc-cli info /Backups/backup.zip --json
nc-cli share /Backups/backup.zip
```

Large uploads are chunked automatically when they exceed the chunk size, default 100 MB:

```bash
nc-cli upload ./huge.tar.zst /Backups/huge.tar.zst
nc-cli upload ./huge.tar.zst /Backups/huge.tar.zst --chunk-size 50
nc-cli upload ./huge.tar.zst /Backups/huge.tar.zst --no-chunk
```

## Commands

```text
ls       [path] [--json] [--recursive]
upload   <local> <remote> [--json] [--no-chunk] [--chunk-size MB] [--no-clobber]
download <remote> <local> [--json]
mkdir    <path> [--json]
mv       <src> <dst> [--json] [--overwrite]
cp       <src> <dst> [--json] [--overwrite]
rm       <path> [--json] [--recursive] [--force]
search   <query> [path] [--json]
info     <path> [--json]
quota    [path] [--json]
share    <path> [--json] [--pw PASS|--password-env VAR|--password-stdin]
version
help
```

## JSON output

All commands support the same wrapper:

```json
{
  "ok": true,
  "http_code": "207",
  "data": {},
  "error": null
}
```

Example:

```bash
nc-cli upload ./file.txt /Uploads/file.txt --json
```

```json
{
  "ok": true,
  "http_code": "201",
  "data": {
    "operation": "upload",
    "path": "/Uploads/file.txt",
    "bytes": 123,
    "chunked": false
  },
  "error": null
}
```

Full schema: [`docs/json-output.md`](docs/json-output.md).

## Exit codes

- `0`: success
- `2`: not found / HTTP 404
- `3`: auth failure / HTTP 401 or 403
- `4`: conflict / HTTP 409 or 412
- `5`: server error / HTTP 5xx or unsupported server method
- `6`: network error, curl failure, timeout, or incomplete download
- `7`: usage error or unsafe operation refused
- `8`: size limit / HTTP 413
- `9`: checksum mismatch / HTTP 400 on checksum-checked upload

## Safer delete behavior

Directory deletion is recursive in WebDAV, so this CLI refuses dangerous deletes by default:

```bash
nc-cli rm /                         # refused
nc-cli rm /SomeDir                  # refused: directory requires --recursive
nc-cli rm /SomeDir --recursive      # allowed
nc-cli rm /Backups --recursive --force
```

Protected top-level paths require `--force` in addition to `--recursive`:

- `/HERMES-DROP`
- `/Obsidian`
- `/_INTEGRARTE.ARQ`

Those names come from the original Hermes/Nextcloud deployment. Override them without patching code:

```bash
export NC_PROTECTED_DELETE_PATHS="/Backups,/Shared Team Folder"
```

Set it to an empty string to disable protected-path checks except for `/`, which is always refused.

## Tests

```bash
python -m py_compile bin/nc-cli
python -m pip install pytest
pytest -q
```

The unit suite does not require a live Nextcloud server. It tests command behavior with monkeypatched curl calls.

## Hermes Agent skill

The original project came from a Hermes Agent skill. If you use Hermes, keep a thin skill wrapper that points to this repository and documents your local deployment conventions.

Do not commit real Nextcloud URLs, users, or app passwords. Use `examples/env.example` as the template.

## License

MIT.
