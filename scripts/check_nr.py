"""
Monitor de Segurança do Trabalho — Diário Oficial da União
Busca diariamente publicações relacionadas a NR, portarias SST,
instruções normativas e outros atos que impactem a segurança do trabalho.
"""

import json
import os
import re
import time
import hashlib
import urllib.request
import urllib.parse
import urllib.error
from datetime import datetime, timezone, timedelta
from html.parser import HTMLParser

# ─── Fuso horário de Brasília ────────────────────────────────────────────────
BRASILIA = timezone(timedelta(hours=-3))
def now_brasilia():
    return datetime.now(BRASILIA)

# ─── Caminhos ────────────────────────────────────────────────────────────────
DATA_DIR   = os.path.join(os.path.dirname(__file__), '..', 'data')
STATE_FILE = os.path.join(DATA_DIR, 'state.json')
os.makedirs(DATA_DIR, exist_ok=True)

# ─── Termos de busca no DOU ──────────────────────────────────────────────────
# Cada termo gera uma busca independente no DOU
SEARCH_TERMS = [
    "norma regulamentadora",
    "segurança saúde trabalho portaria",
    "NR-1 NR-2 NR-3 NR-4 NR-5 NR-6 NR-7",
    "NR-8 NR-9 NR-10 NR-11 NR-12 NR-13",
    "NR-14 NR-15 NR-16 NR-17 NR-18 NR-19",
    "NR-20 NR-21 NR-22 NR-23 NR-24 NR-25",
    "NR-26 NR-27 NR-28 NR-29 NR-30 NR-31",
    "NR-32 NR-33 NR-34 NR-35 NR-36 NR-37 NR-38",
    "equipamento proteção individual EPI portaria",
    "CIPA acidente trabalho portaria",
    "insalubridade periculosidade portaria",
    "espaço confinado portaria",
    "trabalho altura portaria",
    "PCMSO PPRA PGR portaria",
]

# ─── URLs das fontes monitoradas ─────────────────────────────────────────────
DOU_SEARCH_BASE = "https://www.in.gov.br/consulta/-/buscar/dou"
MTE_PORTARIAS   = "https://www.gov.br/trabalho-e-emprego/pt-br/acesso-a-informacao/participacao-social/conselhos-e-orgaos-colegiados/comissao-tripartite-partitaria-permanente/normas-regulamentadora/portarias-sst"
MTE_INDEX       = "https://www.gov.br/trabalho-e-emprego/pt-br/acesso-a-informacao/participacao-social/conselhos-e-orgaos-colegiados/comissao-tripartite-partitaria-permanente/normas-regulamentadora/normas-regulamentadoras-vigentes"

# ─── Palavras-chave para filtrar resultados relevantes ───────────────────────
KEYWORDS_INCLUDE = [
    "norma regulamentadora", "nr-", " nr ", "portaria",
    "segurança do trabalho", "saúde no trabalho", "segurança e saúde",
    "insalubridade", "periculosidade", "epi", "equipamento de proteção",
    "acidente de trabalho", "medicina do trabalho", "cipa",
    "espaço confinado", "trabalho em altura", "ergonomia",
    "pcmso", "pgr", "ppra", "ltcat", "laudo",
    "agente nocivo", "agente químico", "agente físico", "agente biológico",
    "caldeira", "vaso de pressão", "explosivo", "inflamável",
    "mineração", "construção civil", "indústria da construção",
]

KEYWORDS_EXCLUDE = [
    "concurso público", "licitação", "pregão", "contrato administrativo",
    "aposentadoria", "pensão", "benefício previdenciário",
    "imposto", "tributo", "fiscal", "receita federal",
]

# ─── Parser HTML ─────────────────────────────────────────────────────────────
class TextExtractor(HTMLParser):
    def __init__(self):
        super().__init__()
        self.texts = []
        self._skip = False
        self.links = []
        self._current_href = None

    def handle_starttag(self, tag, attrs):
        if tag in ('script', 'style', 'nav', 'footer', 'head'): self._skip = True
        if tag == 'a':
            attrs_dict = dict(attrs)
            self._current_href = attrs_dict.get('href', '')

    def handle_endtag(self, tag):
        if tag in ('script', 'style', 'nav', 'footer', 'head'): self._skip = False
        if tag == 'a': self._current_href = None

    def handle_data(self, data):
        if not self._skip:
            s = data.strip()
            if s: self.texts.append(s)

    def get_text(self): return ' '.join(self.texts)


