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

import json, os, re, sys, time, hashlib
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


# O gov.br falha por timeout de forma intermitente: 6 das 28 execuções entre
# 02/09 e 14/09 morreram assim, sempre nas duas fontes do MTE (o DOU e a ABNT
# nunca falharam). Sem retry aqui, a única defesa era repetir o script inteiro
# no workflow — 12 minutos de runner para o que um backoff de 3 segundos
# resolve. Erro de rede é transitório; 404 não é, e não se repete.
TENTATIVAS = 3
BACKOFF_S = 3
TIMEOUT_S = 20


def fetch(url, timeout=TIMEOUT_S, tentativas=TENTATIVAS):
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 '
                      '(KHTML, like Gecko) Chrome/120.0 Safari/537.36',
        'Accept': 'text/html,application/xhtml+xml,application/json;q=0.9,*/*;q=0.8',
        'Accept-Language': 'pt-BR,pt;q=0.9',
    }
    ultimo = None
    for n in range(1, tentativas + 1):
        req = urllib.request.Request(url, headers=headers)
        try:
            with urllib.request.urlopen(req, timeout=timeout) as r:
                raw = r.read()
            try:
                return raw.decode('utf-8')
            except UnicodeDecodeError:
                return raw.decode('latin-1', errors='replace')
        except urllib.error.HTTPError as e:
            # 4xx é resposta definitiva do servidor: repetir não muda nada.
            if e.code < 500:
                raise SourceError(f"HTTP {e.code} em {url}")
            ultimo = f"HTTP {e.code}"
        except Exception as e:
            ultimo = type(e).__name__
        if n < tentativas:
            print(f"[{ultimo}, tentativa {n}/{tentativas}]", end=" ", flush=True)
            time.sleep(BACKOFF_S * n)      # 3s, depois 6s
    raise SourceError(f"{ultimo} em {url} após {tentativas} tentativas")


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
        return itens, False, []

    # Nada extraído: o HTML provavelmente mudou de estrutura. Não fingimos que
    # está tudo bem — voltamos ao hash e sinalizamos modo degradado.
    h = page_hash(html)
    return [{'iid': 'pagehash_' + h[:12],
             'titulo': f"Alteração detectada em: {cfg['label']}",
             'link': url_usada}], True, []


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


# A busca do in.gov.br NÃO pagina. Testado em 15/09/2026: currentPage, page,
# cur, o cur com namespace do portlet, start e offset — todos devolvem a mesma
# primeira página. O único controle que funciona é `delta`, e ele é uma lista
# branca: 50 devolve 50, mas 100, 200, 500 e 1000 caem de volta para o padrão
# de 20. Não há totalCount na resposta para saber quantos resultados existem.
#
# Portanto o teto é 50 por consulta, e é um teto SILENCIOSO: se uma semana
# tiver 60 publicações, as 10 últimas simplesmente não aparecem, sem erro.
#
# A saída não é paginar (não dá), é evitar que a consulta chegue ao teto:
# quando uma busca volta com 50 itens, ela é refeita dia a dia dentro da
# janela, porque um único dia dificilmente satura. E se nem assim couber, o
# fato é REGISTRADO em vez de engolido — falso negativo silencioso é o pior
# desfecho possível aqui.
DELTA_DOU = 50                 # maior valor aceito pelo portlet
MAX_CONSULTAS_DOU = 24         # trava de tempo: limita o desdobramento
FALHAS_SEGUIDAS_ABORTA = 3     # se o site caiu, não insiste 24 vezes


def _url_dou(termo, secao, de, ate):
    params = {
        'q': termo, 's': secao, 'exactDate': 'personalizado',
        'publishFrom': de.strftime('%d-%m-%Y'),
        'publishTo': ate.strftime('%d-%m-%Y'),
        'sortType': '0', 'delta': str(DELTA_DOU),
    }
    return 'https://www.in.gov.br/consulta/-/buscar/dou?' + urllib.parse.urlencode(params)


