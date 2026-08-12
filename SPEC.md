# dbctl — Especificação completa

**Um banco Odoo por branch, agnóstico de projeto.**
Documento de delegação: contém contexto, arquitetura, spec de cada arquivo, fluxos, plano de
execução, plano de validação e critérios de avaliação.

- **Idioma:** prosa em português; **todo código, nome de arquivo, função, variável, comando de CLI e
  mensagem de log em inglês.**
- **Escopo:** MVP. Só o essencial e funcional. O que estiver em "Fora de escopo" não deve ser feito.
- **Dois entregáveis:** (1) o tool `~/projects/dbctl`; (2) um projeto Odoo sandbox
  `~/projects/dbctl-sandbox` para testar sem tocar no projeto real.

---

## 1. Problema

Num projeto Odoo, todas as branches compartilham o mesmo banco Postgres. O Odoo aplica mudanças de
schema no banco quando roda com `-u` (upgrade de módulo), mas **não reverte nada** quando você faz
`git checkout` para outra branch. O banco fica com o schema da última branch que subiu.

Ao voltar para outra branch, o código espera campos/views/ações que o banco não tem — ou convive com
colunas e registros de `ir.model.data` deixados por uma feature que não existe mais no código atual.
O resultado é erro na subida do Odoo ou comportamento inconsistente.

Exemplo real no projeto que motivou isto (`credsus`): a branch `GC-629` adicionou o campo `url_sei` ao
model `faturamento.fatura` e criou dois registros `mail.template`. Qualquer outra branch passa a
carregar esse resíduo.

**Solução:** um banco (e um filestore) por branch, criado por clone de um banco template. Trocar de
branch passa a ser `git checkout` + apontar o Odoo para o banco daquela branch.

**Decisão registrada — por que não git worktrees:** worktree resolve ter vários *códigos* checkoutados
simultaneamente; não resolve drift de schema (várias worktrees apontando ao mesmo banco reproduzem o
erro idêntico). Só valeria para rodar duas branches ao mesmo tempo, o que não é requisito, e custaria
container, porta e filestore por worktree. **Não implementar worktrees.**

---

## 2. Glossário

| Termo | Significado |
|---|---|
| **tool** | O `dbctl` em si, em `~/projects/dbctl`. Agnóstico, não conhece nenhum projeto. |
| **projeto injetado** | Qualquer projeto Odoo (repositório git) que tenha um `.dbctl.toml` em algum lugar da árvore. |
| **template DB** | Banco de origem do clone (ex.: `greencompras_local`). Nunca é modificado. |
| **branch DB** | Banco derivado, pertencente a uma branch. Sempre começa com o `db_prefix`. |
| **filestore** | Diretório de anexos do Odoo, um por banco, dentro do container (`<data_dir>/filestore/<db>`). |
| **seed** | Arquivo Python com uma função `run(env)` que popula dados via ORM do Odoo. |
| **slug** | Nome da branch normalizado para caber em identificador Postgres. |

---

## 3. Pré-requisitos

### 3.1 Do host (já verificados na máquina alvo)

| Requisito | Estado verificado | Como conferir |
|---|---|---|
| Python ≥ 3.11 | Python 3.14.4 presente | `python3 --version` |
| Docker + Docker Compose v2 | presentes e em uso | `docker ps`, `docker compose version` |
| Git | presente | `git --version` |
| pipx / uv / poetry | **ausentes** — usar `venv` + `pip` | `which pipx uv poetry` |

O tool **não** deve exigir client `psql` no host, nem acesso direto à porta do Postgres. Toda operação
de banco é feita via `docker exec` no container do Postgres. Isso é requisito de portabilidade.

### 3.2 Do projeto injetado

Para um projeto Odoo ser gerenciável pelo `dbctl`, ele precisa:

1. Ser um repositório git (o nome da branch é a chave de tudo — e agora também a base de descoberta
   do config, ver 5.0).
2. Rodar Postgres e Odoo em containers Docker, com nomes de container estáveis.
3. Ter um `docker-compose.yml` com um serviço de Odoo identificável.
4. Ter um banco template já existente e funcional.
5. Ter um `.dbctl.toml` em algum lugar do repositório — não precisa ser a raiz (ver 5.0).

### 3.3 Ambiente de referência (projeto `credsus`) — fatos verificados

Estes dados foram levantados na máquina e servem de referência concreta. **O tool não deve conter
nenhum destes valores hardcoded** — eles só existem no `.dbctl.toml` do projeto.

