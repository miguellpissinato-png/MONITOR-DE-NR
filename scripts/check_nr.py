"""
Monitor SST v3.1 — Segurança e Saúde no Trabalho
Fontes:
  1. Portarias SST MTE (gov.br/sst-portarias) — FONTE PRIMÁRIA
  2. Página índice NR (gov.br)                 — BACKUP

NOTA (2026-08-27): a antiga "Fonte 2 — DOU Federal via Querido Diário"
foi REMOVIDA. O Querido Diário indexa apenas Diários Oficiais MUNICIPAIS
(prefeituras) — ele nunca teve o Diário Oficial da União (DOU), então
essa fonte nunca poderia detectar uma portaria federal do MTE, mesmo
funcionando perfeitamente. Os erros de HTTPError vistos nos logs vinham
dessa chamada, que foi removida por ser inútil e por gerar ruído/falhas
falsas nos logs. As duas fontes abaixo (monitoramento por hash das
páginas oficiais do MTE) continuam ativas e são as que efetivamente
detectam mudanças.
"""

import json, os, re, hashlib
import urllib.request, urllib.error
from datetime import datetime, timezone, timedelta
from html.parser import HTMLParser

BRASILIA = timezone(timedelta(hours=-3))
def now_brasilia(): return datetime.now(BRASILIA)

DATA_DIR   = os.path.join(os.path.dirname(__file__), '..', 'data')
STATE_FILE = os.path.join(DATA_DIR, 'state.json')
os.makedirs(DATA_DIR, exist_ok=True)

YEAR = now_brasilia().year
MTE_PORTARIAS_URL = (
    f"https://www.gov.br/trabalho-e-emprego/pt-br/assuntos/inspecao-do-trabalho/"
    f"seguranca-e-saude-no-trabalho/sst-portarias/{YEAR}-1"
)
MTE_INDEX_URL = (
    "https://www.gov.br/trabalho-e-emprego/pt-br/acesso-a-informacao/"
    "participacao-social/conselhos-e-orgaos-colegiados/"
    "comissao-tripartite-partitaria-permanente/"
    "normas-regulamentadora/normas-regulamentadoras-vigentes"
)

class TextExtractor(HTMLParser):
    def __init__(self):
        super().__init__(); self.texts=[]; self._skip=False
    def handle_starttag(self,tag,attrs):
        if tag in ('script','style','nav','footer','head'): self._skip=True
    def handle_endtag(self,tag):
        if tag in ('script','style','nav','footer','head'): self._skip=False
    def handle_data(self,data):
        if not self._skip:
            s=data.strip()
            if s: self.texts.append(s)
    def get_text(self): return ' '.join(self.texts)