def _resultados_dou(html):
    """Extrai a lista de resultados do bloco JSON do portlet."""
    m = re.search(r'<script[^>]+id="[^"]*params"[^>]*>(.*?)</script>', html, re.S | re.I)
    if not m:
        return []
    try:
        dados = json.loads(m.group(1).strip())
    except json.JSONDecodeError:
        return []
    return _walk_for_results(dados) or []


def collect_dou(cfg):
    """Busca no DOU os termos configurados, sem deixar o teto de 50 cortar."""
    hoje = now_brasilia()
    dias = int(cfg.get('window_days', 7))
    inicio = hoje - timedelta(days=dias)

    itens, vistos = [], set()
    falhas, sucessos, consultas, seguidas = [], 0, 0, 0
    saturadas = []

    def consulta(termo, secao, de, ate):
        """Devolve (n_itens, saturou) e acumula em `itens`."""
        nonlocal sucessos, consultas, seguidas
        consultas += 1
        try:
            html = fetch(_url_dou(termo, secao, de, ate))
            seguidas = 0
        except SourceError as e:
            falhas.append(str(e))
            seguidas += 1
            return 0, False
        sucessos += 1
        brutos = _resultados_dou(html)
        for r in brutos:
            titulo = re.sub(r'\s+', ' ', re.sub(r'<[^>]+>', '', str(r.get('title', '')))).strip()
            if not titulo:
                continue
            url_titulo = r.get('urlTitle') or ''
            link = ('https://www.in.gov.br/web/dou/-/' + url_titulo) if url_titulo \
                   else _url_dou(termo, secao, de, ate)
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
                'orgao': (r.get('hierarchyStr') or r.get('pubName') or '')[:200],
                'ementa': re.sub(r'<[^>]+>', ' ', str(r.get('content') or ''))[:600].strip(),
            })
        return len(brutos), len(brutos) >= DELTA_DOU

    for secao in cfg.get('sections', ['do1']):
        for termo in cfg.get('queries', []):
            if seguidas >= FALHAS_SEGUIDAS_ABORTA:
                break
            n, saturou = consulta(termo, secao, inicio, hoje)
            if not saturou:
                continue

            # Bateu no teto: a janela inteira não cabe. Refaz dia a dia.
            print(f"\n    [teto de {DELTA_DOU} atingido em {termo} — refazendo dia a dia]",
                  end=" ", flush=True)
            ainda_saturado = []
            for d in range(dias + 1):
                if consultas >= MAX_CONSULTAS_DOU or seguidas >= FALHAS_SEGUIDAS_ABORTA:
                    break
                dia = inicio + timedelta(days=d)
                _, sat_dia = consulta(termo, secao, dia, dia)
                if sat_dia:
                    ainda_saturado.append(dia.strftime('%d/%m'))
            if ainda_saturado:
                saturadas.append(f"{termo} em {', '.join(ainda_saturado)}")

    if sucessos == 0:
        raise SourceError("nenhuma consulta ao DOU respondeu: " +
                          (" | ".join(falhas[:3]) or "sem detalhes"))

    # Um dia inteiro saturado significa que pode haver publicação não vista.
    # Isso vai para o estado e aparece no painel: nunca some em silêncio.
    if saturadas:
        print(f"\n    [AVISO: teto atingido mesmo por dia em {'; '.join(saturadas)}]",
              end=" ", flush=True)
    return itens, False, saturadas


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
        "total_nrs": None,   # derivado da página índice do MTE, não fixo
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

def load_config():
    with open(SOURCES_FILE, 'r', encoding='utf-8') as f:
        cfg = json.load(f)
    vocab = {
        'alta':     [re.compile(t, re.IGNORECASE) for t in cfg.get('termos_alta', [])],
        'possivel': [re.compile(t, re.IGNORECASE) for t in cfg.get('termos_possivel', [])],
    }
    return cfg['sources'], vocab


