"""
Monitor SST v4 — Segurança e Saúde no Trabalho

Monitora, em fontes oficiais, qualquer alteração que possa obrigar a empresa
a se adaptar: portarias do MTE, Normas Regulamentadoras, publicações do DOU
e normas técnicas (NBR).

Diferenças em relação à v3.1 (que falhava em silêncio):

  1. FALHA BARULHENTA — se uma fonte crítica não puder ser lida, o script
     termina com código de saída != 0 e o workflow fica vermelho. Antes,
     qualquer erro de rede virava "sem alteração" e o painel seguia verde.

  2. SAÚDE POR FONTE — o state.json passa a registrar, para cada fonte,
     quando ela foi lida com sucesso pela última vez, o último erro e há
     quantas execuções seguidas ela falha. O painel usa isso para mostrar
     "DESATUALIZADO" em vez de fingir normalidade.

  3. DIFF DE ITENS, NÃO HASH DE PÁGINA — em vez de comparar o hash do texto
     inteiro (que muda com banner, data de atualização ou notícia lateral),
     extraímos a lista de itens (links de portarias/NRs/NBRs) e comparamos
     conjuntos. Isso elimina o falso positivo e ainda diz QUAL item é novo.
     Se a extração não encontrar nada — sinal de que o HTML mudou —, a fonte
     cai para hash de página e é marcada como "degradada" no painel.

  4. DOU DE VERDADE — busca no in.gov.br pelos termos de SST numa janela de
     dias, em vez de depender só das páginas do MTE.

  5. FONTES DECLARATIVAS — a lista fica em data/sources.json. Para vigiar uma
     norma nova, basta acrescentar uma entrada lá.

Sem dependências externas: só biblioteca padrão do Python.
"""

import json, os, re, sys, hashlib
import urllib.request, urllib.error, urllib.parse
from datetime import datetime, timezone, timedelta
from html.parser import HTMLParser

SCHEMA_VERSION = 4
BRASILIA = timezone(timedelta(hours=-3))

def now_brasilia():
    return datetime.now(BRASILIA)

BASE_DIR     = os.path.dirname(os.path.abspath(__file__))
DATA_DIR     = os.path.join(BASE_DIR, '..', 'data')
STATE_FILE   = os.path.join(DATA_DIR, 'state.json')
SOURCES_FILE = os.path.join(DATA_DIR, 'sources.json')
os.makedirs(DATA_DIR, exist_ok=True)

# Nº de falhas seguidas de uma fonte NÃO-crítica antes de derrubar a execução.
# Uma falha isolada da ABNT não deve apagar o monitoramento do MTE, mas uma
# fonte quebrada há dias precisa aparecer.
NONCRITICAL_FAILURE_LIMIT = 3

MAX_HISTORY = 500          # itens guardados no histórico do painel
RECENT_WINDOW_DAYS = 7     # janela de "publicações recentes"


# ─── HTTP ─────────────────────────────────────────────────────────────────────

class SourceError(Exception):
    """Falha ao ler uma fonte. Propaga para virar erro visível."""