| Item | Valor |
|---|---|
| Container Postgres | `db-green-compras-local` (imagem `postgres:17`, porta host 5433) |
| Credenciais Postgres | user `foo-user`, senha `foo-pass` |
| Bancos existentes | `greencompras_local` (59 MB), `odoo` (75 MB), `ssp` (59 MB) |
| Container Odoo | `green-compras-local` (imagem `credsus-web`, portas 8069 e 8072) |
| Serviço compose do Odoo | `web` |
| `data_dir` do Odoo | `/var/lib/odoo` (host: `../odoo-resource-local`) |
| Filestore | `/var/lib/odoo/filestore/<db>` — 13 MB no `greencompras_local` |
| Config do Odoo | `config/odoo.conf`, **versionado**, com `db_name` **comentado** (o banco é sempre escolhido em runtime por `-d`), `dbfilter = ^%d$`, `list_db = True`, `admin_passwd = master` |
| Montagem de código | `./odoo-cotacao/:/mnt/odoo-cotacao` — **código montado ao vivo**, então `git checkout` já troca o código dentro do container, sem rebuild |
| Entrypoint | `config/entrypoint.sh` — intercepta `odoo` como primeiro argumento, dá `shift` e executa `odoo "$@"`; qualquer outro comando cai em `exec "$@"` (ou seja, `cp`, `ls` etc. funcionam via `docker compose run`) |
| `.gitignore` já contém | `/temp/`, `/docker-compose.override.yaml`, `/docker-compose.yaml`, `/config/.env` |

Duas consequências importantes desses fatos:

- **`config/odoo.conf` é versionado e não pode ser editado pelo tool.** O banco é escolhido em runtime
  via `-d` na linha de comando. O `db_name` estar comentado (em vez de preenchido) reforça isso:
  o tool nunca depende de um valor fixo no arquivo.
- **`docker-compose.override.yaml` é gitignored** — é o ponto de extensão sancionado para trocar o
  `command` do serviço Odoo sem sujar o repositório.

---

## 4. Arquitetura

### 4.1 Visão geral

Monólito modular. Uma única aplicação Python, dividida em módulos com fronteiras claras. A CLI é uma
casca fina: faz parsing de argumentos e formata saída, **nunca contém regra de negócio**.

```
┌─────────────────────────────────────────────────────────┐
│ cli.py  (Typer)  — parsing, output, exit codes           │
├─────────────────────────────────────────────────────────┤
│ commands/  — orquestração de cada caso de uso            │
├──────────┬──────────┬───────────┬──────────┬────────────┤
│ postgres │ filestore│ sanitize  │ seeding  │ strategies │
├──────────┴──────────┴───────────┴──────────┴────────────┤
│ config.py · project.py · naming.py · docker.py · errors  │
└─────────────────────────────────────────────────────────┘
```

**Regra de dependência:** camadas de baixo nunca importam de cima. `cli.py` importa `commands/`;
`commands/` importa os módulos de serviço; os de serviço importam só a camada base.

### 4.2 Estrutura de arquivos do tool

```
~/projects/dbctl/
  README.md
  pyproject.toml
  .dbctl.example.toml
  .gitignore
  dbctl/
    __init__.py            # versão apenas; sem imports pesados
    __main__.py            # entrypoint: `python -m dbctl`
    cli.py                 # Typer app
    errors.py              # exceções tipadas + exit codes
    config.py              # carrega e valida .dbctl.toml
    project.py             # descoberta da raiz do projeto + git
    naming.py              # branch -> nome de banco
    docker.py              # wrapper único de subprocess p/ docker
    postgres.py            # operações de banco
    filestore.py           # operações de filestore
    sanitize.py            # neutralização pós-clone
    seeding.py             # execução dos seeds
    strategies/
      __init__.py          # seleção da estratégia
      base.py              # interface (ABC)
      compose_override.py  # estratégia implementada
      custom.py            # escape hatch
    commands/
      __init__.py
      status.py
      create.py
      use.py
      unuse.py
      upgrade.py
      seed.py
      list_dbs.py
      drop.py
      reset.py
      hook.py              # instala/remove o post-checkout
```

### 4.3 Estrutura no projeto injetado

O `.dbctl.toml` pode morar na raiz do repositório ou em qualquer subpasta (inclusive uma pasta já
ignorada pelo git — ver 5.0 para a ordem de descoberta). Em qualquer um dos dois casos, os caminhos
relativos **dentro** do config (`seeds.path`, `odoo.compose_file`, `strategy.override_file`) são
resolvidos a partir da **raiz do repositório git**, nunca a partir da pasta onde o arquivo está.

**Na raiz** (arranjo mais simples):
```
<projeto>/
  .dbctl.toml                    # config (gitignored — contém credenciais locais)
  <seeds_path>/                  # caminho livre, definido na config
    base.py                      # roda sempre
    branches/
      <slug>.py                  # roda só na branch correspondente
```

**Em pasta já ignorada** (evita tocar no `.gitignore` versionado — arranjo do `credsus`):
```
<projeto>/
  temp/                          # já está em /temp/ no .gitignore
    .dbctl.toml                  # config
    seeds/
      base.py
      branches/
        <slug>.py
```
No `credsus`, `seeds_path = "temp/seeds"` e o `.dbctl.toml` também vive em `temp/`, porque `/temp/`
já está no `.gitignore` — não exige mexer em arquivo versionado. Em outro projeto pode ser qualquer
pasta.

---

## 5. Especificação de configuração

### 5.0 Localização do arquivo `.dbctl.toml`

