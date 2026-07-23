"""
Monitor SST — Segurança e Saúde no Trabalho
Fonte: API pública do Querido Diário
Filtra apenas publicações FEDERAIS que alterem NR, portarias SST, etc.
"""

import json
import os
import re
import time
import hashlib
import urllib.request
import urllib.parse
from datetime import datetime, timezone, timedelta

BRASILIA = timezone(timedelta(hours=-3))
def now_brasilia():
    return datetime.now(BRASILIA)

DATA_DIR   = os.path.join(os.path.dirname(__file__), '..', 'data')
STATE_FILE = os.path.join(DATA_DIR, 'state.json')
os.makedirs(DATA_DIR, exist_ok=True)

# ─── API do Querido Diário ───────────────────────────────────────────────────
QD_API = "https://api.queridodiario.ok.org.br/gazettes"

# ─── Termos de busca — específicos para alterações de NR ─────────────────────
# Cada termo é buscado individualmente no DOU federal
SEARCH_TERMS = [
    '"norma regulamentadora"',           # busca exata
    '"NR-1" OR "NR-2" OR "NR-3" OR "NR-4" OR "NR-5"',
    '"NR-6" OR "NR-7" OR "NR-8" OR "NR-9" OR "NR-10"',
    '"NR-11" OR "NR-12" OR "NR-13" OR "NR-14" OR "NR-15"',
    '"NR-16" OR "NR-17" OR "NR-18" OR "NR-19" OR "NR-20"',
    '"NR-21" OR "NR-22" OR "NR-23" OR "NR-24" OR "NR-25"',
    '"NR-26" OR "NR-27" OR "NR-28" OR "NR-29" OR "NR-30"',
    '"NR-31" OR "NR-32" OR "NR-33" OR "NR-34" OR "NR-35"',
    '"NR-36" OR "NR-37" OR "NR-38"',
    '"portaria" "segurança saúde trabalho"',
    '"instrução normativa" "segurança trabalho"',
]

# ─── Palavras que DEVEM estar no trecho para ser relevante ───────────────────
MUST_HAVE = [
    "norma regulamentadora",
    "nr-1", "nr-2", "nr-3", "nr-4", "nr-5", "nr-6", "nr-7",
    "nr-8", "nr-9", "nr-10", "nr-11", "nr-12", "nr-13", "nr-14",
    "nr-15", "nr-16", "nr-17", "nr-18", "nr-19", "nr-20", "nr-21",
    "nr-22", "nr-23", "nr-24", "nr-25", "nr-26", "nr-27", "nr-28",
    "nr-29", "nr-30", "nr-31", "nr-32", "nr-33", "nr-34", "nr-35",
    "nr-36", "nr-37", "nr-38",
    "portaria sst", "portaria mte", "portaria mtp", "portaria sefit",
    "portaria sit", "portaria seprt",
    "instrução normativa sst",
]

# ─── Palavras que DESCARTAM o trecho automaticamente ─────────────────────────
DISCARD = [
    "concurso público", "licitação", "pregão eletrônico",
    "aposentadoria", "pensão por morte", "benefício previdenciário",
    "imposto de renda", "receita federal", "certidão negativa",
    "transferência de servidor", "exoneração", "nomeação",
    "município de", "prefeitura", "câmara municipal",
    "tribunal", "judiciário", "ministério público",
    "edição nº", "controladoria geral do município",
]

# ─── IDs dos territórios FEDERAIS no Querido Diário ─────────────────────────
# Deixar vazio para buscar em âmbito federal (DOU)
# O QD usa territory_ids vazio = federal
FEDERAL_SOURCES = [
    # Fontes conhecidas do DOU no Querido Diário
    # territory_ids vazio = retorna gazettes federais
]

def is_relevant(excerpt):
    """Verifica se o trecho é de fato relevante para SST federal."""
    t = excerpt.lower()
    # Deve ter pelo menos uma palavra obrigatória
    has_must = any(k in t for k in MUST_HAVE)
    # Não pode ter palavras de descarte
    has_discard = any(k in t for k in DISCARD)
    return has_must and not has_discard

