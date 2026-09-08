"""
Gerador de relatório SST — análise de aplicabilidade

Lê as publicações que o monitor detectou e ainda não foram relatadas, busca o
texto integral de cada uma, pede à API da Claude uma análise de aplicabilidade
por tipo de unidade e emite um PDF formatado.

PRINCÍPIOS DE PROJETO

1. TRIAGEM, NÃO PARECER. Um modelo de linguagem pode interpretar mal texto
   normativo. O relatório existe para poupar a leitura de dezenas de diários,
   não para substituir o julgamento do profissional de SESMT. Todo item traz o
   link do texto original, e a decisão de compliance é sempre humana.

2. NADA DESAPARECE EM SILÊNCIO. Itens classificados como baixa relevância não
   são apagados: vão para a seção "descartados" do PDF, com o motivo. Se a
   triagem errar, o erro fica visível — e não enterrado.

3. FALHA NÃO INVALIDA O MONITOR. Sem chave de API, ou se a análise falhar, o
   script encerra sem erro e o monitoramento segue funcionando normalmente.
   O relatório é uma camada a mais, não um ponto único de falha.

4. SEM DADOS IDENTIFICÁVEIS. O perfil das unidades é genérico por decisão
   deliberada, porque este repositório é público.
"""

import json, os, re, sys
from datetime import datetime, timezone, timedelta

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from check_nr import (fetch, SourceError, TextExtractor, BRASILIA, now_brasilia,
                      load_config, prioridade_sst)

BASE_DIR    = os.path.dirname(os.path.abspath(__file__))
DATA_DIR    = os.path.join(BASE_DIR, '..', 'data')
REL_DIR     = os.path.join(BASE_DIR, '..', 'relatorios')
STATE_FILE  = os.path.join(DATA_DIR, 'state.json')
PERFIL_FILE = os.path.join(DATA_DIR, 'perfil_unidades.json')

MODELO = "claude-opus-5"
MAX_ITENS_POR_EXECUCAO = 15     # trava de custo: nunca analisa mais que isso
MAX_CHARS_TEXTO = 24000         # ~6k tokens por ato


# ─── Análise ──────────────────────────────────────────────────────────────────

ESQUEMA_ANALISE = {
    "type": "object",
    "properties": {
        "aplica_se": {
            "type": "boolean",
            "description": "true se a norma impacta ao menos uma das unidades do perfil"},
        "confianca": {
            "type": "string", "enum": ["alta", "media", "baixa"],
            "description": "confiança na própria análise; baixa quando o texto for ambíguo ou incompleto"},
        "urgencia": {
            "type": "string", "enum": ["critica", "alta", "media", "baixa", "informativa"]},
        "resumo": {
            "type": "string", "description": "2 a 4 frases: o que este ato é e o que ele faz"},
        "o_que_mudou": {
            "type": "string", "description": "a alteração concreta; se for norma nova, diga isso"},
        "unidades_afetadas": {
            "type": "array", "items": {"type": "string"},
            "description": "ids das unidades afetadas, do perfil fornecido; vazio se nenhuma"},
        "nrs_relacionadas": {
            "type": "array", "items": {"type": "string"},
            "description": "NRs ou normas citadas, ex.: 'NR-17 Anexo II'"},
        "prazo": {
            "type": "string",
            "description": "prazo de adequação ou vigência; string vazia se o texto não trouxer"},
        "requer_leitura_original": {
            "type": "boolean",
            "description": "true quando o texto for complexo o bastante para exigir leitura na íntegra"},
        "justificativa": {
            "type": "string",
            "description": "por que se aplica ou não se aplica, citando a unidade e a atividade"},
    },
    "required": ["aplica_se", "confianca", "urgencia", "resumo", "o_que_mudou",
                 "unidades_afetadas", "nrs_relacionadas", "prazo",
                 "requer_leitura_original", "justificativa"],
    "additionalProperties": False,
}