O `.dbctl.toml` **não** precisa estar na raiz do projeto. A raiz do projeto (`project_root`) e o
arquivo de config (`path`) são dois conceitos distintos:

- **`project_root`** = topo do repositório git, via `git rev-parse --show-toplevel`. É a base de todo
  caminho relativo do config (`seeds.path`, `odoo.compose_file`, `strategy.override_file`) e a cwd do
  `docker compose`. Fora de um repo git → `GitError` (exit 4).
- **`path`** = o arquivo `.dbctl.toml` em si, em qualquer lugar dentro do repositório.

Ordem de descoberta (a primeira que resolver vence):

1. **`--config PATH`** (flag global) ou **`DBCTL_CONFIG`** (env var). Explícito, ignora toda busca;
   caminho inexistente → `ConfigError`.
2. **Subindo da cwd** até o topo do repositório, procurando `.dbctl.toml` — comportamento de sempre,
   preservado como caso comum (arquivo na raiz ou numa pasta acima da cwd).
3. **Descendo do topo do repositório**, com profundidade máxima 3 e poda de `.git`, `.venv`,
   `node_modules`, `__pycache__` e diretórios começando com ponto.
   - Nenhum `.dbctl.toml` encontrado → `ProjectNotFoundError` (exit 2), mencionando `--config` /
     `DBCTL_CONFIG` como alternativas.
   - **Mais de um encontrado → `ConfigError` (exit 3)** listando todos os caminhos e pedindo para
     escolher com `--config`. Ambiguidade nunca é resolvida em silêncio — o banco que o Odoo serve
     depende de qual arquivo é lido.

A flag `-p/--project` continua existindo e passa a significar "raiz do projeto" (para quando a
descoberta automática do repo git não é suficiente); pode ser combinada com `--config`.

### 5.1 Arquivo `.dbctl.toml`

```toml
[postgres]
container   = "db-green-compras-local"   # obrigatório
user        = "foo-user"                 # obrigatório
password    = "foo-pass"                 # opcional se DBCTL_PG_PASSWORD estiver setado
template_db = "greencompras_local"       # obrigatório
db_prefix   = "dev_"                     # opcional, default "dev_"

[odoo]
container       = "green-compras-local"  # obrigatório
compose_service = "web"                  # obrigatório
compose_file    = "docker-compose.yml"   # opcional, default "docker-compose.yml"
data_dir        = "/var/lib/odoo"         # opcional, default "/var/lib/odoo"
default_modules = ["faturamento"]         # opcional, usado pelo `upgrade` sem -m

[seeds]
path  = "temp/seeds"                     # opcional; se ausente, comando `seed` é no-op avisando
mount = "/mnt/dbctl-seeds"               # opcional, default "/mnt/dbctl-seeds"

[strategy]
kind          = "compose-override"       # "compose-override" | "custom"
override_file = "docker-compose.override.yaml"   # só para compose-override

[hooks]
enabled = true                           # opcional, default true; false desliga o post-checkout
                                          # sem desinstalá-lo (ver 7.1, `dbctl hook`)

# Escape hatch — só quando kind = "custom".
# Placeholders disponíveis: {db}, {modules}, {project_root}
# [strategy.commands]
# start   = "..."
# stop    = "..."
# upgrade = "..."
# shell   = "..."
```

### 5.2 Regras de validação da config

O `config.py` deve falhar **antes** de qualquer efeito colateral, com mensagem apontando a chave
problemática e o caminho do arquivo:

1. Chaves obrigatórias ausentes → erro listando todas de uma vez (não uma por vez).
2. `strategy.kind` fora do conjunto permitido → erro listando os valores válidos.
3. `strategy.kind = "custom"` sem `[strategy.commands].start`/`stop` → erro.
4. `postgres.password` ausente **e** `DBCTL_PG_PASSWORD` ausente → erro.
5. `seeds.path` apontando para diretório inexistente → **aviso**, não erro (o projeto pode ainda não
   ter seeds).
6. `db_prefix` vazio ou que não case com `^[a-z][a-z0-9_]*$` → erro (o prefixo é a proteção contra
   dropar banco alheio).
7. `seeds.path` é resolvido para **caminho absoluto** no carregamento (base: a raiz do **repositório
   git**, não a pasta onde o `.dbctl.toml` está — ver 5.0). É esse caminho absoluto que vai no `-v` do
   `compose run` do seed — `compose run -v` exige caminho absoluto do host.
8. `hooks.enabled` aceita apenas os literais booleanos reconhecidos (arquivo: `true`/`false` do TOML;
   env var: `1/true/yes/on` e `0/false/no/off`, case-insensitive). Valor não reconhecido → erro
   apontando a chave. Bloco `[hooks]` ausente é equivalente a `enabled = true`.

### 5.3 Overrides por variável de ambiente

Todas as chaves aceitam override por env var no padrão `DBCTL_<SEÇÃO>_<CHAVE>` em maiúsculas
(ex.: `DBCTL_POSTGRES_PASSWORD`, `DBCTL_ODOO_CONTAINER`, `DBCTL_HOOKS_ENABLED`). Precedência:
**env var > arquivo > default**.

