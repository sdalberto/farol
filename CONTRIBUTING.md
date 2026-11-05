# Como contribuir com o Farol

Obrigado pelo interesse! 🎉 Todo o código é comentado em português para facilitar.

## Preparando o ambiente

```bash
git clone https://github.com/SEU_USUARIO/farol.git && cd farol
python -m venv .venv && . .venv/bin/activate    # Windows: .venv\Scripts\activate
pip install -r requirements-dev.txt
python -m farol --home ./.dados-dev setup        # pasta de dados separada para testes
python -m farol --home ./.dados-dev run
pytest                                           # rode os testes antes do PR
```

## Onde mexer

| Quero… | Arquivo |
|---|---|
| Suportar um novo formato de documento | `farol/extractors.py` → crie `_extrair_xxx` e registre em `EXTRACTORS` |
| Mudar ranking/operadores da busca | `farol/indexer.py` (`parse_query`, `search`) |
| Adicionar um provedor de IA | `farol/ai.py` → crie `_ask_xxx` e registre em `PROVIDERS` |
| Criar uma rota na API | `farol/server.py` (sempre chame `require(request)`) |
| Mudar a interface | `farol/static/app.js` e `app.css` |
| Traduzir / novo idioma | `farol/static/i18n/*.json` (mesmas chaves nos 3 arquivos) + `LANGUAGES` em `config.py` + `MSG` em `__main__.py` |
| Novo fundo pronto | `PRESETS` em `app.js` |

## Regras de ouro

1. **Offline primeiro**: nada de CDN ou chamadas externas na interface. Bibliotecas de terceiros vão em `farol/static/vendor/` com a licença junto.
2. **Segurança**: todo caminho vindo da interface passa por `resolve_in_roots`; todo texto exibido passa por `esc()`.
3. **Sem dependências pesadas**: prefira a biblioteca padrão do Python.
4. **Comente em português** e mantenha os 3 idiomas sincronizados.
5. Commits pequenos e descritivos; um assunto por PR.