def fetch_url(url, timeout=25):
    """Faz requisição HTTP simulando navegador."""
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36',
        'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
        'Accept-Language': 'pt-BR,pt;q=0.9',
        'Connection': 'keep-alive',
    }
    req = urllib.request.Request(url, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            raw = resp.read()
            try: return raw.decode('utf-8')
            except: return raw.decode('latin-1', errors='replace')
    except urllib.error.HTTPError as e:
        print(f"    [HTTP {e.code}]")
        return None
    except Exception as e:
        print(f"    [ERRO: {type(e).__name__}: {e}]")
        return None


def is_relevant(text):
    """Verifica se o texto é relevante para segurança do trabalho."""
    text_lower = text.lower()
    # Deve conter pelo menos uma palavra-chave relevante
    has_keyword = any(kw in text_lower for kw in KEYWORDS_INCLUDE)
    # Não deve ser sobre assuntos não relacionados
    has_exclusion = any(kw in text_lower for kw in KEYWORDS_EXCLUDE)
    return has_keyword and not has_exclusion


def extract_dou_results(html, search_term):
    """Extrai resultados de busca do DOU."""
    if not html:
        return []

    results = []

    # Extrai blocos de resultado — o DOU usa divs com classe específica
    # Padrão: título do ato + data + link
    
    # Busca por padrões de portaria/instrução no texto completo
    parser = TextExtractor()
    parser.feed(html)
    full_text = parser.get_text()

    # Extrai links do HTML
    links = re.findall(
        r'href=["\'](/materia/[^"\']+|https://www\.in\.gov\.br/[^"\']+)["\']',
        html
    )

    # Extrai títulos de atos (padrão DOU)
    patterns = [
        # PORTARIA Nº X, DE X DE MÊS DE ANO
        r'(PORTARIA\s+(?:MTE|MTb|SEFIT|SIT|SST|SEPRT)?\s*(?:N[Oº°\.]+\s*)?\d[\d\.]*[\s,]+DE\s+\d+\s+DE\s+\w+\s+DE\s+\d{4}[^\.]{0,300})',
        # INSTRUÇÃO NORMATIVA
        r'(INSTRU[ÇC][ÃA]O\s+NORMATIVA\s*(?:N[Oº°\.]+\s*)?\d[\d\.]*[\s,]+DE[^\.]{0,300})',
        # RESOLUÇÃO
        r'(RESOLU[ÇC][ÃA]O\s*(?:N[Oº°\.]+\s*)?\d[\d\.]*[\s,]+DE[^\.]{0,300})',
        # Altera norma regulamentadora
        r'((?:Altera|Aprova|Revoga|Institui|Estabelece)[^\.]{10,200}(?:[Nn]orma [Rr]egulamentadora|[Ss]egurança[^\.]{5,100}[Tt]rabalho)[^\.]{0,100})',
    ]

    found_acts = set()
    for pattern in patterns:
        matches = re.findall(pattern, full_text, re.IGNORECASE)
        for match in matches:
            clean = re.sub(r'\s+', ' ', match.strip())
            if len(clean) > 20 and is_relevant(clean):
                act_id = hashlib.md5(clean[:100].encode()).hexdigest()[:12]
                if act_id not in found_acts:
                    found_acts.add(act_id)
                    # Tenta encontrar link correspondente
                    link = next((
                        f"https://www.in.gov.br{l}" if l.startswith('/') else l
                        for l in links
                        if 'materia' in l or 'dou' in l.lower()
                    ), f"https://www.in.gov.br/consulta/-/buscar/dou?q={urllib.parse.quote(search_term)}&s=todos")

                    results.append({
                        "titulo": clean[:200],
                        "link": link,
                        "fonte": "Diário Oficial da União",
                        "busca": search_term
                    })

    return results[:5]  # limita por busca


def search_dou(term, date_str):
    """Busca no DOU por termo específico na data de hoje."""
    # URL de busca do DOU com filtro de data
    encoded = urllib.parse.quote(f'"{term}"')
    url = f"{DOU_SEARCH_BASE}?q={encoded}&s=todos&exactDate={date_str}&sortType=0"
    print(f"    Buscando: \"{term}\"...", end=" ", flush=True)
    html = fetch_url(url)
    if not html:
        print("falha.")
        return []

    # Verifica se há resultados
    text_lower = html.lower()
    has_results = (
        'resultado' in text_lower or
        'materia' in text_lower or
        'portaria' in text_lower or
        'instrução' in text_lower or
        'norma regulamentadora' in text_lower
    )

    if not has_results:
        print("sem publicações.")
        return []

    results = extract_dou_results(html, term)
    print(f"{len(results)} resultado(s) relevante(s).")
    return results


def check_mte_portarias():
    """Monitora a página de portarias SST do MTE."""
    print("  Verificando portal de Portarias SST (MTE)...", end=" ", flush=True)
    html = fetch_url(MTE_PORTARIAS)
    if not html:
        # Tenta URL alternativa
        html = fetch_url(MTE_INDEX)
    if not html:
        print("falha.")
        return None, None

    parser = TextExtractor()
    parser.feed(html)
    clean = parser.get_text()
    clean = re.sub(r'\d{2}/\d{2}/\d{4}', '', clean)
    clean = re.sub(r'\d{4}-\d{2}-\d{2}', '', clean)
    clean = re.sub(r'\s+', ' ', clean).strip()
    h = hashlib.md5(clean.encode('utf-8')).hexdigest()
    print("OK.")
    return h, MTE_PORTARIAS


def load_state():
    if os.path.exists(STATE_FILE):
        with open(STATE_FILE, 'r', encoding='utf-8') as f:
            return json.load(f)
    return {
        "last_check": None,
        "status": "Monitorando",
        "total_nrs": 38,
        "hashes": {},
        "publicacoes_recentes": [],
        "history": [],
        "recent_changes": []
    }


def save_state(state):
    with open(STATE_FILE, 'w', encoding='utf-8') as f:
        json.dump(state, f, ensure_ascii=False, indent=2)


def run_check():
    print(f"\n{'='*65}")
    print(f"  Monitor SST / DOU — {now_brasilia().strftime('%d/%m/%Y %H:%M')} (Brasília)")
    print(f"{'='*65}\n")

    state = load_state()
    today     = now_brasilia()
    today_str = today.strftime('%Y-%m-%d')
    today_fmt = today.strftime('%d/%m/%Y')
    now_str   = today.strftime('%d/%m/%Y %H:%M')
    # Formato de data para o DOU (dd-mm-yyyy)
    dou_date  = today.strftime('%d-%m-%Y')

    new_publications = []

    # ── 1. Busca no Diário Oficial da União ──────────────────────────────────
    print("[ DIÁRIO OFICIAL DA UNIÃO ]")
    seen_ids = set()

    for term in SEARCH_TERMS:
        results = search_dou(term, dou_date)
        for r in results:
            pub_id = hashlib.md5(r['titulo'][:80].encode()).hexdigest()[:16]
            if pub_id not in seen_ids:
                seen_ids.add(pub_id)
                r['id']       = pub_id
                r['data']     = today_str
                r['data_fmt'] = today_fmt
                r['tipo']     = 'DOU'
                new_publications.append(r)
        time.sleep(1)  # respeita o servidor

    # ── 2. Monitora página de portarias SST do MTE ───────────────────────────
    print("\n[ PORTAL MTE — PORTARIAS SST ]")
    mte_hash, mte_url = check_mte_portarias()
    if mte_hash:
        old_mte = state["hashes"].get("__mte_portarias__")
        if old_mte and mte_hash != old_mte:
            print("  → ALTERAÇÃO DETECTADA no portal de portarias!")
            pub = {
                "id":       "mte_portal_" + today_str,
                "titulo":   "Atualização detectada no portal de Portarias SST do MTE",
                "link":     mte_url,
                "fonte":    "Portal MTE — Portarias SST",
                "busca":    "monitoramento automático",
                "data":     today_str,
                "data_fmt": today_fmt,
                "tipo":     "MTE"
            }
            if pub["id"] not in seen_ids:
                new_publications.append(pub)
        state["hashes"]["__mte_portarias__"] = mte_hash

    # ── Atualiza estado ───────────────────────────────────────────────────────
    state["last_check"] = now_str
    state["total_nrs"]  = 38

    if new_publications:
        state["status"] = "Nova Publicação"
        # Adiciona às recentes (evita duplicatas)
        existing_ids = {p.get("id") for p in state.get("publicacoes_recentes", [])}
        for p in new_publications:
            if p["id"] not in existing_ids:
                state.setdefault("publicacoes_recentes", []).append(p)
                state.setdefault("history", []).append(p)
                state.setdefault("recent_changes", []).append(p)
    else:
        state["status"] = "Monitorando"

    # Remove publicações recentes com mais de 7 dias
    cutoff = today - timedelta(days=7)
    state["publicacoes_recentes"] = [
        p for p in state.get("publicacoes_recentes", [])
        if datetime.strptime(p["data"], '%Y-%m-%d').replace(tzinfo=BRASILIA) >= cutoff
    ]
    state["recent_changes"] = state["publicacoes_recentes"]

    save_state(state)

    print(f"\n{'─'*65}")
    print(f"  Status      : {state['status']}")
    print(f"  Horário     : {state['last_check']}")
    print(f"  Publicações : {len(new_publications)} nova(s) hoje")
    print(f"{'─'*65}\n")


if __name__ == '__main__':
    run_check()