Duas variáveis adicionais, fora do padrão `DBCTL_<SEÇÃO>_<CHAVE>` por não pertencerem a nenhuma seção
do TOML — controlam a própria descoberta do arquivo (ver 5.0):
- `DBCTL_CONFIG` — caminho explícito do `.dbctl.toml`, equivalente à flag `--config`.
- `DBCTL_DRY_RUN` — já documentado em `docker.py` (seção 6).

---

## 6. Especificação de cada arquivo

Para cada módulo: responsabilidade, API pública e regras. Assinaturas são orientativas — o
implementador pode ajustar tipos, desde que mantenha a fronteira de responsabilidade.

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
  da seção 5.0: `explicit` (ou `DBCTL_CONFIG`) primeiro; depois busca subindo de `start` até o topo do
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
troca de branch (ver CU-3.1 na seção 7). Segue o mesmo contrato dos outros `commands/*.py`: retorna
dados, nunca imprime.

- Marcador `# GENERATED BY dbctl - DO NOT EDIT` no início do arquivo do hook, usado para diferenciar
  um hook nosso de um hook de terceiros.
- Script gerado por `install`, com o interpretador em caminho absoluto (`sys.executable`) e o
  `.dbctl.toml` em uso embutido — assim o hook funciona independente da venv estar ativa e sem
  depender da busca da seção 5.0 rodar de novo a cada checkout:
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
(força a raiz do projeto) e `--config <path>` (força o arquivo `.dbctl.toml`, ver 5.0).

O comando `hook post-checkout` é o único que **não** passa pelo tratamento de erro padrão de
`_run()`: ele envolve toda a chamada a `commands/hook.py::on_checkout` num `try/except Exception`
próprio e sempre termina com `raise typer.Exit(0)`, para cumprir a regra de ouro do hook mesmo diante
de um bug inesperado no próprio dbctl.

---

## 7. Casos de uso e fluxos

### CU-1 — Injetar um projeto novo
**Ator:** desenvolvedor com um projeto Odoo ainda não gerenciado.
1. Copia `.dbctl.example.toml` como `.dbctl.toml`, na raiz do projeto **ou** dentro de uma pasta já
   ignorada pelo git (ver 4.3 e 5.0) — a segunda opção evita mexer em `.gitignore` versionado.
2. Preenche containers, credenciais e template DB.
3. Se optou pela raiz, adiciona `.dbctl.toml` e a pasta de seeds ao `.gitignore` do projeto (o exemplo
   deve trazer essa instrução comentada no topo). Se colocou numa pasta já ignorada, este passo some.
4. `dbctl status` → confirma que o projeto foi detectado, mostra qual `.dbctl.toml` foi usado
   (`config:`) e o banco alvo da branch atual.

**Critério:** nenhum arquivo versionado do projeto precisou ser alterado — nem o `.gitignore`, se o
config foi colocado numa pasta já ignorada.

### CU-2 — Começar a trabalhar numa branch nova
1. `git checkout -b GC-700-nova-feature`
2. `dbctl create` — clona o template, copia filestore, sanitiza, roda seeds.
3. `dbctl use` — o Odoo passa a servir o banco dessa branch.
4. `dbctl upgrade -m modulo_alterado` — aplica mudanças de schema **só nesse banco**.

### CU-3 — Alternar entre branches (o fluxo que resolve o problema)
1. `git checkout GC-629-...` → `dbctl use`
2. Trabalha, roda `dbctl upgrade` quando muda model.
3. `git checkout GC-723-hotfix...` → `dbctl use`
4. O Odoo sobe **sem erro**, porque o banco dessa branch nunca viu as mudanças da GC-629.
5. Voltar para a GC-629 → `dbctl use` → o banco anterior está intacto.

### CU-3.1 — Alternar entre branches sem lembrar do `dbctl use`
1. `dbctl hook install` — uma vez só, instala o `post-checkout`.
2. `git checkout GC-629-...` — o hook chama `dbctl use` sozinho; Odoo já sobe no banco certo.
3. `git checkout GC-723-hotfix...` — idem, sem digitar `dbctl use`.
4. Se a branch nova ainda não tem banco, o hook só avisa (`dbctl create --use` primeiro) — o checkout
   nunca é bloqueado nem o tool cria banco sozinho durante um checkout.
5. Para desligar temporariamente sem desinstalar: `[hooks] enabled = false` no `.dbctl.toml`, ou
   `DBCTL_HOOKS_ENABLED=0` na sessão do shell.

### CU-4 — Banco sujou, recomeçar
`dbctl reset` — dropa e recria a partir do template, com seeds. Uma confirmação, a não ser com `--yes`.

### CU-5 — Dados específicos da branch
1. Cria `<seeds_path>/branches/<slug>.py` com uma função `run(env)` idempotente.
2. `dbctl seed` — roda `base.py` e depois o arquivo da branch.
3. `dbctl status` mostra qual arquivo de seed foi detectado para a branch atual.

