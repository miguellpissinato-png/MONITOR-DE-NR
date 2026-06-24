import json
import os
import re
import hashlib
import urllib.request
import urllib.error
from urllib.parse import urljoin
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

# ─── Lista oficial das NR com URLs do gov.br ─────────────────────────────────
NR_LIST = [
    {"nr": "NR-1",  "nome": "Disposições Gerais e Gerenciamento de Riscos Ocupacionais", "url": "https://www.gov.br/trabalho-e-emprego/pt-br/acesso-a-informacao/participacao-social/conselhos-e-orgaos-colegiados/ctpp-nrs/normas-regulamentadoras-nrs/nr-01"},
    {"nr": "NR-2",  "nome": "Inspeção Prévia (Revogada)", "url": "https://www.gov.br/trabalho-e-emprego/pt-br/acesso-a-informacao/participacao-social/conselhos-e-orgaos-colegiados/ctpp-nrs/normas-regulamentadoras-nrs/nr-02"},
    {"nr": "NR-3",  "nome": "Embargo e Interdição", "url": "https://www.gov.br/trabalho-e-emprego/pt-br/acesso-a-informacao/participacao-social/conselhos-e-orgaos-colegiados/ctpp-nrs/normas-regulamentadoras-nrs/nr-03"},
    {"nr": "NR-4",  "nome": "Serviços Especializados em Engenharia de Segurança e em Medicina do Trabalho", "url": "https://www.gov.br/trabalho-e-emprego/pt-br/acesso-a-informacao/participacao-social/conselhos-e-orgaos-colegiados/ctpp-nrs/normas-regulamentadoras-nrs/nr-04"},
    {"nr": "NR-5",  "nome": "Comissão Interna de Prevenção de Acidentes e de Assédio", "url": "https://www.gov.br/trabalho-e-emprego/pt-br/acesso-a-informacao/participacao-social/conselhos-e-orgaos-colegiados/ctpp-nrs/normas-regulamentadoras-nrs/nr-05"},
    {"nr": "NR-6",  "nome": "Equipamentos de Proteção Individual", "url": "https://www.gov.br/trabalho-e-emprego/pt-br/acesso-a-informacao/participacao-social/conselhos-e-orgaos-colegiados/ctpp-nrs/normas-regulamentadoras-nrs/nr-06"},
    {"nr": "NR-7",  "nome": "Programa de Controle Médico de Saúde Ocupacional", "url": "https://www.gov.br/trabalho-e-emprego/pt-br/acesso-a-informacao/participacao-social/conselhos-e-orgaos-colegiados/ctpp-nrs/normas-regulamentadoras-nrs/nr-07"},
    {"nr": "NR-8",  "nome": "Edificações", "url": "https://www.gov.br/trabalho-e-emprego/pt-br/acesso-a-informacao/participacao-social/conselhos-e-orgaos-colegiados/ctpp-nrs/normas-regulamentadoras-nrs/nr-08"},
    {"nr": "NR-9",  "nome": "Avaliação e Controle das Exposições Ocupacionais a Agentes Físicos, Químicos e Biológicos", "url": "https://www.gov.br/trabalho-e-emprego/pt-br/acesso-a-informacao/participacao-social/conselhos-e-orgaos-colegiados/ctpp-nrs/normas-regulamentadoras-nrs/nr-09"},
    {"nr": "NR-10", "nome": "Segurança em Instalações e Serviços em Eletricidade", "url": "https://www.gov.br/trabalho-e-emprego/pt-br/acesso-a-informacao/participacao-social/conselhos-e-orgaos-colegiados/ctpp-nrs/normas-regulamentadoras-nrs/nr-10"},
    {"nr": "NR-11", "nome": "Transporte, Movimentação, Armazenagem e Manuseio de Materiais", "url": "https://www.gov.br/trabalho-e-emprego/pt-br/acesso-a-informacao/participacao-social/conselhos-e-orgaos-colegiados/ctpp-nrs/normas-regulamentadoras-nrs/nr-11"},
    {"nr": "NR-12", "nome": "Segurança no Trabalho em Máquinas e Equipamentos", "url": "https://www.gov.br/trabalho-e-emprego/pt-br/acesso-a-informacao/participacao-social/conselhos-e-orgaos-colegiados/ctpp-nrs/normas-regulamentadoras-nrs/nr-12"},
    {"nr": "NR-13", "nome": "Caldeiras, Vasos de Pressão, Tubulações e Reservatórios Metálicos de Pressão", "url": "https://www.gov.br/trabalho-e-emprego/pt-br/acesso-a-informacao/participacao-social/conselhos-e-orgaos-colegiados/ctpp-nrs/normas-regulamentadoras-nrs/nr-13"},
    {"nr": "NR-14", "nome": "Fornos", "url": "https://www.gov.br/trabalho-e-emprego/pt-br/acesso-a-informacao/participacao-social/conselhos-e-orgaos-colegiados/ctpp-nrs/normas-regulamentadoras-nrs/nr-14"},
    {"nr": "NR-15", "nome": "Atividades e Operações Insalubres", "url": "https://www.gov.br/trabalho-e-emprego/pt-br/acesso-a-informacao/participacao-social/conselhos-e-orgaos-colegiados/ctpp-nrs/normas-regulamentadoras-nrs/nr-15"},
    {"nr": "NR-16", "nome": "Atividades e Operações Perigosas", "url": "https://www.gov.br/trabalho-e-emprego/pt-br/acesso-a-informacao/participacao-social/conselhos-e-orgaos-colegiados/ctpp-nrs/normas-regulamentadoras-nrs/nr-16"},
    {"nr": "NR-17", "nome": "Ergonomia", "url": "https://www.gov.br/trabalho-e-emprego/pt-br/acesso-a-informacao/participacao-social/conselhos-e-orgaos-colegiados/ctpp-nrs/normas-regulamentadoras-nrs/nr-17"},
    {"nr": "NR-18", "nome": "Segurança e Saúde no Trabalho na Indústria da Construção", "url": "https://www.gov.br/trabalho-e-emprego/pt-br/acesso-a-informacao/participacao-social/conselhos-e-orgaos-colegiados/ctpp-nrs/normas-regulamentadoras-nrs/nr-18"},
    {"nr": "NR-19", "nome": "Explosivos", "url": "https://www.gov.br/trabalho-e-emprego/pt-br/acesso-a-informacao/participacao-social/conselhos-e-orgaos-colegiados/ctpp-nrs/normas-regulamentadoras-nrs/nr-19"},
    {"nr": "NR-20", "nome": "Segurança e Saúde no Trabalho com Inflamáveis e Combustíveis", "url": "https://www.gov.br/trabalho-e-emprego/pt-br/acesso-a-informacao/participacao-social/conselhos-e-orgaos-colegiados/ctpp-nrs/normas-regulamentadoras-nrs/nr-20"},
    {"nr": "NR-21", "nome": "Trabalho a Céu Aberto", "url": "https://www.gov.br/trabalho-e-emprego/pt-br/acesso-a-informacao/participacao-social/conselhos-e-orgaos-colegiados/ctpp-nrs/normas-regulamentadoras-nrs/nr-21"},
    {"nr": "NR-22", "nome": "Segurança e Saúde Ocupacional na Mineração", "url": "https://www.gov.br/trabalho-e-emprego/pt-br/acesso-a-informacao/participacao-social/conselhos-e-orgaos-colegiados/ctpp-nrs/normas-regulamentadoras-nrs/nr-22"},
    {"nr": "NR-23", "nome": "Proteção Contra Incêndios", "url": "https://www.gov.br/trabalho-e-emprego/pt-br/acesso-a-informacao/participacao-social/conselhos-e-orgaos-colegiados/ctpp-nrs/normas-regulamentadoras-nrs/nr-23"},
    {"nr": "NR-24", "nome": "Condições Sanitárias e de Conforto nos Locais de Trabalho", "url": "https://www.gov.br/trabalho-e-emprego/pt-br/acesso-a-informacao/participacao-social/conselhos-e-orgaos-colegiados/ctpp-nrs/normas-regulamentadoras-nrs/nr-24"},
    {"nr": "NR-25", "nome": "Resíduos Industriais", "url": "https://www.gov.br/trabalho-e-emprego/pt-br/acesso-a-informacao/participacao-social/conselhos-e-orgaos-colegiados/ctpp-nrs/normas-regulamentadoras-nrs/nr-25"},
    {"nr": "NR-26", "nome": "Sinalização de Segurança", "url": "https://www.gov.br/trabalho-e-emprego/pt-br/acesso-a-informacao/participacao-social/conselhos-e-orgaos-colegiados/ctpp-nrs/normas-regulamentadoras-nrs/nr-26"},
    {"nr": "NR-27", "nome": "Registro Profissional do Técnico de Segurança do Trabalho (Revogada)", "url": "https://www.gov.br/trabalho-e-emprego/pt-br/acesso-a-informacao/participacao-social/conselhos-e-orgaos-colegiados/ctpp-nrs/normas-regulamentadoras-nrs/nr-27"},
    {"nr": "NR-28", "nome": "Fiscalização e Penalidades", "url": "https://www.gov.br/trabalho-e-emprego/pt-br/acesso-a-informacao/participacao-social/conselhos-e-orgaos-colegiados/ctpp-nrs/normas-regulamentadoras-nrs/nr-28"},
    {"nr": "NR-29", "nome": "Norma Regulamentadora de Segurança e Saúde no Trabalho Portuário", "url": "https://www.gov.br/trabalho-e-emprego/pt-br/acesso-a-informacao/participacao-social/conselhos-e-orgaos-colegiados/ctpp-nrs/normas-regulamentadoras-nrs/nr-29"},
    {"nr": "NR-30", "nome": "Segurança e Saúde no Trabalho Aquaviário", "url": "https://www.gov.br/trabalho-e-emprego/pt-br/acesso-a-informacao/participacao-social/conselhos-e-orgaos-colegiados/ctpp-nrs/normas-regulamentadoras-nrs/nr-30"},
    {"nr": "NR-31", "nome": "Segurança e Saúde no Trabalho na Agricultura, Pecuária, Silvicultura, Exploração Florestal e Aquicultura", "url": "https://www.gov.br/trabalho-e-emprego/pt-br/acesso-a-informacao/participacao-social/conselhos-e-orgaos-colegiados/ctpp-nrs/normas-regulamentadoras-nrs/nr-31"},
    {"nr": "NR-32", "nome": "Segurança e Saúde no Trabalho em Estabelecimentos de Saúde", "url": "https://www.gov.br/trabalho-e-emprego/pt-br/acesso-a-informacao/participacao-social/conselhos-e-orgaos-colegiados/ctpp-nrs/normas-regulamentadoras-nrs/nr-32"},
    {"nr": "NR-33", "nome": "Segurança e Saúde nos Trabalhos em Espaços Confinados", "url": "https://www.gov.br/trabalho-e-emprego/pt-br/acesso-a-informacao/participacao-social/conselhos-e-orgaos-colegiados/ctpp-nrs/normas-regulamentadoras-nrs/nr-33"},
    {"nr": "NR-34", "nome": "Condições e Meio Ambiente de Trabalho na Indústria da Construção, Reparação e Desmonte Naval", "url": "https://www.gov.br/trabalho-e-emprego/pt-br/acesso-a-informacao/participacao-social/conselhos-e-orgaos-colegiados/ctpp-nrs/normas-regulamentadoras-nrs/nr-34"},
    {"nr": "NR-35", "nome": "Trabalho em Altura", "url": "https://www.gov.br/trabalho-e-emprego/pt-br/acesso-a-informacao/participacao-social/conselhos-e-orgaos-colegiados/ctpp-nrs/normas-regulamentadoras-nrs/nr-35"},
    {"nr": "NR-36", "nome": "Segurança e Saúde no Trabalho em Empresas de Abate e Processamento de Carnes e Derivados", "url": "https://www.gov.br/trabalho-e-emprego/pt-br/acesso-a-informacao/participacao-social/conselhos-e-orgaos-colegiados/ctpp-nrs/normas-regulamentadoras-nrs/nr-36"},
    {"nr": "NR-37", "nome": "Segurança e Saúde em Plataformas de Petróleo", "url": "https://www.gov.br/trabalho-e-emprego/pt-br/acesso-a-informacao/participacao-social/conselhos-e-orgaos-colegiados/ctpp-nrs/normas-regulamentadoras-nrs/nr-37"},
    {"nr": "NR-38", "nome": "Segurança e Saúde no Trabalho nas Atividades de Limpeza Urbana e Manejo de Resíduos Sólidos", "url": "https://www.gov.br/trabalho-e-emprego/pt-br/acesso-a-informacao/participacao-social/conselhos-e-orgaos-colegiados/ctpp-nrs/normas-regulamentadoras-nrs/nr-38"},
]