def prioridade_sst(texto, vocab):
    """
    Ordena, não descarta.

    Um vocabulário de palavras-chave sempre vai errar — a versão anterior,
    montada só com termos do MTE, barrava 10 de 10 atos de ANVISA, INMETRO,
    CONTRAN e INSS que geram adequação real. Por isso o resultado aqui não
    esconde nada: define apenas a ordem de leitura.

      alta     — SST direto (NR, PGR, LTCAT, ASO, insalubridade, ergonomia...)
      possivel — tema EHS adjacente (qualidade do ar, ruído, SPDA, eSocial...)
      baixa    — sem correspondência; vai recolhido para o fim, ainda clicável

    Falso negativo custa uma não-conformidade; falso positivo custa dez
    segundos de leitura. A assimetria decide o desenho.
    """
    if not vocab or not any(vocab.values()):
        return 'alta'
    if any(p.search(texto) for p in vocab.get('alta', [])):
        return 'alta'
    if any(p.search(texto) for p in vocab.get('possivel', [])):
        return 'possivel'
    return 'baixa'


def termos_encontrados(texto, vocab, limite=6):
    """Quais termos casaram — mostrado no painel para você poder calibrar."""
    achados = []
    for p in vocab.get('alta', []) + vocab.get('possivel', []):
        m = p.search(texto)
        if m and m.group(0).strip():
            t = m.group(0).strip()
            if t.lower() not in [a.lower() for a in achados]:
                achados.append(t)
        if len(achados) >= limite:
            break
    return achados


def extrai_nrs(itens):
    """
    Normaliza os links da página índice numa lista de NRs.

    Ordena pelo número da norma (NR-1, NR-2, ... NR-38), não alfabeticamente,
    senão NR-10 apareceria antes de NR-2. Itens sem número identificável são
    mantidos ao final, para nunca sumirem da tela.
    """
    vistos, nrs = set(), []
    for it in itens:
        titulo = re.sub(r'\s+', ' ', it.get('titulo', '')).strip()
        m = re.search(r'\bNR[\s\-–]?0*(\d{1,2})\b', titulo, re.IGNORECASE)
        num = int(m.group(1)) if m else None
        chave = num if num is not None else titulo.lower()
        if chave in vistos:
            continue
        vistos.add(chave)
        # "NR-06 — Equipamento de Proteção Individual" -> nome sem o prefixo
        nome = re.sub(r'^\s*NR[\s\-–]?0*\d{1,2}\s*[—–\-:.]*\s*', '', titulo,
                      flags=re.IGNORECASE).strip() or titulo
        nrs.append({
            'nr': f"NR-{num:02d}" if num is not None else titulo[:12],
            'num': num if num is not None else 999,
            'nome': nome[:160],
            'link': it.get('link', ''),
        })
    nrs.sort(key=lambda x: (x['num'], x['nr']))
    return nrs


def processa_fonte(cfg, state, agora, vocab=None):
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
        itens, degradado, avisos = coletor(cfg)
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
    # Teto da busca atingido: pode haver publicação que o monitor não viu.
    # Fica no estado para o painel mostrar — um limite silencioso seria a
    # pior forma de falhar numa ferramenta de compliance.
    saude["truncado"] = avisos or None

    conhecidos = set(saude.get("known_ids", []))
    primeira_vez = not conhecidos

    novos = []
    for it in itens:
        if it['iid'] in conhecidos:
            continue
        # Fontes do MTE/NR/ABNT já são específicas de SST por construção;
        # só o DOU, que é uma busca aberta no diário inteiro, precisa de triagem.
        alvo = ' '.join([it['titulo'], it.get('ementa', ''), it.get('orgao', '')])
        if cfg.get('kind') == 'dou_search':
            prio = prioridade_sst(alvo, vocab or {})
        else:
            prio = 'alta'   # MTE, índice NR e ABNT já são específicos por construção
        termos = termos_encontrados(alvo, vocab or {})

        novos.append({
            'id': f"{sid}_{it['iid']}",
            'titulo': it['titulo'],
            'link': it['link'],
            'fonte': cfg.get('label', sid),
            'busca': it.get('busca', 'monitoramento estruturado'),
            'data': agora.strftime('%Y-%m-%d'),
            'data_fmt': agora.strftime('%d/%m/%Y'),
            'tipo': cfg.get('tipo', 'MTE'),
            'orgao': it.get('orgao', ''),
            'ementa': it.get('ementa', ''),
            'prioridade': prio,
            'termos': termos,
            'relevante': prio != 'baixa',
        })

    # Guarda a lista atual como baseline (limitada, para o state não inchar).
    saude["known_ids"] = [it['iid'] for it in itens][-800:]

    # A página índice do MTE é a fonte oficial de QUAIS NRs existem. Guardamos a
    # lista para o painel exibir, em vez de manter uma cópia escrita à mão no
    # HTML: duas listas que não derivam uma da outra acabam divergindo, e o
    # painel mentiria justamente no dia em que uma NR nova aparecesse.
    if cfg.get('lista_nrs'):
        state["nrs"] = extrai_nrs(itens)
        state["total_nrs"] = len(state["nrs"])

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


