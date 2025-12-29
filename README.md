# Crawler — Leilões DETRAN-MG (ético)

Crawler em Python 3.11+ para coletar **somente dados públicos** de leilões e lotes no site:
- Home: https://leilao.detran.mg.gov.br/

## Princípios de conformidade (importante)
- Respeita `robots.txt` e aplica **rate limit + backoff**.
- **Não** contorna login/captcha/paywall/anti-bot. Se houver "Login obrigatório", marca `requires_login=true` e segue adiante.
- Prioriza **endpoints JSON** quando observados (via Playwright Network); HTML é fallback.

## Arquitetura / Estratégia

- **Camada de descoberta (home)**: usa Playwright para renderizar a home e coletar os links de “Detalhes”. Se falhar (site fora, JS bloqueado, etc.), cai para `requests + BeautifulSoup`.
- **Camada de coleta (por leilão)**:
   - **JSON-first (preferido)**: enquanto abre a página do leilão, registra respostas `application/json` observadas no Network. Se alguma dessas respostas contiver uma lista de lotes, o crawler tenta paginar o **mesmo endpoint** de forma legítima (sem burlar login). Se retornar `401/403`, considera “requer login” e cai para HTML.
   - **HTML fallback**: navega a paginação por controles visuais (links/botões “2”, “3”, “Próx”), extraindo cards via parser defensivo.
- **Checkpoint/resume**: salva páginas já coletadas em `.checkpoint/state.json` dentro do `--output-dir`. Reexecutar o comando retoma de onde parou (por leilão/página).
- **Rate limit + backoff**:
   - Rate limit por intervalo (ex.: `--rate-limit 0.5` = ~1 req a cada 2s).
   - Retries exponenciais com jitter para erros transitórios.
- **Auditoria/Logs**:
   - `crawler.log` com eventos.
   - `network.jsonl` com metadados de endpoints JSON observados.
   - `raw/<auction_id>/api_endpoints.jsonl` com metadados por leilão (sem persistir payloads JSON em disco por padrão).

## Instalação

### 1) Criar venv (Windows PowerShell)
```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -U pip
pip install -r requirements.txt

# Instalar o pacote (src-layout) para habilitar o comando CLI
pip install -e .
```

### 2) Instalar browsers do Playwright
```powershell
python -m playwright install
```

## Uso (CLI)

### Dry-run (não baixa tudo)
Lista leilões e no máximo 2 páginas de lotes por leilão:
```powershell
detran-leilao-crawler crawl --dry-run --output-dir .\out

# Alternativa sem instalar entrypoint:
python -m detran_leilao_crawler.cli crawl --dry-run --output-dir .\out
```

### Crawl completo
```powershell
detran-leilao-crawler crawl --headless --rate-limit 0.5 --output-dir .\out
```

### Filtrar e exportar
```powershell
detran-leilao-crawler filter --input-dir .\out --filters .\configs\filters.example.yaml --output-dir .\out_filtered
detran-leilao-crawler export --input-dir .\out_filtered --output-dir .\exports --sqlite
```

## Como detectar API JSON (manual)
1. Abra o site no navegador.
2. Pressione F12 → aba **Network**.
3. Filtre por **Fetch/XHR**.
4. Abra um leilão e navegue páginas de lotes.
5. Procure requisições que retornem `application/json` e observe:
   - URL do endpoint
   - query params (page, size, auctionId, etc.)
   - payload (se POST)

Este projeto também tenta **registrar** potenciais endpoints via Playwright (sem contornar proteções): veja logs `network.jsonl` em `--output-dir`.

## Saídas
- JSONL bruto por leilão/página (checkpoint-friendly)
- CSV/JSON consolidados
- SQLite opcional (`auctions`, `lots`, `images`)

## Testes
```powershell
pytest
```