# ─── Parser HTML simples para extrair texto limpo ───────────────────────────
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


def fetch_page(url, timeout=20):
    """Faz requisição HTTP e retorna o HTML como texto."""
    headers = {
        'User-Agent': 'Mozilla/5.0 (compatible; NR-Monitor/2.0; +https://github.com)'
    }
    req = urllib.request.Request(url, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            raw = resp.read()
            # tenta utf-8, depois latin-1
            try:
                return raw.decode('utf-8')
            except UnicodeDecodeError:
                return raw.decode('latin-1', errors='replace')
    except Exception as e:
        print(f"  [ERRO ao buscar {url}]: {e}")
        return None


def page_hash(html_text):
    """Gera um hash MD5 do conteúdo textual relevante da página."""
    parser = TextExtractor()
    parser.feed(html_text)
    clean = parser.get_text()
    # remove datas dinâmicas que mudam sem indicar alteração de conteúdo
    clean = re.sub(r'\d{2}/\d{2}/\d{4}', '', clean)
    clean = re.sub(r'\d{4}-\d{2}-\d{2}', '', clean)
    return hashlib.md5(clean.encode('utf-8')).hexdigest()



# ─── Descobre automaticamente os links atuais das NRs no gov.br ─────────────
class LinkExtractor(HTMLParser):
    def __init__(self, base_url):
        super().__init__()
        self.base_url = base_url
        self.links = []
        self._href = None
        self._text = []

    def handle_starttag(self, tag, attrs):
        if tag == 'a':
            attrs = dict(attrs)
            self._href = attrs.get('href')
            self._text = []

    def handle_data(self, data):
        if self._href:
            stripped = data.strip()
            if stripped:
                self._text.append(stripped)

    def handle_endtag(self, tag):
        if tag == 'a' and self._href:
            text = ' '.join(self._text).strip()
            href = urljoin(self.base_url, self._href)
            self.links.append((text, href))
            self._href = None
            self._text = []


def extract_nr_links(html_text, base_url):
    """Extrai da página índice os links atuais de cada NR."""
    parser = LinkExtractor(base_url)
    parser.feed(html_text)

    nr_urls = {}

    for text, href in parser.links:
        combined = f"{text} {href}"

        # Pega padrões como NR-1, NR-01, nr-31 ou norma-regulamentadora-no-31-nr-31
        match = re.search(
            r'(?:\bNR[-\s]?0?(\d{1,2})\b|norma-regulamentadora-no-0?(\d{1,2})-nr-0?\d{1,2})',
            combined,
            re.IGNORECASE
        )

        if match and 'normas-regulamentadoras-vigentes' in href:
            numero = match.group(1) or match.group(2)
            nr_key = f"NR-{int(numero)}"
            nr_urls[nr_key] = href

    return nr_urls


def fallback_nr_url(nr):
    """Plano B caso a extração automática da página índice falhe."""
    base_url = "https://www.gov.br/trabalho-e-emprego/pt-br/acesso-a-informacao/participacao-social/conselhos-e-orgaos-colegiados/comissao-tripartite-partitaria-permanente/normas-regulamentadora/normas-regulamentadoras-vigentes"

    numero = int(re.sub(r'\D', '', nr))

    if numero == 1:
        return f"{base_url}/nr-1"

    return f"{base_url}/norma-regulamentadora-no-{numero}-nr-{numero}"


# ─── Carregar e salvar estado ────────────────────────────────────────────────
def load_state():
    if os.path.exists(STATE_FILE):
        with open(STATE_FILE, 'r', encoding='utf-8') as f:
            return json.load(f)
    return {
        "last_check": None,
        "status": "Monitorando",
        "hashes": {},
        "recent_changes": [],
        "history": []
    }


def save_state(state):
    with open(STATE_FILE, 'w', encoding='utf-8') as f:
        json.dump(state, f, ensure_ascii=False, indent=2)


# ─── Verificação principal ───────────────────────────────────────────────────
def run_check():
    print(f"\n{'='*60}")
    print(f"  Monitor de NR — {now_brasilia().strftime('%d/%m/%Y %H:%M')} (Brasília)")
    print(f"{'='*60}\n")

    state = load_state()
    changes_found = []
    today_str = now_brasilia().strftime('%Y-%m-%d')
    now_str   = now_brasilia().strftime('%d/%m/%Y %H:%M')

    # ── Busca a página índice do MTE (hash geral também) ────────────────────
    INDEX_URL = "https://www.gov.br/trabalho-e-emprego/pt-br/acesso-a-informacao/participacao-social/conselhos-e-orgaos-colegiados/comissao-tripartite-partitaria-permanente/normas-regulamentadora/normas-regulamentadoras-vigentes"
    print("Verificando página índice do MTE...")
    index_html = fetch_page(INDEX_URL)
    nr_urls = {}
    if index_html:
        idx_hash = page_hash(index_html)
        old_idx = state["hashes"].get("__index__")
        if old_idx and idx_hash != old_idx:
            print("  → Alteração detectada na página índice do MTE!")
        state["hashes"]["__index__"] = idx_hash

        nr_urls = extract_nr_links(index_html, INDEX_URL)
        print(f"  → {len(nr_urls)} URLs de NRs encontradas na página índice.")

    # ── Verifica cada NR individualmente ────────────────────────────────────
    for nr_info in NR_LIST:
        nr_key = nr_info["nr"].lower().replace("-", "")
        print(f"  Verificando {nr_info['nr']}...", end=" ")
        current_url = nr_urls.get(nr_info["nr"]) or fallback_nr_url(nr_info["nr"])
        html = fetch_page(current_url)
        if html is None:
            print("falha na requisição, pulando.")
            continue

        new_hash = page_hash(html)
        old_hash = state["hashes"].get(nr_key)

        if old_hash is None:
            # primeira execução: apenas registra o hash
            state["hashes"][nr_key] = new_hash
            print("hash inicial registrado.")
        elif new_hash != old_hash:
            print(f"ALTERAÇÃO DETECTADA!")
            state["hashes"][nr_key] = new_hash
            change_entry = {
                "nr":    nr_info["nr"],
                "nome":  nr_info["nome"],
                "url":   current_url,
                "data":  today_str,
                "data_fmt": now_brasilia().strftime('%d/%m/%Y'),
                "source": "gov.br / MTE"
            }
            changes_found.append(change_entry)
        else:
            print("sem alteração.")

    # ── Atualiza estado ──────────────────────────────────────────────────────
    state["last_check"] = now_str
    state["total_nrs"]  = len(NR_LIST)

    if changes_found:
        state["status"] = "Alteração Detectada"
        # adiciona às recentes (evita duplicatas no mesmo dia)
        existing_keys = {(c["nr"], c["data"]) for c in state["recent_changes"]}
        for c in changes_found:
            if (c["nr"], c["data"]) not in existing_keys:
                state["recent_changes"].append(c)

        # mantém no histórico permanentemente
        hist_keys = {(c["nr"], c["data"]) for c in state["history"]}
        for c in changes_found:
            if (c["nr"], c["data"]) not in hist_keys:
                state["history"].append(c)
    else:
        state["status"] = "Monitorando"

    # ── Remove da lista recente alterações com mais de 7 dias ───────────────
    cutoff = now_brasilia() - timedelta(days=7)
    state["recent_changes"] = [
        c for c in state["recent_changes"]
        if datetime.strptime(c["data"], '%Y-%m-%d').replace(tzinfo=BRASILIA) >= cutoff
    ]

    save_state(state)

    print(f"\n{'─'*60}")
    print(f"  Status final : {state['status']}")
    print(f"  Última check : {state['last_check']}")
    print(f"  Alterações   : {len(changes_found)}")
    print(f"{'─'*60}\n")


if __name__ == '__main__':
    run_check()
