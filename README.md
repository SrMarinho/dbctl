# dbctl

**Um banco Odoo por branch, agnóstico de projeto.**

Num projeto Odoo, todas as branches compartilham o mesmo banco Postgres. O Odoo
aplica mudanças de schema com `-u`, mas **não reverte nada** no `git checkout`:
o banco fica com o schema da última branch que subiu. `dbctl` resolve isso com
um banco (e filestore) por branch, criado por clone de um banco template.

Trocar de branch passa a ser: `git checkout <branch>` + `dbctl use`.

## Desenvolvimento

Lint, formatação e tipos são garantidos por **pre-commit** (ruff + mypy):

```bash
uv tool install pre-commit     # uma vez
pre-commit install             # liga o hook de commit (já instalado no repo)
pre-commit run --all-files     # roda tudo manualmente
```

Configuração: `.pre-commit-config.yaml` + `[tool.ruff]`/`[tool.mypy]` no
`pyproject.toml` (linha 100, regras E/F/W/I/UP/B/SIM/C4; mypy com
`disallow_untyped_defs` etc.). Rodar localmente sem pre-commit:
`ruff check dbctl && ruff format --check dbctl && mypy dbctl`.

## Instalação

Requisitos: Python >= 3.11, Docker + Docker Compose v2, git. O tool **não**
precisa de `psql` no host nem de acesso direto à porta do Postgres — toda
operação de banco roda via `docker exec` no container do Postgres.

```bash
git clone <seu-repo-do-dbctl> ~/projects/dbctl
cd ~/projects/dbctl
python3 -m venv .venv
.venv/bin/pip install -e .
# (ou com uv: uv venv .venv && uv pip install -e .)
```

Use `.venv/bin/dbctl` (ou adicione ao PATH / crie um alias).

## Injetar um projeto novo (Caso 1)

O projeto precisa: ser um repo git; rodar Postgres e Odoo em containers Docker
com nomes estáveis; ter um `docker-compose.yml` com o serviço do Odoo (o
`command` do serviço deve ser apenas `odoo` — o override do dbctl substitui o
command ao trocar de banco, então flags extras seriam perdidas); e ter um banco
template existente.

1. Copie o exemplo e preencha:

   ```bash
   cp .dbctl.example.toml <projeto>/.dbctl.toml
   # edite: containers, credenciais, template_db, default_modules, seeds
   ```

   O `.dbctl.toml` pode viver **na raiz do repositório** ou **em qualquer
   subpasta** — inclusive numa pasta já ignorada pelo git (ex.: `temp/`), o que
   evita tocar num `.gitignore` versionado. Os caminhos relativos do config
   (`seeds.path`, `compose_file`, `override_file`) são sempre resolvidos a
   partir da **raiz do repositório git**, não da pasta do arquivo.

2. Se colocou na raiz, adicione `.dbctl.toml` (e a pasta de seeds) ao
   `.gitignore` do projeto. Se usou uma pasta já ignorada, este passo some.

3. Confirme:

   ```bash
   cd <projeto>
   dbctl status
   ```

**Descoberta do config (spec 5.0)** — a primeira que resolver vence:

1. `--config PATH` ou `DBCTL_CONFIG` (explícito, ignora a busca);
2. subindo da cwd até o topo do repositório git (`git rev-parse
   --show-toplevel`);
3. descendo do topo, profundidade máxima 3 (podando `.git`, `.venv`,
   `node_modules`, `__pycache__` e diretórios começando com ponto).

Zero resultados → erro 2; **mais de um** → erro 3 listando todos os caminhos
(ambiguidade nunca é resolvida em silêncio — use `--config`). Fora de um
repositório git → erro 4. `-p/--project` força a raiz do projeto quando a
descoberta automática não basta, e pode ser combinado com `--config`.

Todas as chaves do `.dbctl.toml` aceitam override por env var no padrão
`DBCTL_<SEÇÃO>_<CHAVE>` (ex.: `DBCTL_POSTGRES_PASSWORD`). Precedência:
**env var > arquivo > default**.

## Fluxo de trabalho diário

```bash
git checkout -b GC-700-nova-feature
dbctl create --use        # clona o template, copia filestore, sanitiza, roda seeds, serve
# mexeu num model? aplique so no banco desta branch:
dbctl upgrade     # detecta sozinho o que mudou desde a branch base
# (ou explicite: dbctl upgrade -m faturamento)

# alternar entre branches:
git checkout GC-629-...   # o código troca (montado ao vivo no container)
dbctl use                 # o Odoo passa a servir o banco da branch

# banco sujou? recomece:
dbctl reset               # dropa e recria a partir do template (confirmação)

# limpeza:
dbctl list                # bancos do prefixo com tamanho
dbctl drop                # remove banco + filestore (confirmação)
dbctl unuse               # remove o override; o projeto volta à config base
```

