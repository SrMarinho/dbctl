<!-- docs/specs/05-modulos.md — parte do SPEC do dbctl, seções 6.
     Índice e ordem de leitura: docs/specs/README.md. -->

## 6. Especificação de cada arquivo

Para cada módulo: responsabilidade, API pública e regras. Assinaturas são orientativas — o
implementador pode ajustar tipos, desde que mantenha a fronteira de responsabilidade.

### `logging.py`
Log **estruturado JSONL** — o canal de diagnóstico para loops de engenharia
(modelos lendo o log para melhorar o projeto). O console (Typer) segue sendo
o canal humano; o arquivo é máquina-legível de propósito.

- Arquivo por dia: `<log_dir>/dbctl-YYYY-MM-DD.jsonl`, uma linha = um evento.
  `log_dir`: `DBCTL_LOG_DIR` (env) → `<repo do tool>/logs` → `~/.dbctl/logs`
  (fallback). A pasta `logs/` é gitignored.
- Schema plano (snake_case): `ts` (ISO-8601 UTC), `run` (id da invocação,
  correlaciona todos os eventos de uma execução), `level` (debug/info/
  warning/error), `event`, `command`, contexto persistente (project_root,
  config) e campos por evento. Sem filtro de nível: o leitor filtra com `jq`.
- API: `init(command, **ctx) -> Path | None` (abre o arquivo do dia e grava
  `invocation` com argv/cwd/pid), `set_context(**fields)`, `log(level, event,
  **fields)` + helpers `debug/info/warning/error`, `log_exception()` (grava o
  traceback), `redact_argv()` (mascara `-e KEY=value` → `KEY=***`).
- **Segredos nunca são gravados**: todo argv passa por `redact_argv` antes de
  logar (o PGPASSWORD do `docker exec` vira `***`).
- Eventos principais: `invocation`/`command_ok`/`command_failed`/
  `command_crashed` (cli), `exec_ok`/`exec_failed`/`exec_dry_run` (docker.py,
  com duração e tail do erro), `detection`/`upgrade_plan`/`upgrade_nothing`,
  `create_phase` (stop, clone, filestore, sanitize, seeds, upgrade, start),
  `hook_checkout`/`hook_serving`/`hook_failed`/`hook_skipped`.
- Só biblioteca padrão (json/os/sys/threading/traceback/datetime/pathlib) —
  nenhuma dependência nova.

### `errors.py`
Exceções tipadas, todas herdando de `DbctlError`, cada uma com um `exit_code`:

| Exceção | Exit code | Quando |
|---|---|---|
| `ProjectNotFoundError` | 2 | Não achou `.dbctl.toml` na busca (subindo da cwd nem descendo do repo) |
| `ConfigError` | 3 | Config inválida ou incompleta |
| `GitError` | 4 | Não é repo git, ou HEAD destacado |
| `DockerError` | 5 | Container ausente, ou comando docker falhou |
| `DatabaseError` | 6 | Banco já existe, não existe, ou clone falhou |
| `SeedError` | 7 | Falha executando seeds |
| `UserAbort` | 130 | Usuário respondeu "não" numa confirmação |

`cli.py` captura `DbctlError`, imprime `Error: <mensagem>` em stderr e sai com o `exit_code`. Nenhum
traceback vaza para o usuário em erro esperado; `--verbose` mostra o traceback completo.

### `project.py`
- `project_root(start: Path) -> Path` — raiz do repositório git que contém `start`, via
  `git -C <start> rev-parse --show-toplevel`. Fora de um repo git → `GitError`.
- `find_config(start: Path, explicit: Path | None = None) -> Path` — implementa a ordem de descoberta
  da [seção 5.0](04-configuracao.md): `explicit` (ou `DBCTL_CONFIG`) primeiro; depois busca subindo de `start` até o topo do
  repo; por fim busca descendo do topo do repo (profundidade máxima 3, com poda de `.git`, `.venv`,
  `node_modules`, `__pycache__` e diretórios começando com ponto). Zero resultados →
  `ProjectNotFoundError` com mensagem explicando como injetar um projeto e citando `--config`/
  `DBCTL_CONFIG`. Mais de um resultado na busca descendente → `ConfigError` listando os caminhos.
- `hooks_dir(root: Path) -> Path` — diretório de hooks efetivo do repositório, via
  `git -C <root> rev-parse --git-path hooks` (resolvido relativo a `root`). Respeita `core.hooksPath`
  customizado, ao contrário de montar `<root>/.git/hooks` manualmente. `GitError` se não for repo git.
