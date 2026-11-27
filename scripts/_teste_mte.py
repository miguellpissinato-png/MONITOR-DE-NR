import json, sys
sys.path.insert(0, 'scripts')
import check_nr as c
cfg = {s['id']: s for s in json.load(open('data/sources.json'))['sources']}
st = json.load(open('data/state.json'))
for sid in ('mte_portarias', 'nr_index'):
    print(f'\n### {sid}')
    try:
        itens, deg, av = c.collect_page_items(cfg[sid])
    except c.SourceError as e:
        print('FALHA', e); continue
    known = set(st['sources'][sid].get('known_ids', []))
    ids = [i['iid'] for i in itens]
    novos = [i for i in itens if i['iid'] not in known]
    print(f'\nitens={len(itens)} degradado={deg} conhecidos_em_comum={len(set(ids)&known)}/{len(known)} novos={len(novos)}')
    for i in novos[:15]: print('  NOVO:', i['titulo'][:90], i['link'][:120])
    for i in itens[:3]: print('  ex:', i['titulo'][:80], i['link'][:120])
    if cfg[sid].get('lista_nrs'):
        print('NRs extraídas:', len(c.extrai_nrs(itens)))
