"""Dependency-free LLM gateway with ordered provider fallback."""
from __future__ import annotations
from dataclasses import dataclass
import json, os
from urllib.request import Request, urlopen
from urllib.error import HTTPError, URLError

class LLMError(RuntimeError): pass
class LLMProviderUnavailable(LLMError): pass

@dataclass(frozen=True)
class LLMConfig:
    provider: str
    model: str
    base_url: str
    api_key: str | None
    timeout: float = 60.0

_DEFAULTS = {
    "local": ("http://127.0.0.1:11434/v1", "local-model", "LEGAL_LLM_API_KEY"),
    "remote": ("http://127.0.0.1:8000/v1", "local-model", "LEGAL_LLM_REMOTE_API_KEY"),
    "openai": ("https://api.openai.com/v1", "gpt-5-mini", "OPENAI_API_KEY"),
    "deepseek": ("https://api.deepseek.com/v1", "deepseek-chat", "DEEPSEEK_API_KEY"),
    "gemini": ("https://generativelanguage.googleapis.com/v1beta", "gemini-2.5-flash", "GEMINI_API_KEY"),
}

def _provider_config(provider: str, env=os.environ) -> LLMConfig:
    provider = provider.strip().lower()
    if provider not in _DEFAULTS:
        raise LLMError(f"provider LLM inconnu: {provider}")
    default_url, default_model, key_name = _DEFAULTS[provider]
    prefix = f"LEGAL_LLM_{provider.upper()}_"
    base = env.get(prefix + "URL") or (env.get("LEGAL_LLM_REMOTE_URL") if provider == "remote" else None) or env.get("LEGAL_LLM_BASE_URL") or default_url
    model = env.get(prefix + "MODEL") or env.get("LEGAL_LLM_MODEL") or default_model
    key = env.get(key_name) if key_name else None
    if provider in {"openai", "deepseek", "gemini"} and not key:
        raise LLMError(f"{key_name} est requis quand le provider {provider} est configuré")
    return LLMConfig(provider, model, base.rstrip("/"), key, float(env.get(prefix + "TIMEOUT") or env.get("LEGAL_LLM_TIMEOUT", "60")))

def load_config(env=os.environ) -> LLMConfig:
    return _provider_config(env.get("LEGAL_LLM_PROVIDER", "local"), env)

def load_configs(env=os.environ) -> list[LLMConfig]:
    raw = env.get("LEGAL_LLM_PROVIDERS")
    if not raw:
        return [load_config(env)]
    return [_provider_config(name, env) for name in raw.split(",") if name.strip()]

def _post(url: str, payload: dict, headers: dict, timeout: float) -> dict:
    req = Request(url, data=json.dumps(payload).encode(), headers={"Content-Type":"application/json", **headers}, method="POST")
    try:
        with urlopen(req, timeout=timeout) as r: return json.load(r)
    except HTTPError as e:
        if e.code in {408, 425, 429} or e.code >= 500:
            raise LLMProviderUnavailable(f"provider LLM temporairement indisponible: HTTP {e.code}") from e
        raise LLMError(f"appel LLM refusé: HTTP {e.code}") from e
    except (URLError, TimeoutError, OSError) as e:
        raise LLMProviderUnavailable(f"provider LLM indisponible: {e}") from e

def _chat_one(messages: list[dict[str,str]], c: LLMConfig, temperature: float) -> str:
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

def chat(messages: list[dict[str,str]], config: LLMConfig | None=None, *, temperature: float=0.0, env=os.environ) -> str:
    configs = [config] if config else load_configs(env)
    failures=[]
    for c in configs:
        try:
            return _chat_one(messages, c, temperature)
        except LLMProviderUnavailable as exc:
            failures.append(f"{c.provider}: {exc}")
            continue
    raise LLMProviderUnavailable("tous les providers LLM sont indisponibles: " + "; ".join(failures))
