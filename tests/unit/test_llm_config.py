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
