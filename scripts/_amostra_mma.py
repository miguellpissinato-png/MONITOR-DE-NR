"""Descartável: mostra registros reais do cadastro de legislação ambiental do MMA."""
import csv, io, json, urllib.request
UA={'User-Agent':'Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0'}
def get(u,t=60):
    with urllib.request.urlopen(urllib.request.Request(u,headers=UA),timeout=t) as r: return r.read()

pkg=json.loads(get("https://dados.mma.gov.br/api/3/action/package_show?id=legislacao-ambiental-brasileira"))['result']
rec=sorted([r for r in pkg['resources'] if str(r.get('format','')).upper()=='CSV'], key=lambda r:str(r['name']))[-1]
raw=get(rec['url'])
for enc in ('utf-8-sig','latin-1'):
    try: txt=raw.decode(enc); break
    except UnicodeDecodeError: pass
d=';' if txt[:3000].count(';')>txt[:3000].count(',') else ','
linhas=list(csv.DictReader(io.StringIO(txt),delimiter=d))
print(f"### {len(linhas)} registros | colunas: {list(linhas[0].keys())}\n")

def mostra(titulo, filtro, n=4):
    sel=[l for l in linhas if filtro(l)][-n:]
    print(f"\n{'='*70}\n  {titulo}  ({sum(1 for l in linhas if filtro(l))} no total)\n{'='*70}")
    for l in sel:
        print(f"\n  ATO     : {str(l.get('ATO NORMATIVO',''))[:95]}")
        print(f"  EMENTA  : {str(l.get('EMENTA',''))[:190]}")
        print(f"  ASSUNTO : {str(l.get('ASSUNTO',''))[:70]}   | ÁREA: {str(l.get('ÁREA MMA',''))[:28]}")
        print(f"  STATUS  : {str(l.get('STATUS',''))[:55]}   | REVOGA: {str(l.get('REVOGA',''))[:45]}")
        print(f"  LINK    : {str(l.get('LINK',''))[:95]}")

def tem(l,*ps): 
    t=' '.join(str(v) for v in l.values()).lower()
    return any(p in t for p in ps)

mostra("RESÍDUOS SÓLIDOS E LOGÍSTICA REVERSA", lambda l: tem(l,'resíduo','logística reversa'))
mostra("EFLUENTES E RECURSOS HÍDRICOS", lambda l: tem(l,'efluente','recursos hídricos','lançamento'))
mostra("LICENCIAMENTO AMBIENTAL", lambda l: tem(l,'licenciamento'))
mostra("EMISSÕES ATMOSFÉRICAS E RUÍDO", lambda l: tem(l,'atmosfér','emissão','ruído'))

from collections import Counter
print(f"\n{'='*70}\n  DISTRIBUIÇÃO\n{'='*70}")
print("\n  por ASSUNTO (top 12):")
for k,v in Counter(str(l.get('ASSUNTO','')).strip() for l in linhas).most_common(12):
    print(f"    {v:>5}  {k[:60]}")
print("\n  por STATUS:")
for k,v in Counter(str(l.get('STATUS','')).strip() for l in linhas).most_common(8):
    print(f"    {v:>5}  {k[:60] or '(vazio)'}")
print("\n  por DOCUMENTO (top 8):")
for k,v in Counter(str(l.get('DOCUMENTO','')).strip() for l in linhas).most_common(8):
    print(f"    {v:>5}  {k[:45]}")
