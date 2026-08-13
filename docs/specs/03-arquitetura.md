<!-- docs/specs/03-arquitetura.md — parte do SPEC do dbctl, seções 4.
     Índice e ordem de leitura: docs/specs/README.md. -->

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
ignorada pelo git — ver [configuração](04-configuracao.md) para a ordem de descoberta). Em qualquer um dos dois casos, os caminhos
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
