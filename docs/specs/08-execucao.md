<!-- docs/specs/08-execucao.md — parte do SPEC do dbctl, seções 9.
     Índice e ordem de leitura: docs/specs/README.md. -->

## 9. Plano de execução

Cinco entregas. Cada uma é um commit no repositório correspondente e deve deixar o projeto num estado
utilizável.

**E1 — Fundação do tool** (`~/projects/dbctl`)
`pyproject.toml`, `errors.py`, `config.py`, `project.py`, `naming.py`, `docker.py`,
`.dbctl.example.toml`, e `cli.py` com apenas `status`.
*Pronto quando:* `dbctl status` funciona num projeto injetado e todos os erros de config/descoberta
saem com mensagem clara e exit code correto.

**E2 — Ciclo de vida do banco**
`postgres.py`, `filestore.py`, `sanitize.py`, `strategies/` completo, e os comandos `create`, `use`,
`upgrade`, `list`, `drop`, `reset`.
*Pronto quando:* dá para criar, usar, atualizar e dropar o banco de uma branch, com `--no-seed`.

**E3 — Seeds**
`seeding.py`, comando `seed`, integração no `create`.
*Pronto quando:* `base.py` e `branches/<slug>.py` rodam, e rodar duas vezes não duplica dados.

**E4 — Sandbox** (`~/projects/dbctl-sandbox`)
O projeto do item 8, com as três branches e o `.dbctl.toml`.
*Pronto quando:* o sandbox sobe sozinho e o `dbctl status` o reconhece.

**E5 — Validação e documentação**
Executar todo o plano de [validação](09-validacao.md) contra o sandbox, corrigir o que falhar, e escrever o
`README.md` do tool com: instalação, injeção de um projeto novo, fluxo de trabalho diário, formato dos
seeds e resolução de problemas comuns.

**Ordem obrigatória:** E1 → E2 → E3 → E4 → E5. O sandbox (E4) pode ser antecipado se ajudar a testar
E2/E3, mas não deve atrasar a fundação.

---
