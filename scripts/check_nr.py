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

# ─── URL da página índice (única confirmada como funcional) ──────────────────
INDEX_URL = (
    "https://www.gov.br/trabalho-e-emprego/pt-br/acesso-a-informacao/"
    "participacao-social/conselhos-e-orgaos-colegiados/"
    "comissao-tripartite-partitaria-permanente/"
    "normas-regulamentadora/normas-regulamentadoras-vigentes"
)

# ─── NR-1 tem página própria confirmada — monitoramos ela separadamente ──────
NR1_URL = f"{INDEX_URL}/nr-1"

# ─── Lista para exibição no site (links sempre para a índice) ────────────────
NR_DISPLAY = [
    {"nr": f"NR-{i}", "nome": nome, "url": INDEX_URL}
    for i, nome in enumerate([  # URLs individuais sobrescritas abaixo quando necessário
        "Disposições Gerais e Gerenciamento de Riscos Ocupacionais",
        "Inspeção Prévia (Revogada)",
        "Embargo e Interdição",
        "Serviços Especializados em Engenharia de Segurança e em Medicina do Trabalho",
        "Comissão Interna de Prevenção de Acidentes e de Assédio",
        "Equipamentos de Proteção Individual",
        "Programa de Controle Médico de Saúde Ocupacional",
        "Edificações",
        "Avaliação e Controle das Exposições Ocupacionais a Agentes Físicos, Químicos e Biológicos",
        "Segurança em Instalações e Serviços em Eletricidade",
        "Transporte, Movimentação, Armazenagem e Manuseio de Materiais",
        "Segurança no Trabalho em Máquinas e Equipamentos",
        "Caldeiras, Vasos de Pressão, Tubulações e Reservatórios Metálicos de Pressão",
        "Fornos",
        "Atividades e Operações Insalubres",
        "Atividades e Operações Perigosas",
        "Ergonomia",
        "Segurança e Saúde no Trabalho na Indústria da Construção",
        "Explosivos",
        "Segurança e Saúde no Trabalho com Inflamáveis e Combustíveis",
        "Trabalho a Céu Aberto",
        "Segurança e Saúde Ocupacional na Mineração",
        "Proteção Contra Incêndios",
        "Condições Sanitárias e de Conforto nos Locais de Trabalho",
        "Resíduos Industriais",
        "Sinalização de Segurança",
        "Registro Profissional do Técnico de Segurança do Trabalho (Revogada)",
        "Fiscalização e Penalidades",
        "Segurança e Saúde no Trabalho Portuário",
        "Segurança e Saúde no Trabalho Aquaviário",
        "Segurança e Saúde no Trabalho na Agricultura, Pecuária, Silvicultura, Exploração Florestal e Aquicultura",
        "Segurança e Saúde no Trabalho em Estabelecimentos de Saúde",
        "Segurança e Saúde nos Trabalhos em Espaços Confinados",
        "Condições e Meio Ambiente de Trabalho na Indústria da Construção, Reparação e Desmonte Naval",
        "Trabalho em Altura",
        "Segurança e Saúde no Trabalho em Empresas de Abate e Processamento de Carnes e Derivados",
        "Segurança e Saúde em Plataformas de Petróleo",
        "Segurança e Saúde no Trabalho nas Atividades de Limpeza Urbana e Manejo de Resíduos Sólidos",
    ], start=1)
]
# Corrige NR-1 para ter URL própria confirmada
NR_DISPLAY[0]["url"] = NR1_URL

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
        'User-Agent': 'Mozilla/5.0 (compatible; NR-Monitor/2.0)',
        'Accept': 'text/html,application/xhtml+xml;q=0.9,*/*;q=0.8',
        'Accept-Language': 'pt-BR,pt;q=0.9',
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
    # Remove datas e horários dinâmicos para evitar falsos positivos
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

    # ── Monitora a página índice principal ───────────────────────────────────
    pages_to_check = [
        ("__index__", "Página Índice MTE (todas as NR)", INDEX_URL, INDEX_URL),
        ("nr1",       "NR-1 (página individual)",         NR1_URL,   NR1_URL),
    ]

    for key, label, url, link in pages_to_check:
        print(f"  Verificando {label}...", end=" ", flush=True)
        html = fetch_page(url)
        if html is None:
            print("falha, pulando.")
            continue

        new_hash = page_hash(html)
        old_hash = state["hashes"].get(key)

        if old_hash is None:
            state["hashes"][key] = new_hash
            print("hash inicial registrado.")
        elif new_hash != old_hash:
            print("ALTERAÇÃO DETECTADA!")
            state["hashes"][key] = new_hash
            # Quando a índice muda, pode indicar qualquer NR — registra como geral
            change_entry = {
                "nr":       "MTE",
                "nome":     "Atualização detectada no portal de NR do Ministério do Trabalho",
                "url":      link,
                "data":     today_str,
                "data_fmt": now_brasilia().strftime('%d/%m/%Y'),
                "source":   "gov.br / MTE"
            }
            if key == "nr1":
                change_entry["nr"]   = "NR-1"
                change_entry["nome"] = "Disposições Gerais e Gerenciamento de Riscos Ocupacionais"
            changes_found.append(change_entry)
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
