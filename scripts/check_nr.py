import json
import os
import re
import hashlib
import urllib.request
import urllib.error
from datetime import datetime, timezone, timedelta
from html.parser import HTMLParser

# ─── Fuso horário de Brasília ───────────────────────────────────────────────
BRASILIA = timezone(timedelta(hours=-3))

def now_brasilia():
    return datetime.now(BRASILIA)

# ─── Caminhos dos arquivos de dados ─────────────────────────────────────────
DATA_DIR   = os.path.join(os.path.dirname(__file__), '..', 'data')
STATE_FILE = os.path.join(DATA_DIR, 'state.json')
os.makedirs(DATA_DIR, exist_ok=True)

# ─── URL base CORRETA (atualizada em 2024) ───────────────────────────────────
BASE = (
    "https://www.gov.br/trabalho-e-emprego/pt-br/acesso-a-informacao/"
    "participacao-social/conselhos-e-orgaos-colegiados/"
    "comissao-tripartite-partitaria-permanente/"
    "normas-regulamentadora/normas-regulamentadoras-vigentes"
)

# ─── Lista oficial das NR com URLs corretas do gov.br ────────────────────────
NR_LIST = [
    {"nr": "NR-1",  "nome": "Disposições Gerais e Gerenciamento de Riscos Ocupacionais",                          "url": f"{BASE}/nr-1"},
    {"nr": "NR-2",  "nome": "Inspeção Prévia (Revogada)",                                                          "url": f"{BASE}/norma-regulamentadora-no-2-nr-2"},
    {"nr": "NR-3",  "nome": "Embargo e Interdição",                                                                "url": f"{BASE}/nr-3"},
    {"nr": "NR-4",  "nome": "Serviços Especializados em Engenharia de Segurança e em Medicina do Trabalho",        "url": f"{BASE}/nr-4"},
    {"nr": "NR-5",  "nome": "Comissão Interna de Prevenção de Acidentes e de Assédio",                            "url": f"{BASE}/nr-5"},
    {"nr": "NR-6",  "nome": "Equipamentos de Proteção Individual",                                                 "url": f"{BASE}/nr-6"},
    {"nr": "NR-7",  "nome": "Programa de Controle Médico de Saúde Ocupacional",                                   "url": f"{BASE}/nr-7"},
    {"nr": "NR-8",  "nome": "Edificações",                                                                         "url": f"{BASE}/nr-8"},
    {"nr": "NR-9",  "nome": "Avaliação e Controle das Exposições Ocupacionais a Agentes Físicos, Químicos e Biológicos", "url": f"{BASE}/nr-9"},
    {"nr": "NR-10", "nome": "Segurança em Instalações e Serviços em Eletricidade",                                "url": f"{BASE}/nr-10"},
    {"nr": "NR-11", "nome": "Transporte, Movimentação, Armazenagem e Manuseio de Materiais",                      "url": f"{BASE}/nr-11"},
    {"nr": "NR-12", "nome": "Segurança no Trabalho em Máquinas e Equipamentos",                                   "url": f"{BASE}/nr-12"},
    {"nr": "NR-13", "nome": "Caldeiras, Vasos de Pressão, Tubulações e Reservatórios Metálicos de Pressão",       "url": f"{BASE}/nr-13"},
    {"nr": "NR-14", "nome": "Fornos",                                                                              "url": f"{BASE}/nr-14"},
    {"nr": "NR-15", "nome": "Atividades e Operações Insalubres",                                                   "url": f"{BASE}/nr-15"},
    {"nr": "NR-16", "nome": "Atividades e Operações Perigosas",                                                    "url": f"{BASE}/nr-16"},
    {"nr": "NR-17", "nome": "Ergonomia",                                                                           "url": f"{BASE}/nr-17"},
    {"nr": "NR-18", "nome": "Segurança e Saúde no Trabalho na Indústria da Construção",                           "url": f"{BASE}/nr-18"},
    {"nr": "NR-19", "nome": "Explosivos",                                                                          "url": f"{BASE}/nr-19"},
    {"nr": "NR-20", "nome": "Segurança e Saúde no Trabalho com Inflamáveis e Combustíveis",                       "url": f"{BASE}/nr-20"},
    {"nr": "NR-21", "nome": "Trabalho a Céu Aberto",                                                              "url": f"{BASE}/nr-21"},
    {"nr": "NR-22", "nome": "Segurança e Saúde Ocupacional na Mineração",                                         "url": f"{BASE}/nr-22"},
    {"nr": "NR-23", "nome": "Proteção Contra Incêndios",                                                          "url": f"{BASE}/nr-23"},
    {"nr": "NR-24", "nome": "Condições Sanitárias e de Conforto nos Locais de Trabalho",                          "url": f"{BASE}/nr-24"},
    {"nr": "NR-25", "nome": "Resíduos Industriais",                                                               "url": f"{BASE}/nr-25"},
    {"nr": "NR-26", "nome": "Sinalização de Segurança",                                                           "url": f"{BASE}/nr-26"},
    {"nr": "NR-27", "nome": "Registro Profissional do Técnico de Segurança do Trabalho (Revogada)",               "url": f"{BASE}/nr-27"},
    {"nr": "NR-28", "nome": "Fiscalização e Penalidades",                                                          "url": f"{BASE}/nr-28"},
    {"nr": "NR-29", "nome": "Segurança e Saúde no Trabalho Portuário",                                            "url": f"{BASE}/nr-29"},
    {"nr": "NR-30", "nome": "Segurança e Saúde no Trabalho Aquaviário",                                           "url": f"{BASE}/nr-30"},
    {"nr": "NR-31", "nome": "Segurança e Saúde no Trabalho na Agricultura, Pecuária, Silvicultura, Exploração Florestal e Aquicultura", "url": f"{BASE}/nr-31"},
    {"nr": "NR-32", "nome": "Segurança e Saúde no Trabalho em Estabelecimentos de Saúde",                         "url": f"{BASE}/nr-32"},
    {"nr": "NR-33", "nome": "Segurança e Saúde nos Trabalhos em Espaços Confinados",                              "url": f"{BASE}/nr-33"},
    {"nr": "NR-34", "nome": "Condições e Meio Ambiente de Trabalho na Indústria da Construção, Reparação e Desmonte Naval", "url": f"{BASE}/nr-34"},
    {"nr": "NR-35", "nome": "Trabalho em Altura",                                                                  "url": f"{BASE}/nr-35"},
    {"nr": "NR-36", "nome": "Segurança e Saúde no Trabalho em Empresas de Abate e Processamento de Carnes e Derivados", "url": f"{BASE}/nr-36"},
    {"nr": "NR-37", "nome": "Segurança e Saúde em Plataformas de Petróleo",                                       "url": f"{BASE}/nr-37"},
    {"nr": "NR-38", "nome": "Segurança e Saúde no Trabalho nas Atividades de Limpeza Urbana e Manejo de Resíduos Sólidos", "url": f"{BASE}/nr-38"},
]