def fetch(url, timeout=45):
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 '
                      '(KHTML, like Gecko) Chrome/120.0 Safari/537.36',
        'Accept': 'text/html,application/xhtml+xml,application/json;q=0.9,*/*;q=0.8',
        'Accept-Language': 'pt-BR,pt;q=0.9',
    }
    req = urllib.request.Request(url, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            raw = r.read()
    except urllib.error.HTTPError as e:
        raise SourceError(f"HTTP {e.code} em {url}")
    except Exception as e:
        raise SourceError(f"{type(e).__name__} em {url}")
    try:
        return raw.decode('utf-8')
    except UnicodeDecodeError:
        return raw.decode('latin-1', errors='replace')


def fetch_first_available(urls):
    """Tenta cada URL na ordem. Devolve (html, url_usada)."""
    erros = []
    for url in urls:
        try:
            return fetch(url), url
        except SourceError as e:
            erros.append(str(e))
    raise SourceError(" | ".join(erros) if erros else "nenhuma URL configurada")


# ─── Parsing de HTML ──────────────────────────────────────────────────────────

class LinkExtractor(HTMLParser):
    """Coleta pares (texto, href) dos links da página."""
    def __init__(self):
        super().__init__()
        self.links = []
        self._href = None
        self._buf = []

    def handle_starttag(self, tag, attrs):
        if tag == 'a':
            self._href = dict(attrs).get('href')
            self._buf = []

    def handle_data(self, data):
        if self._href is not None:
            self._buf.append(data)

    def handle_endtag(self, tag):
        if tag == 'a' and self._href is not None:
            texto = re.sub(r'\s+', ' ', ''.join(self._buf)).strip()
            if texto:
                self.links.append((texto, self._href))
            self._href = None
            self._buf = []


class TextExtractor(HTMLParser):
    """Texto visível da página, para o hash de fallback."""
    SKIP = ('script', 'style', 'nav', 'footer', 'head', 'noscript')

    def __init__(self):
        super().__init__()
        self.texts = []
        self._skip = 0

    def handle_starttag(self, tag, attrs):
        if tag in self.SKIP:
            self._skip += 1

    def handle_endtag(self, tag):
        if tag in self.SKIP and self._skip:
            self._skip -= 1

    def handle_data(self, data):
        if not self._skip:
            s = data.strip()
            if s:
                self.texts.append(s)

    def get_text(self):
        return ' '.join(self.texts)


def strip_volatile(text):
    """Remove datas e horas, que mudam sem que a norma mude."""
    t = re.sub(r'\d{2}/\d{2}/\d{4}(\s+\d{2}[h:]\d{2})?', '', text)
    t = re.sub(r'\d{4}-\d{2}-\d{2}[T\d:.Z+-]*', '', t)
    t = re.sub(r'\s+', ' ', t)
    return t.strip()


def page_hash(html):
    p = TextExtractor()
    p.feed(html)
    return hashlib.md5(strip_volatile(p.get_text()).encode('utf-8')).hexdigest()


def item_id(titulo, link):
    chave = strip_volatile(titulo.lower()) + '|' + (link or '')
    return hashlib.md5(chave.encode('utf-8')).hexdigest()[:16]


# ─── Coletores por tipo de fonte ──────────────────────────────────────────────

def collect_page_items(cfg):
    """
    Lê a página e extrai os links cujo texto casa com item_pattern.
    Devolve (itens, degradado). Se nada casar, cai para hash da página.
    """
    urls = [cfg['url']] + list(cfg.get('url_fallbacks', []))
    year = now_brasilia().year
    urls = [u.replace('{YEAR}', str(year)).replace('{YEAR_PREV}', str(year - 1))
            for u in urls]

    html, url_usada = fetch_first_available(urls)
    padrao = re.compile(cfg.get('item_pattern', '.'), re.IGNORECASE)

    parser = LinkExtractor()
    parser.feed(html)

    itens, vistos = [], set()
    for texto, href in parser.links:
        if len(texto) < 6 or not padrao.search(texto):
            continue
        link = urllib.parse.urljoin(url_usada, href) if href else url_usada
        iid = item_id(texto, link)
        if iid in vistos:
            continue
        vistos.add(iid)
        itens.append({'iid': iid, 'titulo': texto[:300], 'link': link})

    if itens:
        return itens, False

    # Nada extraído: o HTML provavelmente mudou de estrutura. Não fingimos que
    # está tudo bem — voltamos ao hash e sinalizamos modo degradado.
    h = page_hash(html)
    return [{'iid': 'pagehash_' + h[:12],
             'titulo': f"Alteração detectada em: {cfg['label']}",
             'link': url_usada}], True


def _walk_for_results(obj):
    """Acha, no JSON do in.gov.br, a primeira lista de dicts com 'title'."""
    if isinstance(obj, list):
        if obj and isinstance(obj[0], dict) and 'title' in obj[0]:
            return obj
        for item in obj:
            achado = _walk_for_results(item)
            if achado:
                return achado
    elif isinstance(obj, dict):
        for valor in obj.values():
            achado = _walk_for_results(valor)
            if achado:
                return achado
    return None


def collect_dou(cfg):
    """Busca no DOU (in.gov.br) os termos configurados numa janela de dias."""
    hoje = now_brasilia()
    inicio = hoje - timedelta(days=int(cfg.get('window_days', 7)))
    itens, vistos, falhas, sucessos = [], set(), [], 0

    for secao in cfg.get('sections', ['do1']):
        for termo in cfg.get('queries', []):
            params = {
                'q': termo,
                's': secao,
                'exactDate': 'personalizado',
                'publishFrom': inicio.strftime('%d-%m-%Y'),
                'publishTo': hoje.strftime('%d-%m-%Y'),
                'sortType': '0',
            }
            url = 'https://www.in.gov.br/consulta/-/buscar/dou?' + urllib.parse.urlencode(params)
            try:
                html = fetch(url)
            except SourceError as e:
                falhas.append(str(e))
                continue

            sucessos += 1
            m = re.search(
                r'<script[^>]+id="params"[^>]*>(.*?)</script>', html, re.S | re.I)
            if not m:
                continue
            try:
                dados = json.loads(m.group(1).strip())
            except json.JSONDecodeError:
                continue

            for r in (_walk_for_results(dados) or []):
                titulo = re.sub(r'\s+', ' ', str(r.get('title', ''))).strip()
                if not titulo:
                    continue
                url_titulo = r.get('urlTitle') or ''
                link = ('https://www.in.gov.br/web/dou/-/' + url_titulo) if url_titulo else url
                iid = item_id(titulo, link)
                if iid in vistos:
                    continue
                vistos.add(iid)
                itens.append({
                    'iid': iid,
                    'titulo': titulo[:300],
                    'link': link,
                    'pub_date': r.get('pubDate') or '',
                    'busca': termo,
                })

    if sucessos == 0:
        raise SourceError("nenhuma consulta ao DOU respondeu: " +
                          (" | ".join(falhas) or "sem detalhes"))
    return itens, False


COLLECTORS = {
    'page_items': collect_page_items,
    'dou_search': collect_dou,
}


# ─── Estado ───────────────────────────────────────────────────────────────────

def novo_estado():
    return {
        "schema_version": SCHEMA_VERSION,
        "last_check": None,
        "last_success": None,
        "status": "Monitorando",
        "total_nrs": 38,
        "sources": {},
        "publicacoes_recentes": [],
        "recent_changes": [],
        "history": [],
    }


def load_state():
    if not os.path.exists(STATE_FILE):
        return novo_estado()
    try:
        with open(STATE_FILE, 'r', encoding='utf-8') as f:
            estado = json.load(f)
    except (json.JSONDecodeError, OSError) as e:
        print(f"  [aviso] state.json ilegível ({e}); recomeçando o estado.")
        return novo_estado()

    base = novo_estado()
    base.update(estado)
    base["schema_version"] = SCHEMA_VERSION
    base.setdefault("sources", {})
    # Migração da v3: hashes soltos viram baseline por fonte.
    for chave, h in (estado.get("hashes") or {}).items():
        sid = chave.strip('_')
        base["sources"].setdefault(sid, {})["page_hash"] = h
    base.pop("hashes", None)
    return base


def save_state(state):
    tmp = STATE_FILE + '.tmp'
    with open(tmp, 'w', encoding='utf-8') as f:
        json.dump(state, f, ensure_ascii=False, indent=2)
    os.replace(tmp, STATE_FILE)   # escrita atômica: nunca deixa JSON pela metade


# ─── Execução ─────────────────────────────────────────────────────────────────

def load_sources():
    with open(SOURCES_FILE, 'r', encoding='utf-8') as f:
        return json.load(f)['sources']


def processa_fonte(cfg, state, agora):
    """Roda uma fonte. Devolve (novos_itens, ok)."""
    sid = cfg['id']
    saude = state["sources"].setdefault(sid, {})
    saude["label"] = cfg.get('label', sid)
    saude["critical"] = bool(cfg.get('critical'))

    print(f"\n[ {cfg.get('label', sid)} ]")
    print("  Verificando...", end=" ", flush=True)

    coletor = COLLECTORS.get(cfg.get('kind'))
    if coletor is None:
        print(f"tipo de fonte desconhecido: {cfg.get('kind')}")
        saude["last_error"] = f"kind inválido: {cfg.get('kind')}"
        saude["consecutive_failures"] = saude.get("consecutive_failures", 0) + 1
        return [], False

    try:
        itens, degradado = coletor(cfg)
    except SourceError as e:
        print(f"FALHA — {e}")
        saude["last_error"] = str(e)
        saude["consecutive_failures"] = saude.get("consecutive_failures", 0) + 1
        return [], False

    saude["last_ok"] = agora.strftime('%d/%m/%Y %H:%M')
    saude["last_error"] = None
    saude["consecutive_failures"] = 0
    saude["degraded"] = degradado
    saude["item_count"] = len(itens)

    conhecidos = set(saude.get("known_ids", []))
    primeira_vez = not conhecidos

    novos = []
    for it in itens:
        if it['iid'] in conhecidos:
            continue
        novos.append({
            'id': f"{sid}_{it['iid']}",
            'titulo': it['titulo'],
            'link': it['link'],
            'fonte': cfg.get('label', sid),
            'busca': it.get('busca', 'monitoramento estruturado'),
            'data': agora.strftime('%Y-%m-%d'),
            'data_fmt': agora.strftime('%d/%m/%Y'),
            'tipo': cfg.get('tipo', 'MTE'),
        })

    # Guarda a lista atual como baseline (limitada, para o state não inchar).
    saude["known_ids"] = [it['iid'] for it in itens][-800:]

    if primeira_vez:
        print(f"baseline registrado ({len(itens)} itens).")
        return [], True
    if degradado:
        print(f"modo degradado (extração vazia) — {len(novos)} alteração(ões).")
    elif novos:
        print(f"{len(novos)} NOVO(S) ITEM(NS)!")
    else:
        print(f"sem alteração ({len(itens)} itens).")
    return novos, True


def run_check():
    agora = now_brasilia()
    print("\n" + "=" * 65)
    print(f"  Monitor SST v4 — {agora.strftime('%d/%m/%Y %H:%M')} (Brasília)")
    print("=" * 65)

    state = load_state()
    fontes = load_sources()

    vistos = {p.get('id') for p in state.get('history', [])}
    vistos |= {p.get('id') for p in state.get('publicacoes_recentes', [])}

    novos_total, falhas_criticas, fontes_ok = [], [], 0

    for cfg in fontes:
        novos, ok = processa_fonte(cfg, state, agora)
        if ok:
            fontes_ok += 1
        else:
            saude = state["sources"].get(cfg['id'], {})
            seguidas = saude.get("consecutive_failures", 0)
            if cfg.get('critical') or seguidas >= NONCRITICAL_FAILURE_LIMIT:
                falhas_criticas.append(
                    f"{cfg.get('label', cfg['id'])} ({seguidas}x seguidas): "
                    f"{saude.get('last_error')}")
        for p in novos:
            if p['id'] not in vistos:
                vistos.add(p['id'])
                novos_total.append(p)

    state["last_check"] = agora.strftime('%d/%m/%Y %H:%M')
    state["last_check_iso"] = agora.isoformat()
    state["sources_ok"] = fontes_ok
    state["sources_total"] = len(fontes)
    state["failures"] = falhas_criticas

    if falhas_criticas:
        state["status"] = "Falha na verificação"
    elif novos_total:
        state["status"] = "Nova Publicação"
        state["last_success"] = agora.isoformat()
    else:
        state["status"] = "Monitorando"
        state["last_success"] = agora.isoformat()

    if novos_total:
        state["publicacoes_recentes"] = state.get("publicacoes_recentes", []) + novos_total
        state["history"] = (state.get("history", []) + novos_total)[-MAX_HISTORY:]

    corte = agora - timedelta(days=RECENT_WINDOW_DAYS)
    recentes = []
    for p in state.get("publicacoes_recentes", []):
        try:
            d = datetime.strptime(p["data"], '%Y-%m-%d').replace(tzinfo=BRASILIA)
        except (KeyError, ValueError, TypeError):
            continue   # registro antigo malformado não derruba a execução
        if d >= corte:
            recentes.append(p)
    state["publicacoes_recentes"] = recentes
    state["recent_changes"] = recentes

    save_state(state)   # o estado é salvo ANTES de qualquer saída de erro,
                        # para que o painel consiga mostrar a falha.

    print("\n" + "─" * 65)
    print(f"  Status           : {state['status']}")
    print(f"  Horário          : {state['last_check']}")
    print(f"  Fontes OK        : {fontes_ok}/{len(fontes)}")
    print(f"  Novas publicações: {len(novos_total)}")
    for p in novos_total:
        print(f"    • [{p['tipo']}] {p['titulo'][:90]}")
    if falhas_criticas:
        print("  FALHAS:")
        for f in falhas_criticas:
            print(f"    ! {f}")
    print("─" * 65 + "\n")

    return 1 if falhas_criticas else 0


if __name__ == '__main__':
    sys.exit(run_check())