def fetch_json(url, timeout=30):
    headers = {
        'User-Agent': 'Monitor-SST/2.0 (monitoramento NR federal)',
        'Accept': 'application/json',
    }
    req = urllib.request.Request(url, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return json.loads(resp.read().decode('utf-8'))
    except Exception as e:
        print(f"    [ERRO: {type(e).__name__}: {e}]")
        return None

def search_dou(term, since_date, until_date):
    """Busca no DOU federal via Querido Diário."""
    params = urllib.parse.urlencode({
        'querystring':        term,
        'published_since':    since_date,
        'published_until':    until_date,
        'excerpt_size':       800,
        'number_of_excerpts': 2,
        'size':               5,
        'sort_by':            'relevance',
        # Filtra apenas diários de âmbito federal
        'is_extra_edition':   'false',
    })
    url = f"{QD_API}?{params}"
    print(f"    Buscando: {term[:60]}...", end=" ", flush=True)
    data = fetch_json(url)
    if not data:
        print("falha.")
        return []

    gazettes = data.get('gazettes', [])
    if not gazettes:
        print("sem resultados.")
        return []

    results = []
    seen = set()

    for g in gazettes:
        # Filtra apenas fontes federais — o DOU tem territory_id específico
        # Verifica se a URL do arquivo é do DOU federal (in.gov.br)
        file_url = g.get('url', '')
        if not file_url:
            continue

        # Aceita apenas arquivos do DOU federal
        is_federal = (
            'in.gov.br' in file_url or
            'queridodiario' in file_url
        )
        if not is_federal:
            continue

        date   = g.get('date', '')
        excerpts = g.get('excerpts', [])

        for excerpt in excerpts:
            if not is_relevant(excerpt):
                continue

            pub_id = hashlib.md5(excerpt[:120].encode('utf-8')).hexdigest()[:16]
            if pub_id in seen:
                continue
            seen.add(pub_id)

            titulo = re.sub(r'\s+', ' ', excerpt.strip())[:250]

            results.append({
                'id':       pub_id,
                'titulo':   titulo,
                'link':     file_url,
                'fonte':    'Diário Oficial da União',
                'busca':    term,
                'data':     date,
                'data_fmt': datetime.strptime(date, '%Y-%m-%d').strftime('%d/%m/%Y') if date else '',
                'tipo':     'DOU',
            })

    count = len(results)
    print(f"{count} publicação(ões) relevante(s).")
    return results

def load_state():
    if os.path.exists(STATE_FILE):
        with open(STATE_FILE, 'r', encoding='utf-8') as f:
            return json.load(f)
    return {
        "last_check": None, "status": "Monitorando", "total_nrs": 38,
        "hashes": {}, "publicacoes_recentes": [], "recent_changes": [], "history": []
    }

def save_state(state):
    with open(STATE_FILE, 'w', encoding='utf-8') as f:
        json.dump(state, f, ensure_ascii=False, indent=2)

def run_check():
    print(f"\n{'='*65}")
    print(f"  Monitor SST — DOU Federal")
    print(f"  {now_brasilia().strftime('%d/%m/%Y %H:%M')} (Brasília)")
    print(f"{'='*65}\n")

    state     = load_state()
    today     = now_brasilia()
    today_str = today.strftime('%Y-%m-%d')
    today_fmt = today.strftime('%d/%m/%Y')
    now_str   = today.strftime('%d/%m/%Y %H:%M')

    # Busca apenas hoje — evita acumular publicações antigas
    since = today_str
    until = today_str

    new_publications = []
    # IDs já registrados (histórico + recentes)
    seen_ids = {p.get('id') for p in state.get('history', [])}
    seen_ids |= {p.get('id') for p in state.get('publicacoes_recentes', [])}

    print("[ DOU FEDERAL — Querido Diário API ]\n")

    for term in SEARCH_TERMS:
        results = search_dou(term, since, until)
        for r in results:
            if r['id'] not in seen_ids:
                seen_ids.add(r['id'])
                new_publications.append(r)
        time.sleep(2)  # respeita limite de 60 req/min

    # ── Atualiza estado ──────────────────────────────────────────────────────
    state["last_check"] = now_str
    state["total_nrs"]  = 38
    state["status"]     = "Nova Publicação" if new_publications else "Monitorando"

    if new_publications:
        state.setdefault("publicacoes_recentes", []).extend(new_publications)
        state.setdefault("history", []).extend(new_publications)
        state["recent_changes"] = state["publicacoes_recentes"]

    # Remove recentes com mais de 7 dias
    cutoff = today - timedelta(days=7)
    state["publicacoes_recentes"] = [
        p for p in state.get("publicacoes_recentes", [])
        if p.get("data") and
        datetime.strptime(p["data"], '%Y-%m-%d').replace(tzinfo=BRASILIA) >= cutoff
    ]
    state["recent_changes"] = state["publicacoes_recentes"]

    save_state(state)

    print(f"\n{'─'*65}")
    print(f"  Status           : {state['status']}")
    print(f"  Horário          : {state['last_check']}")
    print(f"  Novas publicações: {len(new_publications)}")
    print(f"{'─'*65}\n")

if __name__ == '__main__':
    run_check()
