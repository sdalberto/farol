"""
Conectores de IA (todos OPCIONAIS e desligados por padrão).

Fluxo de uma pergunta:
  1. O Farol faz uma busca local com as palavras da pergunta.
  2. Pega trechos dos melhores arquivos (até 'context_files').
  3. Envia pergunta + trechos para o provedor escolhido.

Provedores:
  - ollama            -> IA 100% local e offline (http://127.0.0.1:11434)
  - anthropic         -> Claude (API da Anthropic)
  - openai            -> GPT (API da OpenAI)
  - openai_compatible -> qualquer API no padrão OpenAI: LM Studio, llama.cpp,
                         OpenRouter, Groq, Gemini (endpoint compatível) etc.

Só usa a biblioteca padrão (urllib) — nenhum SDK extra.
Para adicionar um provedor novo: crie _ask_xxx e registre em PROVIDERS.
"""
from __future__ import annotations

import json
import re
import urllib.error
import urllib.request

LANG_NAMES = {"pt-BR": "português do Brasil", "en": "English", "es": "español"}

# Palavras muito comuns que atrapalham a busca de contexto.
STOPWORDS = set("""
a o os as um uma de do da dos das em no na nos nas para por com sem que qual quais quem
como onde quando é e ou se meu minha meus minhas tem ter sobre isso esse essa este esta
the an of in on at to for with is are was what which who how where when my me i do does
el la los las un una del en con por para que cual como donde cuando es y o mi mis sobre
""".split())


class AIError(Exception):
    pass


def keywords(question: str) -> str:
    """Extrai palavras-chave da pergunta para a busca local."""
    words = [w for w in re.findall(r"\w+", question.lower()) if len(w) > 2 and w not in STOPWORDS]
    return " ".join(words[:8])


def _post(url: str, payload: dict, headers: dict, timeout: int = 120) -> dict:
    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(url, data=data, method="POST",
                                 headers={"Content-Type": "application/json", **headers})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8", "ignore")[:400]
        raise AIError(f"HTTP {e.code}: {body}") from e
    except urllib.error.URLError as e:
        raise AIError(f"connection: {e.reason}") from e


def _ask_anthropic(cfg, system, user):
    if not cfg.get("api_key"):
        raise AIError("missing_api_key")
    base = (cfg.get("base_url") or "https://api.anthropic.com").rstrip("/")
    r = _post(f"{base}/v1/messages",
              {"model": cfg["model"], "max_tokens": 1500, "system": system,
               "messages": [{"role": "user", "content": user}]},
              {"x-api-key": cfg["api_key"], "anthropic-version": "2023-06-01"})
    return "".join(b.get("text", "") for b in r.get("content", []) if b.get("type") == "text")


def _ask_openai_like(cfg, system, user, default_base):
    base = (cfg.get("base_url") or default_base).rstrip("/")
    if not base:
        raise AIError("missing_base_url")
    headers = {"Authorization": f"Bearer {cfg['api_key']}"} if cfg.get("api_key") else {}
    r = _post(f"{base}/chat/completions",
              {"model": cfg["model"], "messages": [{"role": "system", "content": system},
                                                   {"role": "user", "content": user}]},
              headers)
    return r["choices"][0]["message"]["content"]


def _ask_openai(cfg, system, user):
    if not cfg.get("api_key"):
        raise AIError("missing_api_key")
    return _ask_openai_like(cfg, system, user, "https://api.openai.com/v1")


def _ask_compatible(cfg, system, user):
    return _ask_openai_like(cfg, system, user, "")


def _ask_ollama(cfg, system, user):
    base = (cfg.get("base_url") or "http://127.0.0.1:11434").rstrip("/")
    r = _post(f"{base}/api/chat",
              {"model": cfg["model"], "stream": False,
               "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}]},
              {}, timeout=300)
    return r.get("message", {}).get("content", "")


PROVIDERS = {
    "anthropic": _ask_anthropic,
    "openai": _ask_openai,
    "openai_compatible": _ask_compatible,
    "ollama": _ask_ollama,
}


def ask(ai_cfg: dict, question: str, contexts: list[dict], lang: str) -> str:
    """Monta o prompt com os trechos locais e chama o provedor."""
    fn = PROVIDERS.get(ai_cfg.get("provider"))
    if not fn:
        raise AIError("unknown_provider")
    system = (
        "Você é o assistente do Farol, um buscador offline de arquivos pessoais. "
        "Responda usando principalmente os trechos de arquivos fornecidos. "
        "Cite as fontes no formato [1], [2]. Se a resposta não estiver nos arquivos, diga isso "
        f"e responda com seu conhecimento geral. Responda em {LANG_NAMES.get(lang, 'português do Brasil')}."
    )
    blocks = []
    for i, ctx in enumerate(contexts, 1):
        blocks.append(f"[{i}] {ctx['name']} ({ctx['path']})\n{ctx['text']}")
    user = (("Arquivos locais relevantes:\n\n" + "\n\n---\n\n".join(blocks) + "\n\n") if blocks else "") \
        + f"Pergunta: {question}"
    return fn(ai_cfg, system, user).strip()


def excerpt(text: str, terms: list[str], size: int = 2500) -> str:
    """Recorta um pedaço do texto em volta da primeira ocorrência de algum termo."""
    if len(text) <= size:
        return text
    low = text.lower()
    pos = min((p for p in (low.find(t.lower()) for t in terms) if p >= 0), default=0)
    start = max(0, pos - size // 3)
    return text[start:start + size]
