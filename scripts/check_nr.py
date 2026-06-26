import json
import os
import re
import hashlib
import urllib.request
import urllib.error
from datetime import datetime, timezone, timedelta
from html.parser import HTMLParser

BRASILIA = timezone(timedelta(hours=-3))
def now_brasilia():
    return datetime.now(BRASILIA)

DATA_DIR   = os.path.join(os.path.dirname(__file__), '..', 'data')
STATE_FILE = os.path.join(DATA_DIR, 'state.json')
os.makedirs(DATA_DIR, exist_ok=True)

BASE = (
    "https://www.gov.br/trabalho-e-emprego/pt-br/acesso-a-informacao/"
    "participacao-social/conselhos-e-orgaos-colegiados/"
    "comissao-tripartite-partitaria-permanente/"
    "normas-regulamentadora/normas-regulamentadoras-vigentes"
)

# ─── URLs confirmadas individualmente ────────────────────────────────────────
NR_LIST = [
    {"nr":"NR-1",  "nome":"Disposições Gerais e Gerenciamento de Riscos Ocupacionais",                                               "url":f"{BASE}/nr-1"},
    {"nr":"NR-2",  "nome":"Inspeção Prévia (Revogada)",                                                                              "url":f"{BASE}/norma-regulamentadora-no-2-nr-2"},
    {"nr":"NR-3",  "nome":"Embargo e Interdição",                                                                                    "url":f"{BASE}/norma-regulamentadora-no-3-nr-3"},
    {"nr":"NR-4",  "nome":"Serviços Especializados em Engenharia de Segurança e em Medicina do Trabalho",                            "url":f"{BASE}/norma-regulamentadora-no-4-nr-4"},
    {"nr":"NR-5",  "nome":"Comissão Interna de Prevenção de Acidentes e de Assédio",                                                "url":f"{BASE}/norma-regulamentadora-no-5-nr-5"},
    {"nr":"NR-6",  "nome":"Equipamentos de Proteção Individual",                                                                     "url":f"{BASE}/norma-regulamentadora-no-6-nr-6"},
    {"nr":"NR-7",  "nome":"Programa de Controle Médico de Saúde Ocupacional",                                                       "url":f"{BASE}/norma-regulamentadora-no-7-nr-7"},
    {"nr":"NR-8",  "nome":"Edificações",                                                                                             "url":f"{BASE}/norma-regulamentadora-no-8-nr-8"},
    {"nr":"NR-9",  "nome":"Avaliação e Controle das Exposições Ocupacionais a Agentes Físicos, Químicos e Biológicos",              "url":f"{BASE}/norma-regulamentadora-no-9-nr-9"},
    {"nr":"NR-10", "nome":"Segurança em Instalações e Serviços em Eletricidade",                                                    "url":f"{BASE}/norma-regulamentadora-no-10-nr-10"},
    {"nr":"NR-11", "nome":"Transporte, Movimentação, Armazenagem e Manuseio de Materiais",                                          "url":f"{BASE}/norma-regulamentadora-no-11-nr-11"},
    {"nr":"NR-12", "nome":"Segurança no Trabalho em Máquinas e Equipamentos",                                                       "url":f"{BASE}/norma-regulamentadora-no-12-nr-12"},
    {"nr":"NR-13", "nome":"Caldeiras, Vasos de Pressão, Tubulações e Reservatórios Metálicos de Pressão",                          "url":f"{BASE}/norma-regulamentadora-no-13-nr-13"},
    {"nr":"NR-14", "nome":"Fornos",                                                                                                  "url":f"{BASE}/norma-regulamentadora-no-14-nr-14"},
    {"nr":"NR-15", "nome":"Atividades e Operações Insalubres",                                                                      "url":f"{BASE}/norma-regulamentadora-no-15-nr-15"},
    {"nr":"NR-16", "nome":"Atividades e Operações Perigosas",                                                                       "url":f"{BASE}/norma-regulamentadora-no-16-nr-16"},
    {"nr":"NR-17", "nome":"Ergonomia",                                                                                               "url":f"{BASE}/norma-regulamentadora-no-17-nr-17"},
    {"nr":"NR-18", "nome":"Segurança e Saúde no Trabalho na Indústria da Construção",                                               "url":f"{BASE}/norma-regulamentadora-no-18-nr-18"},
    {"nr":"NR-19", "nome":"Explosivos",                                                                                              "url":f"{BASE}/norma-regulamentadora-no-19-nr-19"},
    {"nr":"NR-20", "nome":"Segurança e Saúde no Trabalho com Inflamáveis e Combustíveis",                                          "url":f"{BASE}/norma-regulamentadora-no-20-nr-20"},
    {"nr":"NR-21", "nome":"Trabalho a Céu Aberto",                                                                                  "url":f"{BASE}/norma-regulamentadora-no-21-nr-21"},
    {"nr":"NR-22", "nome":"Segurança e Saúde Ocupacional na Mineração",                                                             "url":f"{BASE}/norma-regulamentadora-no-22-nr-22"},
    {"nr":"NR-23", "nome":"Proteção Contra Incêndios",                                                                              "url":f"{BASE}/norma-regulamentadora-no-23-nr-23"},
    {"nr":"NR-24", "nome":"Condições Sanitárias e de Conforto nos Locais de Trabalho",                                              "url":f"{BASE}/norma-regulamentadora-no-24-nr-24"},
    {"nr":"NR-25", "nome":"Resíduos Industriais",                                                                                   "url":f"{BASE}/norma-regulamentadora-no-25-nr-25"},
    {"nr":"NR-26", "nome":"Sinalização de Segurança",                                                                               "url":f"{BASE}/norma-regulamentadora-no-26-nr-26"},
    {"nr":"NR-27", "nome":"Registro Profissional do Técnico de Segurança do Trabalho (Revogada)",                                   "url":f"{BASE}/norma-regulamentadora-no-27-nr-27"},
    {"nr":"NR-28", "nome":"Fiscalização e Penalidades",                                                                             "url":f"{BASE}/norma-regulamentadora-no-28-nr-28"},
    {"nr":"NR-29", "nome":"Segurança e Saúde no Trabalho Portuário",                                                                "url":f"{BASE}/norma-regulamentadora-no-29-nr-29"},
    {"nr":"NR-30", "nome":"Segurança e Saúde no Trabalho Aquaviário",                                                               "url":f"{BASE}/norma-regulamentadora-no-30-nr-30"},
    {"nr":"NR-31", "nome":"Segurança e Saúde no Trabalho na Agricultura, Pecuária, Silvicultura, Exploração Florestal e Aquicultura","url":f"{BASE}/norma-regulamentadora-no-31-nr-31"},
    {"nr":"NR-32", "nome":"Segurança e Saúde no Trabalho em Estabelecimentos de Saúde",                                             "url":f"{BASE}/norma-regulamentadora-no-32-nr-32"},
    {"nr":"NR-33", "nome":"Segurança e Saúde nos Trabalhos em Espaços Confinados",                                                  "url":f"{BASE}/norma-regulamentadora-no-33-nr-33"},
    {"nr":"NR-34", "nome":"Condições e Meio Ambiente de Trabalho na Indústria da Construção, Reparação e Desmonte Naval",           "url":f"{BASE}/norma-regulamentadora-no-34-nr-34"},
    {"nr":"NR-35", "nome":"Trabalho em Altura",                                                                                     "url":f"{BASE}/norma-regulamentadora-no-35-nr-35"},
    {"nr":"NR-36", "nome":"Segurança e Saúde no Trabalho em Empresas de Abate e Processamento de Carnes e Derivados",              "url":f"{BASE}/norma-regulamentadora-no-36-nr-36"},
    {"nr":"NR-37", "nome":"Segurança e Saúde em Plataformas de Petróleo",                                                          "url":"https://www.gov.br/trabalho-e-emprego/pt-br/assuntos/inspecao-do-trabalho/seguranca-e-saude-no-trabalho/ctpp-nrs/norma-regulamentadora-no-37-nr-37"},
    {"nr":"NR-38", "nome":"Segurança e Saúde no Trabalho nas Atividades de Limpeza Urbana e Manejo de Resíduos Sólidos",           "url":f"{BASE}/norma-regulamentadora-no-38-nr-38"},
]

