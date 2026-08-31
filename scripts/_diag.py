"""Diagnóstico temporário: descobre por que o DOU volta vazio e qual URL da
ABNT responde. Roda só via workflow_dispatch com diag=true. Não faz parte do
monitoramento e deve ser removido depois."""
import re, json, sys, os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import check_nr as m

print("\n########## DOU ##########")
url = ('https://www.in.gov.br/consulta/-/buscar/dou?'
       'q=%22norma+regulamentadora%22&s=do1&exactDate=personalizado'
       '&publishFrom=24-08-2026&publishTo=31-08-2026&sortType=0')
try:
    html = m.fetch(url)
    print("tamanho:", len(html))
    for sid in re.findall(r'<script[^>]*id="([^"]+)"', html):
        print("  script id:", sid)
    mm = re.search(r'<script[^>]+id="params"[^>]*>(.*?)</script>', html, re.S | re.I)
    print("tem id=params:", bool(mm))
    if mm:
        try:
            d = json.loads(mm.group(1).strip())
            print("chaves do JSON:", list(d)[:20])
            for k, v in d.items():
                if isinstance(v, list):
                    print(f"  lista '{k}': {len(v)} itens; 1o = "
                          + (json.dumps(v[0], ensure_ascii=False)[:400] if v else "vazio"))
        except Exception as e:
            print("json falhou:", e, "| trecho:", mm.group(1)[:300])
    if 'totalCount' in html:
        print("totalCount no HTML:", re.findall(r'totalCount[^,}]{0,40}', html)[:3])
except Exception as e:
    print("ERRO:", e)

print("\n########## ABNT / normas técnicas ##########")
candidatos = [
    "https://www.abntonline.com.br/consultanacional/",
    "https://www.abntcatalogo.com.br/",
    "https://www.abnt.org.br/",
    "https://www.gov.br/inmetro/pt-br/assuntos/legislacao/portarias",
]
for u in candidatos:
    try:
        html = m.fetch(u, timeout=35)
        p = m.LinkExtractor(); p.feed(html)
        nbr = [t for t, h in p.links if re.search(r'nbr\s*\d+', t, re.I)]
        port = [t for t, h in p.links if re.search(r'portaria', t, re.I)]
        print(f"OK  {len(html):>7}b  links={len(p.links):>4}  nbr={len(nbr):>3}  portaria={len(port):>3}  {u}")
        for t in (nbr or port)[:4]:
            print("      ex:", t[:110])
    except Exception as e:
        print(f"ERRO {e}")
