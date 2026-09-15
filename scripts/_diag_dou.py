"""Diagnóstico temporário: descobre como paginar a busca do DOU.
Roda só via workflow_dispatch com diag=true. Remover depois."""
import json, re, sys, os, urllib.parse
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import check_nr as m

BASE = 'https://www.in.gov.br/consulta/-/buscar/dou'

def busca(**extra):
    p = {'q': '"portaria"', 's': 'do1', 'exactDate': 'personalizado',
         'publishFrom': '08-09-2026', 'publishTo': '15-09-2026', 'sortType': '0'}
    p.update(extra)
    return BASE + '?' + urllib.parse.urlencode(p)

def params_json(html):
    mm = re.search(r'<script[^>]+id="[^"]*params"[^>]*>(.*?)</script>', html, re.S | re.I)
    if not mm:
        return None
    try:
        return json.loads(mm.group(1).strip())
    except json.JSONDecodeError as e:
        print("    json inválido:", e)
        return None

def resume(rotulo, url):
    print(f"\n--- {rotulo}")
    print(f"    {url[:150]}")
    try:
        html = m.fetch(url)
    except Exception as e:
        print("    ERRO:", e); return None
    d = params_json(html)
    if d is None:
        print("    sem bloco params"); return None
    escalares = {k: v for k, v in d.items() if not isinstance(v, (list, dict))}
    print("    escalares:", json.dumps(escalares, ensure_ascii=False)[:500])
    for k, v in d.items():
        if isinstance(v, list):
            print(f"    lista '{k}': {len(v)} itens")
            if v and isinstance(v[0], dict):
                print(f"      chaves do 1o: {sorted(v[0].keys())}")
                print(f"      1o titulo   : {str(v[0].get('title',''))[:80]}")
                print(f"      ultimo      : {str(v[-1].get('title',''))[:80]}")
    itens = m._walk_for_results(d) or []
    return [str(r.get('title',''))[:60] for r in itens]

print("=" * 70)
print("  DIAGNÓSTICO DE PAGINAÇÃO DO DOU")
print("=" * 70)

base = resume("BASE (sem paginação)", busca())
if base is not None:
    print(f"\n    -> {len(base)} itens na 1a resposta")

# candidatos de paginação
for rotulo, extra in [
    ("currentPage=2", {'currentPage': '2'}),
    ("page=2",        {'page': '2'}),
    ("delta=50",      {'delta': '50'}),
    ("delta=20&currentPage=2", {'delta': '20', 'currentPage': '2'}),
]:
    r = resume(rotulo, busca(**extra))
    if r is None or base is None:
        continue
    novos = [t for t in r if t not in base]
    print(f"    -> {len(r)} itens, {len(novos)} DIFERENTES da 1a página")
    if novos:
        print(f"       exemplo novo: {novos[0]}")