INSTRUCOES = """Você analisa publicações oficiais brasileiras para uma equipe de SESMT/EHS.

Sua tarefa: dizer se o ato abaixo impacta as unidades descritas no perfil, e como.

Regras:
- Baseie-se SOMENTE no texto fornecido. Não presuma conteúdo que não está ali.
- Se o texto vier truncado, incompleto ou ilegível, diga isso em `justificativa`,
  marque `confianca` como "baixa" e `requer_leitura_original` como true.
- Na dúvida sobre aplicabilidade, prefira marcar que se aplica e sinalizar
  confiança baixa. Um falso alarme custa uma leitura; um falso negativo custa
  uma não-conformidade.
- `unidades_afetadas` deve conter apenas ids que existem no perfil.
- Seja concreto: "altera o item 17.6.3, que trata de pausas no teleatendimento"
  vale mais que "traz alterações relevantes".
- Não recomende plano de ação nem prazos de implementação — isso cabe ao
  profissional responsável. Descreva o que mudou e a quem se aplica."""


def texto_integral(item):
    """Busca o texto do ato. Devolve (texto, erro)."""
    link = item.get('link')
    if not link:
        return '', 'sem link'
    try:
        html = fetch(link, timeout=40)
    except SourceError as e:
        return '', str(e)
    p = TextExtractor()
    p.feed(html)
    texto = re.sub(r'\s+', ' ', p.get_text()).strip()
    if len(texto) < 200:
        return texto, 'texto muito curto — página pode exigir JavaScript'
    return texto[:MAX_CHARS_TEXTO], None


def analisa(client, item, perfil):
    """Analisa um item. Devolve (analise_dict, erro)."""
    texto, erro_fetch = texto_integral(item)
    if not texto:
        return None, f"não foi possível ler o texto ({erro_fetch})"

    conteudo = (
        f"PERFIL DAS UNIDADES:\n{json.dumps(perfil, ensure_ascii=False, indent=2)}\n\n"
        f"---\n\nATO A ANALISAR\n"
        f"Título: {item.get('titulo')}\n"
        f"Órgão: {item.get('orgao') or 'não informado'}\n"
        f"Publicado em: {item.get('data_fmt')}\n"
        f"Fonte: {item.get('fonte')}\n\n"
        f"TEXTO:\n{texto}"
    )
    if erro_fetch:
        conteudo += f"\n\n[AVISO DE COLETA: {erro_fetch}]"

    try:
        resp = client.messages.create(
            model=MODELO,
            max_tokens=16000,
            system=INSTRUCOES,
            messages=[{"role": "user", "content": conteudo}],
            output_config={"format": {"type": "json_schema", "schema": ESQUEMA_ANALISE}},
        )
    except Exception as e:
        return None, f"{type(e).__name__}: {e}"

    # Uma recusa do modelo não pode virar silêncio: o item segue no relatório
    # marcado como não analisado, para leitura manual.
    if getattr(resp, 'stop_reason', None) == 'refusal':
        return None, "o modelo declinou de analisar este texto"

    try:
        bloco = next(b.text for b in resp.content if b.type == 'text')
        return json.loads(bloco), None
    except (StopIteration, json.JSONDecodeError, AttributeError) as e:
        return None, f"resposta ilegível ({type(e).__name__})"


# ─── PDF ──────────────────────────────────────────────────────────────────────

CORES_URGENCIA = {
    'critica':     ('#7f1d1d', 'CRÍTICA'),
    'alta':        ('#b45309', 'ALTA'),
    'media':       ('#1565c0', 'MÉDIA'),
    'baixa':       ('#475569', 'BAIXA'),
    'informativa': ('#475569', 'INFORMATIVA'),
}

AVISO_LEGAL = (
    "Este relatório é uma <b>triagem automatizada</b> produzida por inteligência "
    "artificial a partir do texto publicado nas fontes oficiais. Ele existe para "
    "reduzir o volume de leitura diária, <b>não para substituir a análise do "
    "profissional responsável</b>. Modelos de linguagem podem interpretar "
    "incorretamente texto normativo — prazos, exceções e revogações em especial. "
    "Antes de qualquer decisão de conformidade, consulte o texto original pelo "
    "link de cada item. A responsabilidade técnica permanece integralmente humana."
)


