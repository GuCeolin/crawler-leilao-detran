# Como rodar o crawler (DETRAN-MG Leilões)

Este guia mostra comandos prontos para:
- Validar rapidamente (`dry-run`)
- Rodar o crawl completo (todos leilões + todas páginas)
- Retomar do ponto onde parou (checkpoint)
- Aplicar filtros e exportar (CSV/JSON/SQLite)

> Observação: este projeto foi feito para ser **ético** e resiliente. Não tenta burlar login/captcha. Se o site exigir autenticação, o crawler marca `requires_login` e segue o que for público.

---

## 1) Preparação do ambiente (Windows / PowerShell)

No diretório do projeto:

```powershell
cd C:\GitHub\crawler-leilao-detran
```

Se você ainda não instalou dependências:

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r .\requirements.txt
pip install -e .
```

### Playwright (necessário para o modo recomendado)

O crawler usa Playwright como primeira opção. Depois de instalar as dependências, instale os browsers do Playwright:

```powershell
python -m playwright install
```

---

## 2) Comando rápido (dry-run)

Útil para validar que está funcionando, sem “martelar” o site e sem coletar tudo:

```powershell
detran-leilao-crawler crawl --dry-run --max-auctions 1 --rate-limit 0.5 --output-dir .\out --headless
```

O `dry-run` limita páginas por design, então é normal ver poucos lotes (ex.: 16 se forem 2 páginas × 8 lotes).

---

## 3) Crawl completo (todos os leilões e todas as páginas)

### Recomendado (headless, com rate-limit)

```powershell
detran-leilao-crawler crawl --headless --rate-limit 0.5 --output-dir .\out
```

- **Sem** `--dry-run`
- **Sem** `--max-auctions`
- **Sem** `--max-pages`

Isso permite percorrer **todos os leilões** descobertos e **todas as páginas** de lotes de cada leilão (até o fim da paginação).

### Mais conservador (mais lento)

```powershell
detran-leilao-crawler crawl --headless --rate-limit 0.2 --output-dir .\out
```

---

## 4) Retomar (checkpoint/resume)

O crawler grava checkpoint em:

- `.\out\.checkpoint\state.json`

Se você interromper (Ctrl+C, queda de rede, etc.), basta rodar o mesmo comando novamente:

```powershell
detran-leilao-crawler crawl --headless --rate-limit 0.5 --output-dir .\out
```

Ele deve continuar a partir do progresso salvo e evitar duplicações no `raw/.../lots.jsonl`.

---

## 5) Onde ficam os arquivos gerados

Após o crawl, você deve ver algo como:

- `.\out\auctions.json` (lista de leilões descobertos + metadados best-effort)
- `.\out\lots.json` (lotes consolidados)
- `.\out\crawler.log` (log de execução)
- `.\out\network.jsonl` (telemetria/auditoria de chamadas observadas; metadados)
- `.\out\raw\<auction_id>\lots.jsonl` (lotes “raw” por leilão/página)
- `.\out\raw\<auction_id>\api_endpoints.jsonl` (metadados de endpoints JSON observados)

---

## 6) Aplicar filtros (pós-processamento)

Use um arquivo YAML/JSON de filtros (exemplo em `configs/filters.example.yaml`).

```powershell
detran-leilao-crawler filter --input-dir .\out --filters .\configs\filters.example.yaml --output-dir .\out_filtered
```

Isso gera um diretório filtrado e copia também o `auctions.json` para manter contexto do crawl.

---

## 7) Exportar (CSV/JSON e opcionalmente SQLite)

### Export simples

```powershell
detran-leilao-crawler export --input-dir .\out_filtered --output-dir .\exports
```

### Export + SQLite

```powershell
detran-leilao-crawler export --input-dir .\out_filtered --output-dir .\exports --sqlite
```

---

## 8) Dicas de diagnóstico

Se algo não bater (ex.: “parou” numa página, mudou o HTML, etc.), olhe:

- `.\out\crawler.log`
- `.\out\network.jsonl`
- `.\out\raw\<auction_id>\api_endpoints.jsonl`

Esses arquivos ajudam a entender se o site mudou estrutura, se houve 401/403, ou se a paginação/seletores precisam ajuste.
