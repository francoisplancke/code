import pytest
from legal.llm import load_config, LLMError

def test_local_needs_no_cloud_key():
 c=load_config({"LEGAL_LLM_PROVIDER":"local"}); assert c.provider=="local" and c.api_key is None
@pytest.mark.parametrize("provider,key",[("openai","OPENAI_API_KEY"),("deepseek","DEEPSEEK_API_KEY"),("gemini","GEMINI_API_KEY")])
def test_cloud_key_required(provider,key):
 with pytest.raises(LLMError): load_config({"LEGAL_LLM_PROVIDER":provider})
 c=load_config({"LEGAL_LLM_PROVIDER":provider,key:"secret"}); assert c.api_key=="secret"
def test_unknown_provider_rejected():
 with pytest.raises(LLMError): load_config({"LEGAL_LLM_PROVIDER":"jev"})

from legal.llm import load_configs

def test_ordered_llm_configs():
 env={"LEGAL_LLM_PROVIDERS":"remote,deepseek,local","LEGAL_LLM_REMOTE_URL":"http://gpu/v1","DEEPSEEK_API_KEY":"secret"}
 cs=load_configs(env)
 assert [c.provider for c in cs] == ["remote","deepseek","local"]
 assert cs[0].base_url == "http://gpu/v1"

def test_chat_falls_back_only_on_provider_unavailable(monkeypatch):
 import legal.llm.providers as p
 calls=[]
 configs=[p.LLMConfig("remote","m","http://gpu",None),p.LLMConfig("local","m","http://cpu",None)]
 monkeypatch.setattr(p,"load_configs",lambda env: configs)
 def fake(messages,c,temperature):
  calls.append(c.provider)
  if c.provider=="remote": raise p.LLMProviderUnavailable("off")
  return "ok"
 monkeypatch.setattr(p,"_chat_one",fake)
 assert p.chat([{"role":"user","content":"x"}],env={}) == "ok"
 assert calls == ["remote","local"]

def test_chat_does_not_hide_non_retryable_error(monkeypatch):
 import legal.llm.providers as p
 configs=[p.LLMConfig("remote","m","http://gpu",None),p.LLMConfig("local","m","http://cpu",None)]
 monkeypatch.setattr(p,"load_configs",lambda env: configs)
 monkeypatch.setattr(p,"_chat_one",lambda *a,**k: (_ for _ in ()).throw(p.LLMError("bad request")))
 import pytest
 with pytest.raises(p.LLMError,match="bad request"):
  p.chat([{"role":"user","content":"x"}],env={})
