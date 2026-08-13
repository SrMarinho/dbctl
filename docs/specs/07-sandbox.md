<!-- docs/specs/07-sandbox.md — parte do SPEC do dbctl, seções 8.
     Índice e ordem de leitura: docs/specs/README.md. -->

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