# ─── Parser HTML simples ────────────────────────────────────────────────────
class TextExtractor(HTMLParser):
    def __init__(self):
        super().__init__()
        self.texts = []
        self._skip = False

    def handle_starttag(self, tag, attrs):
        if tag in ('script', 'style', 'nav', 'footer', 'header'):
            self._skip = True

    def handle_endtag(self, tag):
        if tag in ('script', 'style', 'nav', 'footer', 'header'):
            self._skip = False

    def handle_data(self, data):
        if not self._skip:
            stripped = data.strip()
            if stripped:
                self.texts.append(stripped)

    def get_text(self):
        return ' '.join(self.texts)


def fetch_page(url, timeout=25):
    headers = {
        'User-Agent': 'Mozilla/5.0 (compatible; NR-Monitor/2.0; +https://github.com)',
        'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
        'Accept-Language': 'pt-BR,pt;q=0.9',
    }
    req = urllib.request.Request(url, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            raw = resp.read()
            try:
                return raw.decode('utf-8')
            except UnicodeDecodeError:
                return raw.decode('latin-1', errors='replace')
    except urllib.error.HTTPError as e:
        print(f"  [HTTP {e.code} em {url}]")
        return None
    except Exception as e:
        print(f"  [ERRO: {e}]")
        return None


def page_hash(html_text):
    parser = TextExtractor()
    parser.feed(html_text)
    clean = parser.get_text()
    clean = re.sub(r'\d{2}/\d{2}/\d{4}', '', clean)
    clean = re.sub(r'\d{4}-\d{2}-\d{2}', '', clean)
    return hashlib.md5(clean.encode('utf-8')).hexdigest()


def load_state():
    if os.path.exists(STATE_FILE):
        with open(STATE_FILE, 'r', encoding='utf-8') as f:
            return json.load(f)
    return {
        "last_check": None,
        "status": "Monitorando",
        "total_nrs": len(NR_LIST),
        "hashes": {},
        "recent_changes": [],
        "history": []
    }


def save_state(state):
    with open(STATE_FILE, 'w', encoding='utf-8') as f:
        json.dump(state, f, ensure_ascii=False, indent=2)


def run_check():
    print(f"\n{'='*60}")
    print(f"  Monitor de NR — {now_brasilia().strftime('%d/%m/%Y %H:%M')} (Brasília)")
    print(f"{'='*60}\n")

    state = load_state()
    changes_found = []
    today_str = now_brasilia().strftime('%Y-%m-%d')
    now_str   = now_brasilia().strftime('%d/%m/%Y %H:%M')

    # ── Página índice ────────────────────────────────────────────────────────
    print("Verificando página índice do MTE...")
    index_html = fetch_page(BASE)
    if index_html:
        idx_hash = page_hash(index_html)
        old_idx  = state["hashes"].get("__index__")
        if old_idx and idx_hash != old_idx:
            print("  → Alteração detectada na página índice!")
        state["hashes"]["__index__"] = idx_hash
        print("  OK.")

    # ── Verifica cada NR ────────────────────────────────────────────────────
    for nr_info in NR_LIST:
        nr_key = nr_info["nr"].lower().replace("-", "")
        print(f"  Verificando {nr_info['nr']}...", end=" ", flush=True)
        html = fetch_page(nr_info["url"])
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
            change_entry = {
                "nr":       nr_info["nr"],
                "nome":     nr_info["nome"],
                "url":      nr_info["url"],
                "data":     today_str,
                "data_fmt": now_brasilia().strftime('%d/%m/%Y'),
                "source":   "gov.br / MTE"
            }
            changes_found.append(change_entry)
        else:
            print("sem alteração.")

    # ── Atualiza estado ──────────────────────────────────────────────────────
    state["last_check"] = now_str
    state["total_nrs"]  = len(NR_LIST)

    if changes_found:
        state["status"] = "Alteração Detectada"
        existing = {(c["nr"], c["data"]) for c in state["recent_changes"]}
        for c in changes_found:
            if (c["nr"], c["data"]) not in existing:
                state["recent_changes"].append(c)
        hist_existing = {(c["nr"], c["data"]) for c in state["history"]}
        for c in changes_found:
            if (c["nr"], c["data"]) not in hist_existing:
                state["history"].append(c)
    else:
        state["status"] = "Monitorando"

    # ── Remove recentes com mais de 7 dias ───────────────────────────────────
    cutoff = now_brasilia() - timedelta(days=7)
    state["recent_changes"] = [
        c for c in state["recent_changes"]
        if datetime.strptime(c["data"], '%Y-%m-%d').replace(tzinfo=BRASILIA) >= cutoff
    ]

    save_state(state)

    print(f"\n{'─'*60}")
    print(f"  Status  : {state['status']}")
    print(f"  Horário : {state['last_check']}")
    print(f"  Mudanças: {len(changes_found)}")
    print(f"{'─'*60}\n")


if __name__ == '__main__':
    run_check()