- `current_branch(root: Path) -> str` — via `git -C <root> rev-parse --abbrev-ref HEAD`. Se retornar
  `HEAD` (detached), levanta `GitError` — não há branch para nomear o banco.

### `naming.py`
- `database_name(branch: str, prefix: str) -> str`

Algoritmo exato:
1. `slug` = branch em lowercase, todo caractere fora de `[a-z0-9]` vira `_`, sequências de `_`
   colapsadas em um, `_` das pontas removidos.
2. `digest` = primeiros 6 hex de `sha1(branch.encode())` — do **nome original**, não do slug.
3. `budget` = `63 - len(prefix) - 7` (7 = `_` + 6 do digest).
4. Resultado: `f"{prefix}{slug[:budget]}_{digest}"`.

Propriedades exigidas: determinístico, sempre ≤ 63 chars, sempre começa com o prefixo, duas branches
diferentes nunca colidem (garantido pelo digest do nome completo).

Exemplo de referência: branch `GC-629-mod-fatura-notificacoes-fornecedor-nf-pendente-envio-sei` com
prefixo `dev_` → `dev_gc_629_mod_fatura_notificacoes_fornecedor_nf_p_<hash6>`.

### `docker.py`
Wrapper **único** de subprocess. Nenhum outro módulo chama `subprocess` diretamente — isso concentra
log, tratamento de erro e o modo `--dry-run`.

- `run(args: list[str], *, input: str | None, capture: bool) -> str`
- `exec_in(container: str, args: list[str], *, env: dict[str, str] | None = None, input=None, capture=False) -> str`
  → `docker exec [-e K=V ...] [-i] <container> <args>`. O parâmetro `env` é o canal para o
  `PGPASSWORD` do Postgres: a senha trafega pela API do Docker, não pela linha de comando do host.
- `compose(project_root, compose_files: list[str], args: list[str]) -> str` → `docker compose -f ... <args>`
- `container_running(name: str) -> bool`

Toda falha vira `DockerError` com o comando e o stderr. Se `DBCTL_DRY_RUN=1`, apenas imprime o comando
e não executa — usado na validação.

### `postgres.py`
Todas as operações via `docker.exec_in(pg_container, ["psql", "-U", user, "-d", "postgres", ...])`,
com `PGPASSWORD` passado por env do exec.

- `database_exists(cfg, name) -> bool`
- `list_databases(cfg, prefix: str | None) -> list[tuple[str, str]]` — nome e tamanho legível
- `terminate_connections(cfg, name) -> None` — `pg_terminate_backend` sobre `pg_stat_activity` daquele datname
- `clone_database(cfg, source, target) -> None` — `CREATE DATABASE "<target>" TEMPLATE "<source>"`
- `drop_database(cfg, name) -> None` — `DROP DATABASE IF EXISTS "<name>"`

**Regras de segurança, obrigatórias:**
- `drop_database` **recusa** qualquer nome que não comece com `db_prefix` — mesmo se chamada
  internamente. É a última linha de defesa.
- `clone_database` recusa se `target` já existir (erro claro sugerindo `dbctl reset`).
- Nomes sempre entre aspas duplas no SQL.

### `filestore.py`
Operações executadas **dentro de um container efêmero do serviço Odoo**, nunca no host. Motivo: o
diretório pertence ao uid 101 (`odoo`); copiar pelo host criaria arquivos com dono errado e exigiria
`sudo chown`. Rodando via `docker compose run --rm --no-deps <service> cp -a ...`, a cópia sai com o
dono correto (o entrypoint repassa comandos desconhecidos para `exec "$@"`).

- `copy(cfg, source_db, target_db) -> None` — copia `<data_dir>/filestore/<source>` para `<target>`;
  se a origem não existir, apenas registra aviso e segue (banco sem anexos é válido).
- `remove(cfg, db) -> None` — `rm -rf` do diretório do banco. Recusa nome sem o prefixo.

### `sanitize.py`
Roda logo após o clone, via `seeding.run_python(...)` (mesmo canal de `odoo shell`).

- `sanitize(cfg, db) -> None`, que dentro do Odoo:
  1. Gera um `database.uuid` novo em `ir.config_parameter` — o clone herda o UUID do original, o que
     confunde identificação de instância.
  2. Desativa todos os `ir.mail_server` — um banco de dev nunca deve conseguir enviar e-mail real.
  3. **Não** desativa `ir.cron`: testar crons é caso de uso legítimo de dev. Registrar isso como
     decisão explícita num comentário do código.

