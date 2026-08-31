# Monitor de NR — Segurança e Saúde no Trabalho

Monitora fontes oficiais e avisa, no painel, quando algo que a área de SST
precisa cumprir muda: portarias do MTE, Normas Regulamentadoras, publicações
do Diário Oficial da União e normas técnicas.

- **Painel:** `index.html` (HTML estático, servido pelo GitHub Pages)
- **Coletor:** `scripts/check_nr.py` (Python 3.11, só biblioteca padrão)
- **Fontes:** `data/sources.json` (declarativo — dá para acrescentar norma sem mexer no código)
- **Estado:** `data/state.json` (gravado a cada execução e versionado no Git)

## Princípio de projeto

> **"Sem novidades" e "não consegui verificar" nunca podem parecer a mesma coisa.**

A versão anterior tratava erro de rede como "nenhuma alteração": o painel ficava
verde mesmo sem ter lido nada. Agora, qualquer fonte crítica que falhe:

1. derruba a execução (o workflow fica **vermelho** no GitHub Actions);
2. é registrada em `data/state.json`, com o erro e há quantas execuções falha;
3. faz o painel exibir um **banner vermelho** no topo.

O painel também compara a última verificação com o último dia útil às 09:00
(Brasília, 2h de tolerância). Se nenhuma execução ocorreu, aparece
**"MONITORAMENTO DESATUALIZADO — NÃO CONFIE NESTA TELA"**, mesmo que o
`state.json` esteja intacto. É isso que cobre o caso em que o agendador
simplesmente não roda.

## Agendamento

O `schedule:` do GitHub Actions é **best-effort**: atrasa (observamos de 25 min
a 2h20) e às vezes não dispara. Ele continua no workflow como rede de segurança,
mas o disparo confiável deve vir de um agendador externo.

### Configurar o disparo externo

1. Gere um *fine-grained token* em GitHub → Settings → Developer settings, com
   permissão **Contents: read and write** apenas neste repositório.
2. Em um agendador (cron-job.org, EasyCron ou um cron do seu servidor), agende
   para **08:00 de Brasília, de segunda a sexta**, uma requisição:

```
POST https://api.github.com/repos/miguellpissinato-png/MONITOR-DE-NR/dispatches
Authorization: Bearer SEU_TOKEN
Accept: application/vnd.github+json
Body: {"event_type":"monitor"}
```

Equivalente em `curl`:

```bash
curl -X POST \
  -H "Authorization: Bearer SEU_TOKEN" \
  -H "Accept: application/vnd.github+json" \
  https://api.github.com/repos/miguellpissinato-png/MONITOR-DE-NR/dispatches \
  -d '{"event_type":"monitor"}'
```

Mesmo que o agendador externo falhe, o banner de "desatualizado" avisa. As duas
proteções são independentes de propósito.

## Acrescentar uma fonte

Edite `data/sources.json`:

```json
{
  "id": "identificador_unico",
  "label": "Nome que aparece no painel",
  "kind": "page_items",
  "tipo": "NBR",
  "critical": false,
  "url": "https://exemplo.gov.br/pagina",
  "item_pattern": "nbr\\s*\\d+"
}
```

- `kind`: `page_items` (extrai links da página) ou `dou_search` (busca no in.gov.br).
- `item_pattern`: regex; só links cujo texto casar viram itens monitorados.
- `critical`: `true` faz a execução falhar imediatamente se a fonte cair.
  `false` tolera até 3 falhas seguidas antes de alarmar.

Na primeira execução a fonte registra um *baseline* e não gera alertas — a
comparação começa da segunda em diante.

### Modo degradado

Se a extração de itens não encontrar nada (sinal de que o site oficial mudou de
estrutura), a fonte volta a comparar o hash da página inteira e é marcada como
**degradada** no painel. Ela continua detectando que *algo* mudou, mas não
consegue dizer *o quê* — é o aviso de que o `item_pattern` precisa de ajuste.

## Executar localmente

```bash
python3 scripts/check_nr.py   # sai com código != 0 se uma fonte crítica falhar
```

## Limitações conhecidas

- **Feriados nacionais** não são tratados: em feriado que caia em dia útil, o
  banner de desatualizado pode aparecer indevidamente.
- **O botão "Verificar agora"** pede um token do GitHub e o guarda no
  `localStorage` do navegador. Em um site público, use um token de escopo
  mínimo (apenas este repositório) e evite usá-lo em computador compartilhado.
- **ABNT/NBR:** o catálogo da ABNT não tem API pública e as normas são pagas.
  A fonte `abnt_sst` é experimental e monitora a página pública de catálogo;
  ela é `critical: false` justamente por isso.
