# 01 — Nomes com espaço nas pontas visíveis no `ls` e sugestão de nome no 404

Status: ready-for-agent
Blocked by: —

## Contexto

Em 2026-11-02 o arquivo `/HERMES-DROP/ Aracati - Ceará.zip` (o nome começa com espaço) apareceu no `nc-cli ls` como `📄  Aracati - Ceará.zip`: o espaço inicial ficou indistinguível do espaçamento após o ícone. O `nc-cli download "/HERMES-DROP/Aracati - Ceará.zip"` respondeu `ERROR: File not found ... (HTTP 404)` sem pista, e o agente gastou duas chamadas extras (`--json` + `od -c`) para descobrir o nome real.

## O que construir

1. No `ls` em modo humano (sem `--json`), um nome cujo início ou fim seja espaço em branco (ou que contenha caracteres de controle) é exibido entre aspas, com o espaço visível, ex.: `📄  " Aracati - Ceará.zip"`. Nomes comuns continuam sem aspas. O `--json` não muda: `name` já é o valor exato.
2. Quando um comando que recebe caminho remoto (`download`, `info`, `rm`, `mv`, `cp`, `share`, `ls` em caminho inexistente) termina em 404, o nc-cli lista o diretório-pai e sugere entradas cujo nome, normalizado (NFC, sem espaço nas pontas, comparação sem diferenciar maiúsculas), é igual ao nome pedido normalizado. A sugestão sai no stderr com o caminho exato entre aspas, pronto para copiar; com `--json`, entra como campo `suggestions` (lista de caminhos) no objeto de erro. O exit code continua 2.
3. Se o diretório-pai também não existir ou não houver candidato, o comportamento atual se mantém.

## Acceptance criteria

- [ ] `ls` humano mostra `" Aracati - Ceará.zip"` (com aspas) para um nome com espaço inicial, e `Aracati.zip` sem aspas para um nome comum.
- [ ] `ls --json` é byte a byte igual ao atual para os dois casos.
- [ ] `download "/D/Aracati - Ceará.zip"` contra um servidor onde só existe `/D/ Aracati - Ceará.zip` sai com código 2 e imprime no stderr uma sugestão contendo `"/D/ Aracati - Ceará.zip"`.
- [ ] O mesmo cenário com `--json` traz `suggestions: ["/D/ Aracati - Ceará.zip"]` no erro.
- [ ] Nome pedido em NFD (`Ceará`) casa com o nome do servidor em NFC.
- [ ] Sem candidato, a saída de erro é igual à atual.
- [ ] Testes novos em `tests/test_nc_cli.py`, no estilo dos existentes (servidor WebDAV fake / mocks já usados no arquivo); `uv run --with pytest pytest -q` verde.
- [ ] `docs/json-output.md` documenta o campo `suggestions`.

## Decisions

## Comments