# ─── Parser HTML ─────────────────────────────────────────────────────────────
class TextExtractor(HTMLParser):
    def __init__(self):
        super().__init__()
        self.texts = []
        self._skip = False
    def handle_starttag(self, tag, attrs):
        if tag in ('script','style','nav','footer','header'): self._skip = True
    def handle_endtag(self, tag):
        if tag in ('script','style','nav','footer','header'): self._skip = False
    def handle_data(self, data):
        if not self._skip:
            s = data.strip()
            if s: self.texts.append(s)
    def get_text(self): return ' '.join(self.texts)

def fetch_page(url, timeout=30):
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36',
        'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
        'Accept-Language': 'pt-BR,pt;q=0.9,en;q=0.8',
        'Accept-Encoding': 'gzip, deflate, br',
        'Connection': 'keep-alive',
    }
    req = urllib.request.Request(url, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            raw = resp.read()
            try: return raw.decode('utf-8')
            except: return raw.decode('latin-1', errors='replace')
    except urllib.error.HTTPError as e:
        print(f"[HTTP {e.code}]")
        return None
    except Exception as e:
        print(f"[ERRO: {e}]")
        return None

def page_hash(html):
    p = TextExtractor(); p.feed(html)
    clean = p.get_text()
    clean = re.sub(r'\d{2}/\d{2}/\d{4}', '', clean)
    clean = re.sub(r'\d{4}-\d{2}-\d{2}', '', clean)
    clean = re.sub(r'\d{2}h\d{2}', '', clean)
    return hashlib.md5(clean.encode('utf-8')).hexdigest()

def load_state():
    if os.path.exists(STATE_FILE):
        with open(STATE_FILE,'r',encoding='utf-8') as f: return json.load(f)
    return {"last_check":None,"status":"Monitorando","total_nrs":38,
            "hashes":{},"recent_changes":[],"history":[]}

def save_state(state):
    with open(STATE_FILE,'w',encoding='utf-8') as f:
        json.dump(state, f, ensure_ascii=False, indent=2)

def run_check():
    print(f"\n{'='*60}")
    print(f"  Monitor de NR — {now_brasilia().strftime('%d/%m/%Y %H:%M')} (Brasília)")
    print(f"{'='*60}\n")

    state = load_state()
    changes_found = []
    today_str = now_brasilia().strftime('%Y-%m-%d')
    now_str   = now_brasilia().strftime('%d/%m/%Y %H:%M')

    # ── Página índice geral ──────────────────────────────────────────────────
    print(f"  Verificando índice MTE...", end=" ", flush=True)
    idx_html = fetch_page(BASE)
    if idx_html:
        idx_hash = page_hash(idx_html)
        old_idx  = state["hashes"].get("__index__")
        if old_idx and idx_hash != old_idx:
            print("ALTERAÇÃO NA ÍNDICE!")
        else:
            print("OK.")
        state["hashes"]["__index__"] = idx_hash

    # ── Verifica cada NR individualmente ────────────────────────────────────
    for nr_info in NR_LIST:
        nr_key = nr_info["nr"].lower().replace("-","")
        print(f"  {nr_info['nr']}...", end=" ", flush=True)

        html = fetch_page(nr_info["url"])

        # Se der 404, tenta fallback com /nr-X
        if html is None:
            num = nr_info["nr"].replace("NR-","")
            fallback = f"{BASE}/nr-{num}"
            if fallback != nr_info["url"]:
                print(f"tentando fallback...", end=" ", flush=True)
                html = fetch_page(fallback)
                if html:
                    nr_info["url"] = fallback

        if html is None:
            print("falha, pulando.")
            continue

        new_hash = page_hash(html)
        old_hash = state["hashes"].get(nr_key)

        if old_hash is None:
            state["hashes"][nr_key] = new_hash
            print("hash inicial registrado.")
        elif new_hash != old_hash:
            print("ALTERAÇÃO DETECTADA!")
            state["hashes"][nr_key] = new_hash
            changes_found.append({
                "nr":       nr_info["nr"],
                "nome":     nr_info["nome"],
                "url":      nr_info["url"],
                "data":     today_str,
                "data_fmt": now_brasilia().strftime('%d/%m/%Y'),
                "source":   "gov.br / MTE"
            })
        else:
            print("sem alteração.")

    # ── Atualiza estado ──────────────────────────────────────────────────────
    state["last_check"] = now_str
    state["total_nrs"]  = 38
    state["status"] = "Alteração Detectada" if changes_found else "Monitorando"

    if changes_found:
        existing = {(c["nr"], c["data"]) for c in state["recent_changes"]}
        for c in changes_found:
            if (c["nr"], c["data"]) not in existing:
                state["recent_changes"].append(c)
        hist_ex = {(c["nr"], c["data"]) for c in state["history"]}
        for c in changes_found:
            if (c["nr"], c["data"]) not in hist_ex:
                state["history"].append(c)

    cutoff = now_brasilia() - timedelta(days=7)
    state["recent_changes"] = [
        c for c in state["recent_changes"]
        if datetime.strptime(c["data"],'%Y-%m-%d').replace(tzinfo=BRASILIA) >= cutoff
    ]

    save_state(state)
    print(f"\n{'─'*60}")
    print(f"  Status  : {state['status']}")
    print(f"  Horário : {state['last_check']}")
    print(f"  Mudanças: {len(changes_found)}")
    print(f"{'─'*60}\n")

if __name__ == '__main__':
    run_check()