def escapa(t):
    return (str(t or '').replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;'))


def monta_pdf(caminho, agora, analisados, descartados, falhas, perfil):
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
    from reportlab.lib.units import mm
    from reportlab.lib import colors
    from reportlab.platypus import (SimpleDocTemplate, Paragraph, Spacer,
                                    Table, TableStyle, HRFlowable)

    ss = getSampleStyleSheet()
    est = {
        'titulo':  ParagraphStyle('t', parent=ss['Title'], fontSize=19, spaceAfter=2,
                                  textColor=colors.HexColor('#0d1f3c')),
        'sub':     ParagraphStyle('s', parent=ss['Normal'], fontSize=9.5,
                                  textColor=colors.HexColor('#64748b'), spaceAfter=2),
        'h2':      ParagraphStyle('h2', parent=ss['Heading2'], fontSize=12.5, spaceBefore=14,
                                  spaceAfter=6, textColor=colors.HexColor('#0d1f3c')),
        'item':    ParagraphStyle('i', parent=ss['Heading3'], fontSize=10.5, spaceAfter=3,
                                  textColor=colors.HexColor('#0d1f3c')),
        'corpo':   ParagraphStyle('c', parent=ss['Normal'], fontSize=9.3, leading=13.5,
                                  spaceAfter=4),
        'meta':    ParagraphStyle('m', parent=ss['Normal'], fontSize=8,
                                  textColor=colors.HexColor('#64748b'), spaceAfter=3),
        'aviso':   ParagraphStyle('a', parent=ss['Normal'], fontSize=8.2, leading=11.5,
                                  textColor=colors.HexColor('#7f1d1d')),
    }

    doc = SimpleDocTemplate(
        caminho, pagesize=A4,
        leftMargin=18*mm, rightMargin=18*mm, topMargin=16*mm, bottomMargin=18*mm,
        title=f"Relatório SST — {agora.strftime('%d/%m/%Y')}",
        author="Monitor SST")
    el = []

    # Cabeçalho
    el.append(Paragraph("Relatório de Monitoramento — SST", est['titulo']))
    el.append(Paragraph(
        f"Segurança e Saúde no Trabalho &nbsp;|&nbsp; "
        f"Emitido em {agora.strftime('%d/%m/%Y às %H:%M')} (Brasília)", est['sub']))
    el.append(HRFlowable(width='100%', thickness=1.1,
                         color=colors.HexColor('#1565c0'), spaceBefore=6, spaceAfter=10))

    # Resumo
    aplicaveis = [a for a in analisados if a['analise']['aplica_se']]
    linhas = [['Publicações analisadas', str(len(analisados))],
              ['Com impacto potencial',  str(len(aplicaveis))],
              ['Sem impacto identificado', str(len(analisados) - len(aplicaveis))],
              ['Sem correspondência (listadas, não analisadas)', str(len(descartados))]]
    if falhas:
        linhas.append(['Não analisadas por falha', str(len(falhas))])
    t = Table(linhas, colWidths=[95*mm, 25*mm])
    t.setStyle(TableStyle([
        ('FONTSIZE', (0,0), (-1,-1), 9),
        ('TEXTCOLOR', (0,0), (0,-1), colors.HexColor('#334155')),
        ('ALIGN', (1,0), (1,-1), 'RIGHT'),
        ('FONTNAME', (1,0), (1,-1), 'Helvetica-Bold'),
        ('BOTTOMPADDING', (0,0), (-1,-1), 4), ('TOPPADDING', (0,0), (-1,-1), 4),
        ('LINEBELOW', (0,0), (-1,-2), 0.3, colors.HexColor('#e2e8f0')),
    ]))
    el.append(t)

    # Itens com impacto
    if aplicaveis:
        el.append(Paragraph("Publicações com impacto potencial", est['h2']))
        for n, a in enumerate(aplicaveis, 1):
            el += bloco_item(n, a, perfil, est, colors, Paragraph, Spacer, HRFlowable)

    sem_impacto = [a for a in analisados if not a['analise']['aplica_se']]
    if sem_impacto:
        el.append(Paragraph("Analisadas — sem impacto identificado", est['h2']))
        for a in sem_impacto:
            an = a['analise']
            el.append(Paragraph(escapa(a['item']['titulo']), est['corpo']))
            el.append(Paragraph(
                f"{escapa(an['justificativa'])} "
                f"<font color='#64748b'>(confiança: {escapa(an['confianca'])})</font>", est['meta']))

    if descartados:
        el.append(Paragraph("Sem correspondência no vocabulário de triagem", est['h2']))
        el.append(Paragraph(
            "Detectadas pelo monitor, mas sem termos de SST no título, na ementa ou no órgão "
            "emissor. Listadas aqui para que nada saia do radar sem registro.", est['meta']))
        for d in descartados:
            el.append(Paragraph(
                f"• {escapa(d.get('titulo'))} <font color='#64748b'>— {escapa(d.get('orgao') or d.get('fonte'))}</font>",
                est['meta']))

    if falhas:
        el.append(Paragraph("Não analisadas — requerem leitura manual", est['h2']))
        for f in falhas:
            el.append(Paragraph(
                f"• {escapa(f['item'].get('titulo'))} <font color='#7f1d1d'>— {escapa(f['erro'])}</font>",
                est['meta']))

    # Aviso legal
    el.append(Spacer(1, 12))
    el.append(HRFlowable(width='100%', thickness=0.6,
                         color=colors.HexColor('#cbd5e1'), spaceAfter=6))
    el.append(Paragraph(AVISO_LEGAL, est['aviso']))

    doc.build(el)


def bloco_item(n, a, perfil, est, colors, Paragraph, Spacer, HRFlowable):
    an, item = a['analise'], a['item']
    cor, rotulo = CORES_URGENCIA.get(an['urgencia'], ('#475569', an['urgencia'].upper()))
    nomes = {u['id']: u['nome'] for u in perfil['unidades']}
    unidades = ', '.join(nomes.get(u, u) for u in an['unidades_afetadas']) or '—'

    el = [Paragraph(f"{n}. {escapa(item['titulo'])}", est['item']),
          Paragraph(
              f"<font color='{cor}'><b>{rotulo}</b></font> &nbsp;|&nbsp; "
              f"{escapa(item.get('orgao') or item.get('fonte'))} &nbsp;|&nbsp; "
              f"publicado em {escapa(item.get('data_fmt'))} &nbsp;|&nbsp; "
              f"confiança da análise: {escapa(an['confianca'])}", est['meta']),
          Paragraph(f"<b>Resumo.</b> {escapa(an['resumo'])}", est['corpo']),
          Paragraph(f"<b>O que mudou.</b> {escapa(an['o_que_mudou'])}", est['corpo']),
          Paragraph(f"<b>Unidades afetadas.</b> {escapa(unidades)}", est['corpo']),
          Paragraph(f"<b>Por quê.</b> {escapa(an['justificativa'])}", est['corpo'])]
    if an['nrs_relacionadas']:
        el.append(Paragraph(f"<b>Normas citadas.</b> {escapa(', '.join(an['nrs_relacionadas']))}",
                            est['corpo']))
    if an['prazo']:
        el.append(Paragraph(f"<b>Prazo.</b> {escapa(an['prazo'])}", est['corpo']))
    if an['requer_leitura_original']:
        el.append(Paragraph(
            "<b><font color='#b45309'>Requer leitura do texto original.</font></b> "
            "A análise automática não é suficiente para este item.", est['corpo']))
    if item.get('link'):
        el.append(Paragraph(
            f"<link href='{escapa(item['link'])}' color='#1565c0'>Abrir texto oficial</link>",
            est['meta']))
    el.append(HRFlowable(width='100%', thickness=0.4,
                         color=colors.HexColor('#e2e8f0'), spaceBefore=6, spaceAfter=8))
    return el


# ─── Orquestração ─────────────────────────────────────────────────────────────

def main():
    chave = os.environ.get('ANTHROPIC_API_KEY')
    if not chave:
        print("[relatório] ANTHROPIC_API_KEY não configurada — etapa ignorada.")
        print("            O monitoramento não é afetado. Para ativar, cadastre o")
        print("            secret ANTHROPIC_API_KEY no repositório (ver README).")
        return 0

    with open(STATE_FILE, encoding='utf-8') as f:
        state = json.load(f)
    with open(PERFIL_FILE, encoding='utf-8') as f:
        perfil = json.load(f)

    pendentes = [p for p in state.get('publicacoes_recentes', []) if not p.get('relatorio')]
    if not pendentes:
        print("[relatório] Nenhuma publicação pendente — nada a gerar.")
        return 0

    # Itens detectados antes do classificador existir não têm o campo
    # 'relevante'. Classificar aqui evita gastar API analisando o ruído
    # histórico (ANVISA, ANTT, CFM...) no primeiro relatório.
    _, vocab = load_config()
    for p in pendentes:
        if 'prioridade' not in p:
            alvo = ' '.join([p.get('titulo', ''), p.get('ementa', ''),
                             p.get('orgao', ''), p.get('fonte', '')])
            p['prioridade'] = ('alta' if p.get('tipo') != 'DOU'
                               else prioridade_sst(alvo, vocab))

    # Alta e possível são analisadas; baixa vai listada no fim do PDF, sem
    # consumir API — mas presente, para que nada saia do radar sem registro.
    relevantes  = [p for p in pendentes if p['prioridade'] != 'baixa'][:MAX_ITENS_POR_EXECUCAO]
    descartados = [p for p in pendentes if p['prioridade'] == 'baixa']

    print(f"[relatório] {len(pendentes)} pendente(s): "
          f"{len(relevantes)} para análise, {len(descartados)} de baixa relevância.")

    try:
        import anthropic
    except ImportError:
        print("[relatório] pacote 'anthropic' ausente — etapa ignorada.")
        return 0

    client = anthropic.Anthropic(api_key=chave)
    agora = now_brasilia()
    analisados, falhas = [], []

    for p in relevantes:
        print(f"  analisando: {p['titulo'][:70]}...", end=' ', flush=True)
        analise, erro = analisa(client, p, perfil)
        if erro:
            print(f"FALHA — {erro}")
            falhas.append({'item': p, 'erro': erro})
        else:
            print(f"ok ({'aplica-se' if analise['aplica_se'] else 'sem impacto'})")
            analisados.append({'item': p, 'analise': analise})

    if not analisados and not descartados and not falhas:
        print("[relatório] Nada a relatar.")
        return 0

    os.makedirs(REL_DIR, exist_ok=True)
    nome = f"relatorio-sst-{agora.strftime('%Y-%m-%d-%H%M')}.pdf"
    caminho = os.path.join(REL_DIR, nome)
    try:
        monta_pdf(caminho, agora, analisados, descartados, falhas, perfil)
    except ImportError:
        print("[relatório] pacote 'reportlab' ausente — PDF não gerado.")
        return 0

    # Marca como relatado só depois do PDF existir: se algo falhar acima, os
    # itens continuam pendentes e entram no próximo relatório.
    for p in pendentes:
        p['relatorio'] = nome
    for h in state.get('history', []):
        for p in pendentes:
            if h.get('id') == p.get('id'):
                h['relatorio'] = nome

    state.setdefault('relatorios', []).insert(0, {
        'arquivo': nome,
        'data': agora.strftime('%d/%m/%Y %H:%M'),
        'data_iso': agora.isoformat(),
        'analisados': len(analisados),
        'com_impacto': len([a for a in analisados if a['analise']['aplica_se']]),
        'descartados': len(descartados),
        'falhas': len(falhas),
    })
    state['relatorios'] = state['relatorios'][:60]

    tmp = STATE_FILE + '.tmp'
    with open(tmp, 'w', encoding='utf-8') as f:
        json.dump(state, f, ensure_ascii=False, indent=2)
    os.replace(tmp, STATE_FILE)

    print(f"[relatório] Gerado: relatorios/{nome}")
    print(f"            {len(analisados)} analisada(s), "
          f"{len([a for a in analisados if a['analise']['aplica_se']])} com impacto, "
          f"{len(falhas)} falha(s).")
    return 0


if __name__ == '__main__':
    sys.exit(main())
