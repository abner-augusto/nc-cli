# 02 — Comando `append` atômico para logs append-only

Status: done
Blocked by: 01 (mesmo arquivo; implementar depois do merge do 01)

## Contexto

Logs como `/0-VIABILIDADES BRASIL URBANO/_TRIAGEM/_log-triagem-hermes.md` são append-only e gravados por vários agentes (Hermes no WhatsApp, Claude Code, sessões locais). Hoje o agente baixa, acrescenta localmente e sobe com `--overwrite`: se outro agente gravar entre o download e o upload, a linha dele some sem erro.

## O que construir

`nc-cli append <remoto> <arquivo-local | ->`:

1. Faz GET do remoto e guarda o `ETag`.
2. Concatena: conteúdo remoto + (uma quebra de linha se o remoto não terminar em `\n` e não estiver vazio) + conteúdo novo.
3. Faz PUT com `If-Match: <ETag>`. Em 412, refaz os passos 1–3 até 3 tentativas; esgotadas, sai com código 4 (conflito) sem gravar.
4. Remoto inexistente: só cria com `--create`, usando `If-None-Match: *`; sem a flag, sai com código 2.
5. Depois do PUT, faz a leitura de volta (GET ou PROPFIND) e confirma que o tamanho remoto é igual a `len(remoto_antigo + separador + novo)`; divergência sai com código 9.
6. `-` lê o conteúdo novo do stdin. `--json` segue o formato de `docs/json-output.md` (`data`: `path`, `bytes_appended`, `size`, `attempts`).

## Acceptance criteria

- [ ] Append em arquivo que termina com `\n` concatena sem linha extra; em arquivo sem `\n` final insere exatamente um `\n`.
- [ ] Servidor fake que devolve 412 na primeira tentativa: o append refaz o GET, grava na segunda e reporta `attempts: 2`; o conteúdo final contém a escrita concorrente e a nova.
- [ ] 412 em 3 tentativas seguidas: exit 4 e nenhum PUT bem-sucedido.
- [ ] Remoto inexistente sem `--create`: exit 2; com `--create`: cria o arquivo com `If-None-Match: *`.
- [ ] Leitura de volta com tamanho divergente: exit 9.
- [ ] `-` lê do stdin.
- [ ] `nc-cli help` e `README.md` mostram o comando; `docs/json-output.md` documenta o `data`.
- [ ] Testes em `tests/test_nc_cli.py`; `uv run --with pytest pytest -q` verde.

## Decisions

- GET grava corpo e cabeçalhos em arquivos temporários (bytes exatos, sem tradução de CRLF); ETag usado literalmente em `If-Match`. Confiança alta.
- `bytes_appended` inclui o `\n` separador inserido. Confiança média.
- Leitura de volta por HEAD (`Content-Length`). Confiança alta.
- 412 com `--create` (alguém criou antes) também refaz o GET. Sem ETag no GET: exit 5. Confiança média.

## Comments
