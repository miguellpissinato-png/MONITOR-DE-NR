"""
Monitor SST — Segurança e Saúde no Trabalho
Fonte: API pública do Querido Diário (api.queridodiario.ok.org.br)
Sem cadastro, sem bloqueio, sem custo.
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
# Endpoint para busca nos diários federais (DOU)
# territory_ids='' = busca em âmbito federal
QD_API = "https://api.queridodiario.ok.org.br/gazettes"

# ─── Termos de busca focados em SST ─────────────────────────────────────────
SEARCH_TERMS = [
    "norma regulamentadora",
    "segurança saúde trabalho portaria",
    "NR-1 NR-2 NR-3 NR-4 NR-5",
    "NR-6 NR-7 NR-8 NR-9 NR-10",
    "NR-11 NR-12 NR-13 NR-14 NR-15",
    "NR-16 NR-17 NR-18 NR-19 NR-20",
    "NR-21 NR-22 NR-23 NR-24 NR-25",
    "NR-26 NR-27 NR-28 NR-29 NR-30",
    "NR-31 NR-32 NR-33 NR-34 NR-35",
    "NR-36 NR-37 NR-38",
    "equipamento proteção individual EPI portaria",
    "CIPA comissão interna prevenção acidentes",
    "insalubridade periculosidade portaria",
    "espaço confinado trabalho altura ergonomia",
    "PCMSO PGR PPRA laudo técnico trabalho",
]

# ─── Filtros de relevância ───────────────────────────────────────────────────
INCLUDE = [
    "norma regulamentadora", "nr-", " nr ", "portaria", "instrução normativa",
    "segurança do trabalho", "saúde no trabalho", "segurança e saúde",
    "insalubridade", "periculosidade", "epi", "equipamento de proteção",
    "acidente de trabalho", "medicina do trabalho", "cipa",
    "espaço confinado", "trabalho em altura", "ergonomia",
    "pcmso", "pgr", "ppra", "ltcat", "laudo", "agente nocivo",
    "caldeira", "vaso de pressão", "explosivo", "inflamável",
    "mineração", "construção civil", "abate processamento carnes",
]

EXCLUDE = [
    "concurso público", "licitação", "pregão", "aposentadoria",
    "pensão previdenciária", "imposto de renda", "receita federal",
    "certidão", "transferência", "exoneração", "nomeação",
]

def is_relevant(text):
    t = text.lower()
    return any(k in t for k in INCLUDE) and not any(k in t for k in EXCLUDE)

def fetch_json(url, timeout=30):
    headers = {
        'User-Agent': 'Monitor-SST/2.0 (github.com; monitoramento NR)',
        'Accept': 'application/json',
    }
    req = urllib.request.Request(url, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return json.loads(resp.read().decode('utf-8'))
    except Exception as e:
        print(f"    [ERRO: {type(e).__name__}: {e}]")
        return None

def search_querido_diario(term, since_date, until_date):
    """Busca no Querido Diário por termo no período especificado."""
    params = urllib.parse.urlencode({
        'querystring': term,
        'published_since': since_date,   # YYYY-MM-DD
        'published_until': until_date,   # YYYY-MM-DD
        'excerpt_size': 500,
        'number_of_excerpts': 3,
        'size': 10,
        'sort_by': 'relevance',
    })
    url = f"{QD_API}?{params}"
    print(f"    Buscando: \"{term[:50]}\"...", end=" ", flush=True)
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
        excerpts = g.get('excerpts', [])
        date = g.get('date', '')
        url_pdf = g.get('url', '')
        edition = g.get('edition', {})

        for excerpt in excerpts:
            if not is_relevant(excerpt):
                continue
            # Gera ID único para evitar duplicatas
            pub_id = hashlib.md5(excerpt[:120].encode('utf-8')).hexdigest()[:16]
            if pub_id in seen:
                continue
            seen.add(pub_id)

            # Formata título a partir do trecho
            titulo = excerpt.strip()[:200].replace('\n', ' ')
            titulo = re.sub(r'\s+', ' ', titulo)

            results.append({
                'id':       pub_id,
                'titulo':   titulo,
                'link':     url_pdf or f"https://queridodiario.ok.org.br/",
                'fonte':    'Diário Oficial da União via Querido Diário',
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
    print(f"  Monitor SST / Querido Diário")
    print(f"  {now_brasilia().strftime('%d/%m/%Y %H:%M')} (Brasília)")
    print(f"{'='*65}\n")

    state    = load_state()
    today    = now_brasilia()
    today_str = today.strftime('%Y-%m-%d')
    today_fmt = today.strftime('%d/%m/%Y')
    now_str   = today.strftime('%d/%m/%Y %H:%M')

    # Busca publicações dos últimos 2 dias para não perder nada
    since = (today - timedelta(days=2)).strftime('%Y-%m-%d')

    new_publications = []
    seen_ids = {p.get('id') for p in state.get('publicacoes_recentes', [])}
    seen_ids |= {p.get('id') for p in state.get('history', [])}

    print("[ DIÁRIO OFICIAL DA UNIÃO — via Querido Diário API ]\n")

    for term in SEARCH_TERMS:
        results = search_querido_diario(term, since, today_str)
        for r in results:
            if r['id'] not in seen_ids:
                seen_ids.add(r['id'])
                new_publications.append(r)
        time.sleep(1.5)  # respeita o limite de 60 req/min

    # ── Atualiza estado ──────────────────────────────────────────────────────
    state["last_check"] = now_str
    state["total_nrs"]  = 38
    state["status"] = "Nova Publicação" if new_publications else "Monitorando"

    if new_publications:
        state.setdefault("publicacoes_recentes", []).extend(new_publications)
        state.setdefault("history", []).extend(new_publications)
        state["recent_changes"] = state["publicacoes_recentes"]

    # Remove recentes com mais de 7 dias
    cutoff = today - timedelta(days=7)
    state["publicacoes_recentes"] = [
        p for p in state.get("publicacoes_recentes", [])
        if datetime.strptime(p["data"], '%Y-%m-%d').replace(tzinfo=BRASILIA) >= cutoff
        if p.get("data")
    ]
    state["recent_changes"] = state["publicacoes_recentes"]

    save_state(state)

    print(f"\n{'─'*65}")
    print(f"  Status         : {state['status']}")
    print(f"  Horário        : {state['last_check']}")
    print(f"  Novas publicações: {len(new_publications)}")
    print(f"{'─'*65}\n")

if __name__ == '__main__':
    run_check()
