"""Diagnóstico 2: teto do delta e parâmetro real de página (Liferay usa 'cur')."""
import json, re, sys, os, urllib.parse
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import check_nr as m

BASE = 'https://www.in.gov.br/consulta/-/buscar/dou'
NS = '_br_com_seatecnologia_in_buscadou_BuscaDouPortlet_'

def titulos(**extra):
    p = {'q': '"portaria"', 's': 'do1', 'exactDate': 'personalizado',
         'publishFrom': '01-09-2026', 'publishTo': '15-09-2026', 'sortType': '0'}
    p.update(extra)
    url = BASE + '?' + urllib.parse.urlencode(p)
    try:
        html = m.fetch(url)
    except Exception as e:
        return None, str(e)
    mm = re.search(r'<script[^>]+id="[^"]*params"[^>]*>(.*?)</script>', html, re.S | re.I)
    if not mm:
        return None, 'sem bloco params'
    try:
        d = json.loads(mm.group(1).strip())
    except json.JSONDecodeError as e:
        return None, f'json inválido: {e}'
    itens = m._walk_for_results(d) or []
    return [re.sub(r'<[^>]+>', '', str(r.get('title', '')))[:70] for r in itens], None

print("=" * 72)
print("  TETO DO delta")
print("=" * 72)
base, _ = titulos()
print(f"  padrão (sem delta): {len(base) if base else '?'} itens")
anterior = None
for dv in (50, 100, 200, 500, 1000):
    t, err = titulos(delta=str(dv))
    if err:
        print(f"  delta={dv:<5} ERRO: {err}"); continue
    marca = ""
    if anterior is not None and len(t) == anterior:
        marca = "  <-- não cresceu: TETO ATINGIDO"
    print(f"  delta={dv:<5} {len(t):>4} itens{marca}")
    anterior = len(t)

print()
print("=" * 72)
print("  PARÂMETRO DE PÁGINA")
print("=" * 72)
p1, _ = titulos(delta='20')
print(f"  página 1 (delta=20): {len(p1)} itens | 1o: {p1[0][:50] if p1 else '-'}")
for rotulo, extra in [
    ("cur=2",            {'delta': '20', 'cur': '2'}),
    (NS + "cur=2",       {'delta': '20', NS + 'cur': '2'}),
    (NS + "delta+cur",   {NS + 'delta': '20', NS + 'cur': '2'}),
    ("start=20",         {'delta': '20', 'start': '20'}),
    ("offset=20",        {'delta': '20', 'offset': '20'}),
]:
    t, err = titulos(**extra)
    if err:
        print(f"  {rotulo:<24} ERRO: {err}"); continue
    novos = [x for x in t if x not in p1]
    ok = "SIM — PAGINA!" if novos else "não (mesma página)"
    print(f"  {rotulo:<24} {len(t):>3} itens, {len(novos):>3} inéditos  -> {ok}")
    if novos:
        print(f"      exemplo: {novos[0][:60]}")