### CU-6 — Limpeza
1. `dbctl list` — mostra todos os bancos do prefixo com tamanho.
2. `dbctl drop` na branch já mergeada — remove banco e filestore, com confirmação.

### 7.1 Especificação comando a comando

Para cada comando: pré-condições verificadas **antes** de qualquer efeito colateral, passos, saída e
falhas esperadas.

#### `dbctl status`
- **Pré:** projeto encontrado, config válida, repo git.
- **Passos:** resolve branch → nome do banco → checa existência → lê `current_database()` da estratégia
  → detecta se há seed de branch → lê `hook.info(cfg)`.
- **Saída:** projeto (caminho da raiz), **config (caminho do `.dbctl.toml` em uso)**, branch, banco
  alvo, existe (sim/não), banco servido agora, template, seed da branch detectado (caminho ou
  "nenhum"), **hook** (`installed, enabled` / `installed, disabled` / `not installed`).
- **Aviso opcional:** se `git status --porcelain` do projeto não estiver vazio, uma linha `warning:
  working tree has uncommitted changes` — o banco da branch pode não ter o schema do código ainda não
  commitado. Só aviso, nunca bloqueia.
- **Efeito colateral:** nenhum. Este comando é sempre seguro.

#### `dbctl create [--from TEMPLATE] [--no-seed] [--use]`
- **Pré:** banco alvo **não** existe (senão erro sugerindo `reset`); template existe; containers
  Postgres e do serviço Odoo conhecidos.
- **Passos:**
  1. `strategy.stop()` — necessário porque o Postgres exige **zero conexões** no template para clonar,
     e o Odoo mantém pool aberto;
  2. `terminate_connections(template)` — remove conexões residuais;
  3. `clone_database(template → alvo)`;
  4. `filestore.copy(template → alvo)`;
  5. `sanitize(alvo)` — roda antes do override existir, então usa o mesmo canal efêmero do seed;
  6. `run_seeds(alvo)`, salvo `--no-seed` — monta a pasta de seeds via `-v` explícito, sem depender
     do override (que só é escrito no passo 7);
  7. se `--use`, `strategy.start(alvo)`; senão, restaura o serviço no banco em que estava antes.
- **Falhas:** se o clone falhar no meio, o comando deve tentar remover o banco parcial antes de
  propagar o erro, para não deixar estado sujo.

#### `dbctl use`
- **Pré:** banco da branch existe (senão erro sugerindo `create`).
- **Passos:** `strategy.start(db)`.
- **Saída:** banco servido e URL de acesso.

#### `dbctl unuse`
- **Pré:** nenhum.
- **Passos:** remove o `override_file`, se existir.
- **Saída:** confirma a remoção e avisa que o próximo `docker compose up` usa a config base do projeto
  (comportamento original). Não derruba o serviço: se o container estiver no ar com o banco da branch,
  ele continua servindo até ser recriado sem o override.
- **Efeito colateral:** apenas a remoção do arquivo gitignored. É o contraponto explícito do `use` e o
  caminho sancionado para a reversibilidade (critério 9).

#### `dbctl upgrade [-m mod1,mod2] [--all]`
- **Pré:** banco existe. Sem `-m`, usa `odoo.default_modules`; se este estiver vazio, erro pedindo
  `-m`. `--all` usa `-u all`.
- **Passos:** `strategy.upgrade(db, modules)` (stop → run efêmero com `--stop-after-init` → start).

#### `dbctl seed`
- **Pré:** banco existe; `seeds.path` configurado e existente (senão, aviso e saída 0).
- **Passos:** `run_seeds(db, branch)`.
- **Saída:** quais arquivos rodaram.

#### `dbctl list`
- **Saída:** tabela com nome, tamanho e marcação de qual é o da branch atual e qual está sendo servido.
- Lista **apenas** bancos com o `db_prefix`.

#### `dbctl drop [--yes] [--db NAME]`
- **Pré:** nome começa com o prefixo (recusa qualquer outro, inclusive via `--db`).
- **Passos:** confirmação interativa (a menos de `--yes`) → `stop()` se o banco estiver sendo servido →
  `drop_database` → `filestore.remove`.

#### `dbctl reset [--yes]`
- Equivale a `drop --yes` (se existir) seguido de `create`. Uma única confirmação no início.

#### `dbctl hook install [--force]`
- **Pré:** projeto é um repo git (sempre é, ver 3.2).
- **Passos:** `hook.install(cfg, force=...)`.
- **Saída:** caminho do hook instalado, ou erro explicando `--force` e mostrando a linha `exec` para
  colar manualmente, se já existir um `post-checkout` de terceiros.

#### `dbctl hook uninstall`
- **Passos:** `hook.uninstall(cfg)`.
- **Saída:** confirma a remoção, ou avisa que não havia hook nosso instalado. Nunca remove hook de
  terceiros.

#### `dbctl hook status`
- **Efeito colateral:** nenhum.
- **Saída:** caminho do hook, se está instalado, se é nosso (`ours`) e se está habilitado
  (`hooks.enabled`).