### `seeding.py`
- `run_python(cfg, db, code: str) -> str` — canal genérico: executa `code` dentro do Odoo via
  `docker compose run --rm --no-deps <service> odoo shell -d <db> --no-http`, com o código no stdin.
  Usar container efêmero (`run --rm`) e `--no-http` evita conflito de porta com o serviço que já está
  no ar. Usado tanto pelo `sanitize` quanto pelo `seed`.
- `run_seeds(cfg, db, branch) -> None` — o `compose run` do seed recebe **`-v <seeds_path_absoluto>:<mount>`
  explícito** (o caminho já vem absoluto do `config.py`). A montagem dos seeds **não depende do
  override do compose** — o `dbctl create` roda seeds *antes* de escrever o override, e essa ordem só
  é possível porque o volume é declarado no próprio comando do seed. Depois monta e envia um
  **bootstrap gerado no host** que:
  1. carrega `<mount>/base.py` por caminho, via `importlib.util.spec_from_file_location`, e chama
     `run(env)`;
  2. se `<mount>/branches/<slug>.py` existir, carrega e chama `run(env)` também;
  3. `env.cr.commit()`.

**Contrato dos seeds — crítico para o agnosticismo:**
- A pasta de seeds contém **arquivos soltos**, sem `__init__.py`, sem instalação de pacote.
- Um seed **não importa nada do `dbctl`** — recebe apenas `env` do Odoo. O tool não está instalado
  dentro do container, então qualquer import de `dbctl` quebraria.
- Um seed deve ser **idempotente**: verificar existência antes de criar. `dbctl seed` pode rodar
  várias vezes.
- Ausência de `branches/<slug>.py` é normal: roda só o `base.py`, sem erro.

### `strategies/base.py`
Interface (ABC) com quatro operações:
- `start(db: str) -> None` — deixa o Odoo servindo aquele banco
- `stop() -> None` — para o serviço
- `upgrade(db: str, modules: list[str]) -> None` — aplica `-u` e volta a servir
- `current_database() -> str | None` — qual banco o Odoo está servindo agora

### `strategies/compose_override.py`
Estratégia padrão e única totalmente implementada.

`start(db)` escreve o `override_file` na raiz do projeto:

```yaml
# GENERATED BY dbctl - DO NOT EDIT
services:
  <compose_service>:
    command: ["odoo", "-d", "<db>", "--db-filter=^<db>$"]
```

e depois roda `docker compose -f <compose_file> -f <override_file> up -d <compose_service>`.

Detalhes que o implementador precisa respeitar:
- Em Docker Compose, `command` de um override **substitui** o do arquivo base — comportamento
  desejado, com uma consequência: **o `command` do serviço no compose base deve ser apenas `odoo`**.
  Flags adicionais no command base seriam perdidas ao trocar de banco (documentar isso no README).
- O `--db-filter=^<db>$` elimina a tela de seleção de banco e impede o Odoo de tocar em outros bancos.
- **Nenhum bloco de `volumes` é emitido**: o override fica mínimo (só `command`). A montagem da pasta
  de seeds é responsabilidade do canal de seeding (`run_seeds`, via `-v` explícito), o que elimina a
  dependência de ordem entre seeds e `start`.
- O arquivo é sempre reescrito por completo, com o cabeçalho `GENERATED BY dbctl`.
- `current_database()` lê o `override_file`, se existir, e extrai o `-d`. Sem arquivo → `None`
  (Odoo está no `db_name` do `odoo.conf`, fora da gestão do tool).

`upgrade(db, modules)` — sequência obrigatória, para evitar `-u` "grudado" no override e evitar
upgrade concorrente com o servidor no ar:
1. `stop()` do serviço;
2. `docker compose run --rm --no-deps <service> odoo -d <db> -u <mods> --stop-after-init`;
3. `start(db)` de novo.

### `strategies/custom.py`
Escape hatch: executa os comandos declarados em `[strategy.commands]`, substituindo `{db}`,
`{modules}` e `{project_root}`. Não tenta ser esperto — se o projeto declarou, o tool roda. É o que
permite plugar um Odoo fora de Docker sem código novo no tool.

### `commands/*.py`
Cada arquivo orquestra um caso de uso e retorna dados para a CLI formatar. Sem `print` direto — a
formatação é responsabilidade de `cli.py`.

### `commands/hook.py`
Instala, remove e executa o hook `post-checkout` que mantém o Odoo servindo o banco certo a cada
troca de branch (ver Caso 3.1 nos [casos de uso](06-casos-de-uso.md)). Segue o mesmo contrato dos outros `commands/*.py`: retorna
dados, nunca imprime.

