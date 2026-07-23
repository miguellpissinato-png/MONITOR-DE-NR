name: Monitor Diário — SST e DOU

on:
  schedule:
    - cron: '0 10 * * 1-5'   # 07:00 Brasília — seg a sex
    - cron: '0 12 * * 1-5'   # 09:00 Brasília — retry
  workflow_dispatch:
    inputs:
      reason:
        description: 'Motivo da execução manual'
        required: false
        default: 'Verificação manual'

permissions:
  contents: write

jobs:
  monitor-sst:
    runs-on: ubuntu-latest
    timeout-minutes: 30

    steps:
      - name: Checkout
        uses: actions/checkout@v4
        with:
          fetch-depth: 1

      - name: Configurar Python
        uses: actions/setup-python@v5
        with:
          python-version: '3.11'

      - name: Testar API Querido Diário
        run: |
          echo "Testando api.queridodiario.ok.org.br..."
          for i in 1 2 3; do
            if curl -sf --max-time 15 "https://api.queridodiario.ok.org.br/docs" > /dev/null 2>&1; then
              echo "✅ API disponível"
              exit 0
            fi
            echo "⏳ Tentativa $i falhou — aguardando 20s..."
            sleep 20
          done
          echo "❌ API indisponível — abortando"
          exit 1

      - name: Executar monitoramento
        run: |
          cd scripts
          for i in 1 2 3; do
            echo "--- Tentativa $i de 3 ---"
            if python check_dou.py; then
              break
            fi
            echo "Aguardando 30s..."
            sleep 30
          done

      - name: Salvar estado
        if: always()
        run: |
          git config user.name  "Monitor SST Bot"
          git config user.email "monitor-sst@github-actions"
          git add data/state.json
          git diff --cached --quiet || git commit -m "chore: monitoramento SST $(date -u +'%Y-%m-%d %H:%M UTC')"
          git push