#### `dbctl hook post-checkout <prev> <new> <branch_flag>` (oculto, chamado pelo git)
- **Não é para uso manual** — é o comando que o script gerado por `hook install` invoca a cada
  `post-checkout`. Recebe os três argumentos padrão do hook do git.
- **Passos:** `hook.on_checkout(cfg, prev, new, branch_flag)`.
- **Saída:** as linhas retornadas, prefixadas com `dbctl:`, em stderr.
- **Sempre sai 0** — ver a regra de ouro em `commands/hook.py` (seção 6). Nenhum cenário de erro pode
  fazer o `git checkout` do usuário falhar.

---

## 8. Entregável 2 — projeto sandbox para validação

**Motivação:** o projeto real (`credsus`) está em uso ativo pelo autor durante o desenvolvimento do
tool. O implementador **não deve** usá-lo como cobaia. Em vez disso, cria um projeto Odoo mínimo e
descartável, que serve a dois propósitos: ambiente de teste seguro e **prova de que o tool é
agnóstico** — já que ele tem nomes de container, portas, caminhos e módulos completamente diferentes.

### 8.1 Estrutura

```
~/projects/dbctl-sandbox/
  docker-compose.yml
  odoo.conf
  .dbctl.toml
  .gitignore                     # /temp/, /docker-compose.override.yaml, .dbctl.toml
  README.md                      # como subir e como reproduzir o teste de drift
  addons/
    sandbox_demo/
      __init__.py
      __manifest__.py
      models/
        __init__.py
        sandbox_item.py          # model sandbox.item com um campo `name`
  temp/seeds/
    base.py                      # cria alguns sandbox.item, idempotente
    branches/                    # populado pelo teste
```

### 8.2 Requisitos do sandbox

- **Portas diferentes das do credsus**, para poder rodar em paralelo: Odoo em `8169`, Postgres em
  `5434`.
- **Nomes de container diferentes:** `dbctl-sandbox-db` e `dbctl-sandbox-web`.
- Imagem oficial do Odoo (`odoo:19`; se indisponível, `odoo:18` — registrar no README qual foi usada).
- `data_dir` próprio, em volume separado do credsus.
- Bootstrap do banco template documentado no README:
  `docker compose run --rm --no-deps web odoo -d sandbox_base -i base,sandbox_demo --stop-after-init`
- Repositório git inicializado, com três branches:
  - `main` — só o `sandbox_demo` original;
  - `feature-a` — adiciona o campo `field_a` ao `sandbox.item`;
  - `feature-b` — adiciona o campo `field_b` ao `sandbox.item`.

Essas duas branches são o que torna o **teste de drift** reproduzível e objetivo: `field_a` deve
existir no banco da `feature-a` e **não existir** no banco da `feature-b` nem no da `main`.

---

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
Executar todo o plano de validação (seção 10) contra o sandbox, corrigir o que falhar, e escrever o
`README.md` do tool com: instalação, injeção de um projeto novo, fluxo de trabalho diário, formato dos
seeds e resolução de problemas comuns.

**Ordem obrigatória:** E1 → E2 → E3 → E4 → E5. O sandbox (E4) pode ser antecipado se ajudar a testar
E2/E3, mas não deve atrasar a fundação.

---

## 10. Plano de validação

Executar **inteiramente no sandbox**. O projeto `credsus` só pode ser tocado para um teste final de
leitura (`dbctl status`), nunca para criar, dropar ou reiniciar serviços.

### 10.1 Descoberta e config

| # | Ação | Resultado esperado |
|---|---|---|
| V1 | `dbctl status` de uma subpasta profunda do sandbox | Encontra a raiz pelo `.dbctl.toml` |
| V2 | `dbctl status` a partir de `~` | Falha com `ProjectNotFoundError`, exit 2, mensagem ensinando a injetar |
| V3 | Remover uma chave obrigatória do `.dbctl.toml` | Exit 3, mensagem nomeando a chave e o arquivo |
| V4 | `strategy.kind = "banana"` | Exit 3, mensagem listando os valores válidos |
| V5 | `DBCTL_POSTGRES_PASSWORD=x dbctl status` com senha removida do arquivo | Funciona (env var tem precedência) |
| V6 | `git checkout --detach` e `dbctl status` | Exit 4, mensagem sobre HEAD destacado |

### 10.1.1 Localização do `.dbctl.toml` (seção 5.0)