## Detecção automática de módulos alterados

O banco da branch nasceu de um clone do template, que reflete a branch base —
então **o que a branch mudou desde a base é exatamente o que precisa de `-u`**.
Sem `-m`, o `dbctl upgrade` descobre isso sozinho:

1. base = `[modules].base_ref` → `origin/HEAD` → `main`/`master`/`develop`;
2. `git merge-base HEAD <base>` (pega commitado **e** não commitado);
3. caminhos alterados → diretório com o manifesto (`__manifest__.py`, configurável);
4. módulo detectado mas **não instalado** (pasta nova) → entra com `-i`, não `-u`.

```bash
dbctl upgrade                  # detecta e aplica
dbctl upgrade --no-detect      # comportamento antigo (-m / default_modules)
dbctl status                   # preview: linha "modules:" mostra o que seria
                               # aplicado, sem executar nada
dbctl create                   # o banco já nasce com o schema da branch
```

Configuração (`[modules]` no `.dbctl.toml`):

| Chave | Default | Efeito |
|---|---|---|
| `detect` | `true` | `false` volta ao comportamento antigo |
| `base_ref` | auto | branch base explícita (ex.: `"origin/main"`) |
| `manifest` | `__manifest__.py` | o que marca a raiz de um módulo |
| `install_new` | `true` | módulo novo → `-i`; `false` → `-u` (no-op silencioso) |
| `ignore` | `[]` | globs que nunca disparam upgrade (ex.: `["**/static/**"]`) |

Casos de borda: na branch base, nada é detectado (cai em `default_modules`);
clone shallow → erro explicando que falta histórico; arquivos fora de módulos
(`docker-compose.yml`, README) são ignorados (visíveis com `--verbose`).

## Logs estruturados (JSONL)

Cada execução do dbctl grava um log **estruturado** (JSON Lines) em
`<repo>/logs/dbctl-YYYY-MM-DD.jsonl` — uma linha por evento, schema plano:

```json
{"ts":"2026-08-13T14:34:00.369+00:00","run":"20260813T143400.367",
 "level":"error","event":"command_failed","command":"status",
 "error_type":"GitError","message":"'/tmp' is not inside a git repository...",
 "exit_code":4,"duration_ms":2}
```

Por que JSONL e não texto puro: um modelo (ou `jq`) consome eventos sem
ambiguidade de parsing — timestamp ISO-8601 UTC, `run_id` para correlacionar
uma execução inteira, `level`/`event`/`command` fixos e campos por evento.
O console (Typer) continua sendo o canal humano; o arquivo é o canal de
diagnóstico.

O que é logado:
- `invocation` / `command_ok` / `command_failed` / `command_crashed` — cada
  comando, com argv, cwd, resultado, exit code e duração (traceback completo
  nos crashes);
- `exec_ok` / `exec_failed` / `exec_dry_run` — **todo comando docker/git**,
  com argv, duração e tail do erro (até 4000 chars);
- `detection` / `upgrade_plan` / `upgrade_nothing` — decisões da detecção de
  módulos (base_ref, sha, módulos, unmatched);
- `create_phase` — cada fase do create (stop, clone, filestore, sanitize,
  seeds, upgrade, start);
- `hook_checkout` / `hook_serving` / `hook_failed` — decisões do hook.

Segredos são **redigidos** antes de gravar: flags `-e KEY=value` do
`docker exec` viram `KEY=***` (o PGPASSWORD nunca aparece no log).

Uso no loop de engenharia:

```bash
tail -f logs/dbctl-*.jsonl
jq 'select(.level=="error")' logs/dbctl-*.jsonl | tail
jq 'select(.event=="command_failed")' logs/dbctl-*.jsonl | tail -1
jq --arg run "20260813T143400" 'select(.run==$run)' logs/dbctl-*.jsonl   # uma execução
```

- `DBCTL_LOG_DIR=/caminho` muda o diretório (default: `logs/` do repo; fallback `~/.dbctl/logs`).
- `logs/` é gitignored.

## Hook post-checkout (opcional, Caso 3.1)

Quer trocar de branch sem digitar `dbctl use`? Instale o hook uma vez:

```bash
dbctl hook install        # instala .git/hooks/post-checkout (chmod 0755)
dbctl hook status         # path, dono (dbctl/terceiro), enabled
dbctl hook uninstall      # remove SÓ se foi o dbctl que gerou
```

A partir daí, todo `git checkout <branch>` com banco existente roda o `use`
sozinho (`dbctl: serving <db>` no output do git). **Regra de ouro:** o hook
nunca faz o checkout falhar — config ausente, Docker fora do ar, banco
inexistente e HEAD destacado viram avisos `dbctl:` e o checkout sempre
conclui com exit 0.

