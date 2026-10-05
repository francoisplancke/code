"""Small dependency-free LLM gateway for optional analysis features.

Corpus ingestion must not import or require this module. Cloud credentials are
validated only when the corresponding provider is selected.
"""
from __future__ import annotations
from dataclasses import dataclass
import json, os
from urllib.request import Request, urlopen
from urllib.error import HTTPError, URLError

class LLMError(RuntimeError): pass

@dataclass(frozen=True)
class LLMConfig:
    provider: str
    model: str
    base_url: str
    api_key: str | None
    timeout: float = 60.0

_DEFAULTS = {
    "local": ("http://127.0.0.1:11434/v1", "local-model", None),
    "openai": ("https://api.openai.com/v1", "gpt-5-mini", "OPENAI_API_KEY"),
    "deepseek": ("https://api.deepseek.com/v1", "deepseek-chat", "DEEPSEEK_API_KEY"),
    "gemini": ("https://generativelanguage.googleapis.com/v1beta", "gemini-2.5-flash", "GEMINI_API_KEY"),
}

def load_config(env=os.environ) -> LLMConfig:
    provider = env.get("LEGAL_LLM_PROVIDER", "local").strip().lower()
    if provider not in _DEFAULTS:
        raise LLMError(f"LEGAL_LLM_PROVIDER inconnu: {provider}")
    default_url, default_model, key_name = _DEFAULTS[provider]
    key = env.get(key_name) if key_name else env.get("LEGAL_LLM_API_KEY")
    if key_name and not key:
        raise LLMError(f"{key_name} est requis quand LEGAL_LLM_PROVIDER={provider}")
    return LLMConfig(provider, env.get("LEGAL_LLM_MODEL", default_model),
                     env.get("LEGAL_LLM_BASE_URL", default_url).rstrip("/"), key,
                     float(env.get("LEGAL_LLM_TIMEOUT", "60")))

def _post(url: str, payload: dict, headers: dict, timeout: float) -> dict:
    req = Request(url, data=json.dumps(payload).encode(), headers={"Content-Type":"application/json", **headers}, method="POST")
    try:
        with urlopen(req, timeout=timeout) as r: return json.load(r)
    except (HTTPError, URLError, TimeoutError) as e:
        raise LLMError(f"appel LLM échoué: {e}") from e

def chat(messages: list[dict[str,str]], config: LLMConfig | None=None, *, temperature: float=0.0) -> str:
    c=config or load_config()
    if c.provider == "gemini":
        contents=[{"role":"model" if m["role"]=="assistant" else "user", "parts":[{"text":m["content"]}]} for m in messages if m["role"]!="system"]
        system="\n".join(m["content"] for m in messages if m["role"]=="system")
        payload={"contents":contents,"generationConfig":{"temperature":temperature}}
        if system: payload["systemInstruction"]={"parts":[{"text":system}]}
        data=_post(f"{c.base_url}/models/{c.model}:generateContent?key={c.api_key}",payload,{},c.timeout)
        try: return data["candidates"][0]["content"]["parts"][0]["text"]
        except (KeyError,IndexError) as e: raise LLMError("réponse Gemini inattendue") from e
    headers={"Authorization":f"Bearer {c.api_key}"} if c.api_key else {}
    data=_post(f"{c.base_url}/chat/completions",{"model":c.model,"messages":messages,"temperature":temperature},headers,c.timeout)
    try: return data["choices"][0]["message"]["content"]
    except (KeyError,IndexError) as e: raise LLMError("réponse LLM inattendue") from e