def classifica_pendentes(state, vocab):
    """
    Classifica itens detectados antes da priorização existir.

    Sem isto, publicações antigas caem no padrão conservador ('alta') e o ruído
    do DOU continua no topo do painel por até sete dias. Roda uma vez por item:
    quem já tem prioridade não é tocado.

    Itens antigos não têm ementa nem órgão gravados, então a classificação usa
    só o título — é menos precisa. Por isso o desenho continua o mesmo: quem cai
    em 'baixa' segue visível na faixa recolhida, nunca sumindo da tela.
    """
    ajustados = 0
    for lista in ('publicacoes_recentes', 'history'):
        for p in state.get(lista, []):
            if 'prioridade' in p:
                continue
            alvo = ' '.join([p.get('titulo', ''), p.get('ementa', ''),
                             p.get('orgao', ''), p.get('fonte', '')])
            p['prioridade'] = ('alta' if p.get('tipo') != 'DOU'
                               else prioridade_sst(alvo, vocab))
            p.setdefault('termos', termos_encontrados(alvo, vocab))
            # Item anterior à coleta de ementa e órgão: só havia o título, e
            # título de ato do DOU raramente diz o assunto ("PORTARIA Nº 7.155,
            # DE 31 DE AGOSTO"). A classificação aqui é fraca, e o painel
            # precisa dizer isso — em vez de exibir como triagem confiável.
            if not p.get('ementa') and not p.get('orgao'):
                p['triagem_limitada'] = True
            ajustados += 1
    if ajustados:
        print(f"  [migração] {ajustados} publicação(ões) antiga(s) classificada(s).")


def run_check():
    agora = now_brasilia()
    print("\n" + "=" * 65)
    print(f"  Monitor SST v4 — {agora.strftime('%d/%m/%Y %H:%M')} (Brasília)")
    print("=" * 65)

    state = load_state()
    fontes, vocab = load_config()
    classifica_pendentes(state, vocab)

    vistos = {p.get('id') for p in state.get('history', [])}
    vistos |= {p.get('id') for p in state.get('publicacoes_recentes', [])}

    novos_total, falhas_criticas, fontes_ok = [], [], 0

    for cfg in fontes:
        novos, ok = processa_fonte(cfg, state, agora, vocab)
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
    elif [p for p in novos_total if p.get('prioridade', 'alta') == 'alta']:
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
    por_prio = {n: [p for p in novos_total if p.get('prioridade', 'alta') == n]
                for n in ('alta', 'possivel', 'baixa')}
    print(f"  Novas publicações: {len(novos_total)}"
          f"  (alta: {len(por_prio['alta'])},"
          f" possível: {len(por_prio['possivel'])},"
          f" baixa: {len(por_prio['baixa'])})")
    for rot, marca in (('alta', '●'), ('possivel', '○'), ('baixa', '·')):
        for p in por_prio[rot]:
            termos = f"  [{', '.join(p.get('termos', [])[:3])}]" if p.get('termos') else ''
            print(f"    {marca} [{p['tipo']}] {p['titulo'][:78]}{termos}")
    if falhas_criticas:
        print("  FALHAS:")
        for f in falhas_criticas:
            print(f"    ! {f}")
    print("─" * 65 + "\n")

    return 1 if falhas_criticas else 0


if __name__ == '__main__':
    sys.exit(run_check())