- Marcador `# GENERATED BY dbctl - DO NOT EDIT` no início do arquivo do hook, usado para diferenciar
  um hook nosso de um hook de terceiros.
- Script gerado por `install`, com o interpretador em caminho absoluto (`sys.executable`) e o
  `.dbctl.toml` em uso embutido — assim o hook funciona independente da venv estar ativa e sem
  depender da busca da [seção 5.0](04-configuracao.md) rodar de novo a cada checkout:
  ```sh
  #!/bin/sh
  # GENERATED BY dbctl - DO NOT EDIT (dbctl hook install)
  exec "<abs>/python" -m dbctl --config "<abs>/.dbctl.toml" hook post-checkout "$1" "$2" "$3"
  ```
- `install(cfg, *, force: bool = False) -> dict` — resolve `hooks_dir(project_root)`, cria o diretório
  se preciso, escreve o script acima e aplica `chmod 0o755`.
  - Arquivo já existe e tem o marcador → sobrescreve (`action: "updated"`).
  - Arquivo já existe e **não** tem o marcador (hook de terceiros) → `DbctlError`, a menos que
    `force=True`: nesse caso salva uma cópia como `post-checkout.bak` antes de sobrescrever. A
    mensagem de erro sem `--force` mostra a linha `exec ...` para o usuário colar manualmente no
    hook existente, como alternativa a perder o que já estava lá.
  - Respeita `DBCTL_DRY_RUN`: descreve a ação, não escreve nada.
- `uninstall(cfg) -> dict` — remove o arquivo **só** se contiver o marcador; nunca apaga um hook que
  não foi gerado pelo dbctl. Sem arquivo → `{"action": "absent"}`.
- `info(cfg) -> dict` — `{path, installed: bool, ours: bool, enabled: bool}`, usado por
  `dbctl hook status` e pela linha `hook:` de `dbctl status`.
- `on_checkout(cfg, prev: str, new: str, branch_flag: str) -> list[str]` — a lógica executada pelo
  runner oculto `dbctl hook post-checkout`. Recebe os três argumentos que o git passa a um
  `post-checkout` (`$1` SHA anterior, `$2` SHA novo, `$3` `1` se foi troca de branch / `0` se foi
  checkout de arquivo). Ordem de decisão:
  1. `branch_flag != "1"` → não faz nada (não foi uma troca de branch).
  2. `hooks.enabled` é falso → não faz nada (estado escolhido pelo usuário).
  3. HEAD destacado (`GitError` de `current_branch`, comum durante rebase/bisect) → registra aviso e
     sai, sem tentar resolver banco algum.
  4. `strategy.current_database()` já é igual ao banco alvo da branch atual → registra "já servindo
     `<db>`" e sai. **A comparação certa é o banco servido, não `prev` vs `new`**: `git checkout -b`
     a partir do commit atual troca de branch sem mudar o SHA, e `git checkout -- <arquivo>` já foi
     descartado no passo 1, então esse é o único caso restante a considerar.
  5. Banco alvo não existe → registra aviso sugerindo `dbctl create --use`, sai.
  6. Caso contrário, delega para `commands/use.py::run(cfg)` (reuso — nunca reimplementar a escrita
     do override aqui) e registra "serving `<db>`".
  Todas as mensagens retornadas começam com `dbctl:`, para se destacarem no meio do output do git.
  Esta função **nunca levanta** para o chamador: qualquer exceção interna vira uma linha de aviso na
  lista de retorno — é o `cli.py` quem garante o exit 0 (regra de ouro abaixo), mas a função já se
  protege por conta própria.

**Regra de ouro do hook:** o `post-checkout` gerado **nunca** pode fazer o `git checkout` falhar.
Todo caminho de erro — config ausente, Docker fora do ar, banco inexistente, HEAD destacado — termina
em uma linha de aviso em stderr e exit code 0.

### `cli.py`
Typer app. Um comando por caso de uso, mais o sub-app `hook` (`install`, `uninstall`, `status`, e o
comando oculto `post-checkout`). Flags globais: `--verbose` (traceback completo), `--project <path>`
(força a raiz do projeto) e `--config <path>` (força o arquivo `.dbctl.toml`, ver [configuração](04-configuracao.md)).

O comando `hook post-checkout` é o único que **não** passa pelo tratamento de erro padrão de
`_run()`: ele envolve toda a chamada a `commands/hook.py::on_checkout` num `try/except Exception`
próprio e sempre termina com `raise typer.Exit(0)`, para cumprir a regra de ouro do hook mesmo diante
de um bug inesperado no próprio dbctl.

---