| # | Ação | Resultado esperado |
|---|---|---|
| C1 | `.dbctl.toml` na raiz, `dbctl status` de uma subpasta | Igual ao comportamento de sempre; `config:` mostra o caminho na raiz |
| C2 | Mover o config para `temp/.dbctl.toml`, rodar `dbctl status` da raiz | Encontrado pela busca descendente; `project:` continua sendo o topo do repo |
| C3 | Com o config em `temp/`, `seeds.path = "temp/seeds"` | Resolvido a partir da raiz do repo — mesma pasta de sempre, não relativa a `temp/` |
| C4 | Dois `.dbctl.toml` no repo (raiz e `temp/`) | `ConfigError` listando os dois caminhos e sugerindo `--config` |
| C5 | `dbctl --config temp/.dbctl.toml status` no cenário de C4 | Funciona, sem ambiguidade |
| C6 | `DBCTL_CONFIG=/abs/temp/.dbctl.toml dbctl status` | Idem C5 |
| C7 | `--config` apontando para um arquivo inexistente | `ConfigError` claro, exit 3 |
| C8 | Rodar `dbctl status` fora de qualquer repositório git | `GitError`, exit 4 (não `ProjectNotFoundError`) |
| C9 | Config numa pasta ignorada pelo git, `git status` do projeto | Working tree limpo — o arquivo de credenciais não aparece |

### 10.2 Naming

| # | Ação | Resultado esperado |
|---|---|---|
| V7 | Nome de banco para uma branch de 80 caracteres | ≤ 63 chars, começa com o prefixo |
| V8 | Rodar `dbctl status` duas vezes | Mesmo nome de banco (determinismo) |
| V9 | Duas branches com os mesmos 50 primeiros caracteres | Nomes de banco diferentes (digest difere) |

### 10.3 Ciclo de vida

| # | Ação | Resultado esperado |
|---|---|---|
| V10 | `dbctl create` na `feature-a` | Banco aparece em `dbctl list` com tamanho > 0 |
| V11 | `docker exec dbctl-sandbox-web ls <data_dir>/filestore` | Diretório do novo banco existe |
| V12 | `dbctl create` de novo | Exit 6, erro claro sugerindo `reset` |
| V13 | `dbctl use` e abrir `localhost:8169` | Sobe direto no banco, **sem** tela de seleção |
| V14 | Inspecionar o `docker-compose.override.yaml` gerado | Contém o cabeçalho `GENERATED BY dbctl`, o `-d` e o `--db-filter` corretos |
| V15 | `dbctl upgrade -m sandbox_demo` | Termina sem erro; o override final **não** contém `-u` |
| V16 | `dbctl list` | Só bancos do prefixo; `sandbox_base` e `postgres` **não** aparecem |
| V17 | `dbctl drop --yes` | Banco e filestore somem; `sandbox_base` intacto |
| V18 | `dbctl drop --db sandbox_base` | **Recusa**, exit 6, por não ter o prefixo |
| V19 | `dbctl reset --yes` | Banco volta ao estado do template |

### 10.4 Isolamento entre branches — **o teste que valida a razão de existir do tool**

| # | Ação | Resultado esperado |
|---|---|---|
| V20 | Na `feature-a`: `dbctl create --use && dbctl upgrade -m sandbox_demo` | Sobe sem erro |
| V21 | Confirmar `field_a` no banco da `feature-a` via `information_schema.columns` | Coluna **existe** |
| V22 | `git checkout feature-b && dbctl create --use && dbctl upgrade -m sandbox_demo` | Sobe **sem erro** |
| V23 | Conferir colunas no banco da `feature-b` | `field_b` existe; **`field_a` não existe** |
| V24 | `git checkout feature-a && dbctl use` | Banco anterior intacto, `field_a` de volta, sem reprocessar |

### 10.5 Seeds

| # | Ação | Resultado esperado |
|---|---|---|
| V25 | `dbctl seed` com só o `base.py` | Roda, reporta o arquivo executado |
| V26 | `dbctl seed` de novo | Contagem de registros **inalterada** (idempotência) |
| V27 | Criar `branches/<slug da feature-a>.py` e rodar `dbctl seed` | Roda base **e** o da branch, nessa ordem |
| V28 | `dbctl seed` na `feature-b` (sem arquivo próprio) | Roda só o base, sem erro |
| V29 | Seed com erro proposital (ex.: `1/0`) | Exit 7, erro do Odoo visível, sem commit parcial |
| V30 | Seed tentando `import dbctl` | Falha — confirma que a fronteira está correta e documentada |

### 10.6 Sanitize e segurança

| # | Ação | Resultado esperado |
|---|---|---|
| V31 | Comparar `database.uuid` do template e do clone | **Diferentes** |
| V32 | Conferir `ir.mail_server` no clone | Todos inativos |
| V33 | Conferir `ir.cron` no clone | **Ativos** (decisão deliberada) |
| V34 | `dbctl drop` sem `--yes`, respondendo "não" | Exit 130, nada removido |

### 10.6.1 Hook `post-checkout`

