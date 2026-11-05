# Política de segurança

## Como reportar uma vulnerabilidade

**Não abra uma issue pública.** Use o recurso *Security → Report a vulnerability* do GitHub
(aviso privado) com:

- descrição do problema e impacto;
- passos para reproduzir;
- versão do Farol e sistema operacional.

Respondemos em até 7 dias.

## Modelo de segurança (resumo)

| Ameaça | Proteção |
|---|---|
| Acesso sem senha | Toda rota `/api` exige sessão; não há senha padrão |
| Força bruta | Bloqueio progressivo por IP (30 s dobrando até 15 min) + atraso fixo |
| Vazamento do hash | PBKDF2-SHA256, 600 mil iterações, salt aleatório; `config.json` com permissão 600 |
| CSRF | Cabeçalho `X-Farol` obrigatório + cookie `SameSite=Strict` |
| XSS por arquivos do usuário | HTML/SVG/JS servidos como `text/plain` + CSP `sandbox` |
| Path traversal / symlink | `realpath` + verificação de que o caminho está dentro de uma pasta cadastrada |
| Chave de IA | Fica só no servidor; a interface recebe apenas `has_key` |
| Terminal (Modo Dev) | Desligado por padrão; ligar exige senha; WebSocket valida sessão **e** `Origin`; bloqueio total com `FAROL_DISABLE_DEV=1` |
| SSH | Usa o cliente `ssh` do sistema; senhas nunca são salvas; campos validados contra injeção de argumentos |
| Exposição na rede | Modo desktop escuta só em `127.0.0.1` |

## Recomendações para o modo servidor

- Use HTTPS (`--cert/--key` ou proxy reverso — veja `docs/SERVIDOR.md`).
- Não exponha o Farol direto na internet; prefira VPN (WireGuard/Tailscale).
- Defina `FAROL_DISABLE_DEV=1` se o Modo Dev não for necessário.
- Monte pastas sensíveis como **somente leitura**.
