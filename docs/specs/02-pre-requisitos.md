<!-- docs/specs/02-pre-requisitos.md — parte do SPEC do dbctl, seções 3.
     Índice e ordem de leitura: docs/specs/README.md. -->

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
   do config, ver [configuração](04-configuracao.md)).
2. Rodar Postgres e Odoo em containers Docker, com nomes de container estáveis.
3. Ter um `docker-compose.yml` com um serviço de Odoo identificável.
4. Ter um banco template já existente e funcional.
5. Ter um `.dbctl.toml` em algum lugar do repositório — não precisa ser a raiz (ver [configuração](04-configuracao.md)).

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