| # | Ação | Resultado esperado |
|---|---|---|
| H1 | `dbctl hook install` | `.git/hooks/post-checkout` executável, com o marcador `GENERATED BY dbctl` |
| H2 | `dbctl hook status` | `installed: yes (dbctl)`, `enabled: yes` |
| H3 | `create --use` na `feature-a`; depois `git checkout feature-b` (banco já existente) | Saída `dbctl: serving <db da feature-b>`; override passa a apontar para o banco novo |
| H4 | `git checkout -b branch-nova` | Aviso sugerindo `dbctl create --use`; exit 0; checkout concluído |
| H5 | `[hooks] enabled = false`, depois `git checkout feature-a` | Nenhuma saída do dbctl; override permanece intacto |
| H6 | `DBCTL_HOOKS_ENABLED=0 git checkout feature-b` | Idem H5 |
| H7 | `git checkout -- <arquivo>` (sem trocar de branch) | Hook não faz nada (branch_flag `0`) |
| H8 | `git checkout --detach` | Aviso sobre HEAD destacado; **exit 0** |
| H9 | Parar os containers e rodar `git checkout feature-a` | `dbctl: hook failed: ...`; checkout ainda assim conclui |
| H10 | Criar um `post-checkout` próprio (sem o marcador), rodar `dbctl hook install` | Erro explicando `--force` e mostrando a linha `exec` para colar manualmente |
| H11 | `dbctl hook install --force` no cenário de H10 | `post-checkout.bak` criado com o conteúdo anterior; hook do dbctl instalado |
| H12 | `dbctl hook uninstall` | Arquivo removido; rodar de novo → relata que não havia hook nosso |
| H13 | `DBCTL_DRY_RUN=1 dbctl hook install` | Descreve a ação pretendida, não escreve nada em disco |

### 10.7 Agnosticismo — validação automatizável

| # | Ação | Resultado esperado |
|---|---|---|
| V35 | `grep -riE "credsus\|greencompras\|foo-user\|green-compras\|faturamento" ~/projects/dbctl/dbctl/` | **Zero ocorrências** |
| V36 | Rodar todo o ciclo no sandbox (containers, portas, caminhos e módulos diferentes) | Funciona sem nenhuma alteração no código do tool |
| V37 | No `credsus`, apenas `dbctl status` | Detecta o projeto e mostra o banco alvo, **sem efeito colateral** |
| V38 | `dbctl use` seguido de `dbctl unuse` | Override removido; `docker compose config` do projeto volta a mostrar o command base |
| V39 | `dbctl create --use` numa máquina sem override prévio | Seeds rodam com o `-v` explícito (sem depender do override) e o banco sobe sanitizado |

---

## 11. Critérios de avaliação

Usados para validar o trabalho entregue. Um item não atendido é uma correção obrigatória.

### Bloqueantes (reprovam a entrega)
1. **Isolamento comprovado:** V20–V24 passam integralmente.
2. **Nenhum dado perdido:** nenhum comando é capaz de dropar banco sem o prefixo (V18) nem tocar no
   template. `drop_database` valida o prefixo internamente, além da checagem na camada de comando.
3. **Agnosticismo:** V35 retorna zero ocorrências e V36 passa.
4. **Seeds desacoplados:** seeds não importam o `dbctl` e funcionam como arquivos soltos (V30).
5. **Sem edição de arquivo versionado do projeto injetado:** o tool só escreve o `override_file`
   (gitignored) e o `post-checkout` (não versionado — vive em `.git/hooks/` ou no `core.hooksPath`
   customizado). Em particular, **jamais** edita `config/odoo.conf` ou `docker-compose.yml`.
6. **Erros tratados:** todo erro esperado sai com mensagem legível e exit code da tabela de `errors.py`
   — nunca traceback cru (V2, V3, V4, V6, V12).

### Qualidade (avaliados, mas não bloqueiam)
7. **Fronteiras de módulo:** `cli.py` sem regra de negócio; nenhum módulo além de `docker.py` chama
   `subprocess`; camadas de baixo não importam de cima.
8. **Idempotência:** `seed` repetido não duplica dados; `use` repetido é inofensivo.
9. **Reversibilidade:** apagar o `override_file` devolve o projeto ao comportamento original.
10. **Legibilidade do output:** `status` e `list` são compreensíveis sem consultar a documentação.
11. **README suficiente:** um colega consegue instalar, injetar um projeto e rodar o fluxo diário só
    com o README, sem ler o código.
12. **Sem dependências além do Typer:** biblioteca padrão para o resto (`tomllib` já está no Python
    ≥ 3.11).

### Verificação rápida para o revisor
```
# agnosticismo
grep -riE "credsus|greencompras|foo-user|green-compras" ~/projects/dbctl/dbctl/ ; echo "esperado: vazio"

# subprocess concentrado
grep -rl "subprocess" ~/projects/dbctl/dbctl/ ; echo "esperado: apenas docker.py"

# dependências
grep -A5 "dependencies" ~/projects/dbctl/pyproject.toml ; echo "esperado: apenas typer"
```

---

## 12. Fora de escopo (não implementar)

- Git worktrees, ou rodar duas branches simultaneamente.
- Drivers adicionais de estratégia além de `compose-override` e do escape hatch `custom`.
- Migração/backfill de dados entre bancos de branches diferentes.
- Interface web, TUI ou empacotamento para PyPI.
- Suporte a Postgres fora de container.
- Testes automatizados do tool (a validação do MVP é o plano manual da seção 10) — se sobrar tempo,
  testes unitários de `naming.py` e `config.py` são o melhor investimento, por serem lógica pura.