def fetch_html(url, timeout=30):
    headers = {
        'User-Agent':'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
        'Accept':'text/html,application/xhtml+xml;q=0.9,*/*;q=0.8',
        'Accept-Language':'pt-BR,pt;q=0.9',
    }
    req = urllib.request.Request(url, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            raw=r.read()
            try: return raw.decode('utf-8')
            except: return raw.decode('latin-1',errors='replace')
    except urllib.error.HTTPError as e: print(f"[HTTP {e.code}]"); return None
    except Exception as e: print(f"[ERRO: {type(e).__name__}]"); return None

def stable_hash(text):
    t=re.sub(r'\d{2}/\d{2}/\d{4}(\s+\d{2}h\d{2})?','',text)
    t=re.sub(r'\d{4}-\d{2}-\d{2}[T\d:.Z+-]*','',t)
    t=re.sub(r'\s+',' ',t).strip()
    return hashlib.md5(t.encode('utf-8')).hexdigest()

def page_hash(html):
    p=TextExtractor(); p.feed(html)
    return stable_hash(p.get_text())

def check_mte_portarias(state, today_str, today_fmt):
    print(f"\n[ FONTE 1 — Portarias SST MTE {YEAR} ]")
    print(f"  Verificando...", end=" ", flush=True)
    html = fetch_html(MTE_PORTARIAS_URL)
    if not html: print("falha."); return []

    new_hash = page_hash(html)
    old_hash = state["hashes"].get("__mte_portarias__")
    state["hashes"]["__mte_portarias__"] = new_hash

    if old_hash is None: print("hash inicial registrado."); return []
    if new_hash == old_hash: print("sem alteração."); return []

    print("ALTERAÇÃO DETECTADA!")
    pdf_names = re.findall(
        r'Portaria\s+MTE\s+n[º°\.°]\s*[\d\.]+[^<\n]{5,120}',
        html, re.IGNORECASE
    )
    titulo = "Nova portaria SST detectada na página oficial do MTE"
    if pdf_names: titulo = f"Nova portaria: {pdf_names[-1][:200]}"

    return [{
        'id': 'mte_portarias_' + today_str,
        'titulo': titulo,
        'link': MTE_PORTARIAS_URL,
        'fonte': 'Portal MTE — Portarias SST (gov.br)',
        'busca': 'monitoramento por hash',
        'data': today_str, 'data_fmt': today_fmt, 'tipo': 'MTE',
    }]

def check_nr_index(state, today_str, today_fmt):
    print(f"\n[ FONTE 2 — Índice NR MTE (backup) ]")
    print("  Verificando...", end=" ", flush=True)
    html = fetch_html(MTE_INDEX_URL)
    if not html: print("falha."); return []

    new_hash = page_hash(html)
    old_hash = state["hashes"].get("__nr_index__")
    state["hashes"]["__nr_index__"] = new_hash

    if old_hash is None: print("hash inicial registrado."); return []
    if new_hash == old_hash: print("sem alteração."); return []

    print("ALTERAÇÃO DETECTADA!")
    return [{
        'id': 'nr_index_' + today_str,
        'titulo': 'Alteração detectada na página índice das Normas Regulamentadoras',
        'link': MTE_INDEX_URL, 'fonte': 'Portal MTE — Índice NR',
        'busca': 'monitoramento por hash',
        'data': today_str, 'data_fmt': today_fmt, 'tipo': 'MTE',
    }]

def load_state():
    if os.path.exists(STATE_FILE):
        with open(STATE_FILE,'r',encoding='utf-8') as f: return json.load(f)
    return {"last_check":None,"status":"Monitorando","total_nrs":38,
            "hashes":{},"publicacoes_recentes":[],"recent_changes":[],"history":[]}

def save_state(state):
    with open(STATE_FILE,'w',encoding='utf-8') as f:
        json.dump(state,f,ensure_ascii=False,indent=2)

def run_check():
    print(f"\n{'='*65}")
    print(f"  Monitor SST v3.1 — {now_brasilia().strftime('%d/%m/%Y %H:%M')} (Brasília)")
    print(f"{'='*65}")

    state=load_state()
    today=now_brasilia()
    today_str=today.strftime('%Y-%m-%d')
    today_fmt=today.strftime('%d/%m/%Y')
    now_str=today.strftime('%d/%m/%Y %H:%M')

    seen_ids=(
        {p.get('id') for p in state.get('history',[])} |
        {p.get('id') for p in state.get('publicacoes_recentes',[])}
    )
    new_pubs=[]

    for p in check_mte_portarias(state,today_str,today_fmt):
        if p['id'] not in seen_ids: seen_ids.add(p['id']); new_pubs.append(p)
    for p in check_nr_index(state,today_str,today_fmt):
        if p['id'] not in seen_ids: seen_ids.add(p['id']); new_pubs.append(p)

    state["last_check"]=now_str
    state["total_nrs"]=38
    state["status"]="Nova Publicação" if new_pubs else "Monitorando"

    if new_pubs:
        state.setdefault("publicacoes_recentes",[]).extend(new_pubs)
        state.setdefault("history",[]).extend(new_pubs)

    cutoff=today-timedelta(days=7)
    state["publicacoes_recentes"]=[
        p for p in state.get("publicacoes_recentes",[])
        if p.get("data") and
        datetime.strptime(p["data"],'%Y-%m-%d').replace(tzinfo=BRASILIA)>=cutoff
    ]
    state["recent_changes"]=state["publicacoes_recentes"]
    save_state(state)

    print(f"\n{'─'*65}")
    print(f"  Status           : {state['status']}")
    print(f"  Horário          : {state['last_check']}")
    print(f"  Novas publicações: {len(new_pubs)}")
    print(f"  Fontes ativas    : Portarias SST MTE + Índice NR (monitoramento por hash)")
    print(f"{'─'*65}\n")

if __name__=='__main__':
    run_check()