Para desligar temporariamente sem desinstalar: `[hooks] enabled = false` no
`.dbctl.toml` (ou `DBCTL_HOOKS_ENABLED=0` na sessão). Se já existir um
`post-checkout` de terceiros, o `install` recusa com a linha `exec` para colar
manualmente; `install --force` faz backup como `post-checkout.bak` e sobrescreve.

| Comando | O que faz |
|---|---|
| `status` | Relatório somente-leitura: branch, banco alvo, servido, seed da branch |
| `create [--from T] [--no-seed] [--use] [--no-upgrade]` | Clone do template + filestore + sanitize + seeds + **schema da branch** |
| `use` | Aponta o serviço para o banco da branch (`-d` + `--db-filter` no override) |
| `unuse` | Remove o `docker-compose.override.yaml` (reversível) |
| `upgrade [-m mod1,mod2] [--all] [--no-detect]` | Aplica schema no banco da branch; sem `-m`, **detecta os módulos alterados** desde a branch base (`-i` para módulos novos) |
| `seed` | Roda `base.py` e `branches/<slug>.py`, se existir |
| `list` | Lista só os bancos com o `db_prefix`, com tamanho e marcações |
| `drop [--yes] [--db NAME]` | Remove banco + filestore; **recusa** nome sem o prefixo |
| `reset [--yes]` | Drop + create com seeds; uma única confirmação |
| `hook install/uninstall/status` | Gerencia o post-checkout (ver seção acima) |

Flags globais: `--verbose` (traceback completo), `--project <caminho>` e
`--config <caminho>`.
`DBCTL_DRY_RUN=1` imprime os comandos sem executar.

## Como o banco da branch é escolhido

`dbctl use` escreve um `docker-compose.override.yaml` na raiz do projeto
(arquivo gitignored, **único** arquivo que o tool escreve no projeto):

```yaml
# GENERATED BY dbctl - DO NOT EDIT
services:
  web:
    command: ["odoo", "-d", "dev_gc_700_abc123", "--db-filter=^dev_gc_700_abc123$"]
```

O `command` substitui o do compose base; o `--db-filter` elimina a tela de
seleção de banco. Apagar o arquivo (ou `dbctl unuse`) devolve o projeto ao
comportamento original. O tool **nunca** edita `odoo.conf` nem `docker-compose.yml`.

## Nomes de banco

`dev_<slug da branch>_<6 hex do sha1 da branch inteira>` — sempre <= 63 chars,
determinístico, começa com o `db_prefix`, e duas branches diferentes nunca
colidem (o digest usa o nome completo, não o slug truncado).

## Seeds

A pasta de seeds (definida em `[seeds].path`) contém **arquivos soltos**, sem
`__init__.py`, que recebem apenas `env` do Odoo — **não importam o dbctl**:

```python
# temp/seeds/base.py — roda sempre
def run(env):
    item = env["meu.modelo"]
    if not item.search_count([("name", "=", "x")]):
        item.create({"name": "x"})   # idempotente!
```

- `base.py` roda em toda branch; `branches/<slug>.py` só na branch correspondente.
- Um seed deve ser **idempotente** (verificar existência antes de criar).
- `dbctl seed` pode rodar quantas vezes quiser.
- A pasta é montada no container efêmero via `-v` explícito — não depende do
  override do compose.

## Sanitize pós-clone

Todo banco clonado passa por `odoo shell` que: gera um `database.uuid` novo e
desativa todos os `ir.mail_server` (um banco de dev nunca deve enviar e-mail
real). `ir.cron` **não** é desativado — decisão deliberada: testar crons é caso
de uso legítimo de dev.

## Segurança

- `db_prefix` (default `dev_`) é a proteção contra dropar banco alheio: o drop
  recusa qualquer nome fora do prefixo, na camada de comando **e** dentro do
  próprio `drop_database` (última linha de defesa).
- O banco template nunca é modificado pelo tool (só clonado).
- A senha do Postgres trafega por env do `docker exec` (API do Docker), nunca
  pela linha de comando do host.

## Resolução de problemas

- **`database 'dev_x_...' already exists`** — o banco da branch já existe; rode
  `dbctl reset` para recriar do template.
- **`database 'dev_x_...' does not exist`** — rode `dbctl create` primeiro.
- **`refusing to drop ...`** — o nome não começa com o `db_prefix`; o tool não
  mexe em bancos que não criou.
- **Clone falhou com "being accessed by other users"** — o Odoo mantinha pool
  aberto no template. O `create` já para o serviço e encerra conexões antes de
  clonar; se persistir, confira se outro processo está conectado ao template.
- **`odoo shell failed ... (seeds)`** — o seed quebrou; a mensagem traz o
  traceback do Odoo e nada foi commitado (sem commit parcial).
- **O serviço subiu com o banco errado** — confira o `docker-compose.override.yaml`
  (`dbctl status` mostra o banco servido) e rode `dbctl use`.
- **Quero voltar ao comportamento original** — `dbctl unuse` remove o override.
