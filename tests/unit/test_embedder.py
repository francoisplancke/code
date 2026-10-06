from legal.retrieval.embeddings import SentenceTransformerEmbedder


class FakeVector:
    def __init__(self):
        self.cast = None
    def astype(self, dtype):
        self.cast = dtype
        return self


class FakeModel:
    def __init__(self):
        self.calls = []
    def get_embedding_dimension(self):
        return 384
    def encode(self, texts, **kwargs):
        self.calls.append((texts, kwargs))
        return [FakeVector()]


def test_embedder_preserves_query_encoding_contract():
    model = FakeModel()
    embedder = SentenceTransformerEmbedder("fake", model=model)
    vector = embedder.encode("bonjour", normalize=True)
    assert embedder.dimension == 384
    texts, kwargs = model.calls[0]
    assert texts == ["bonjour"]
    assert kwargs["convert_to_numpy"] is True
    assert kwargs["normalize_embeddings"] is True
    assert vector is not None

from legal.retrieval.embeddings import (
    EmbeddingError, EmbeddingProvider, EmbeddingProviderUnavailable,
    FallbackEmbeddingProvider, embedding_model_from_env,
)

class FakeProvider(EmbeddingProvider):
    def __init__(self, name="m", dimension=3, fail=False):
        self.model_name=name; self.dimension=dimension; self.fail=fail; self.calls=0
    def encode_many(self, texts, *, normalize=True, batch_size=None):
        self.calls += 1
        if self.fail: raise EmbeddingProviderUnavailable("offline")
        return [[1.0] * self.dimension for _ in texts]

def test_embedding_fallback_uses_second_provider_on_unavailable():
    a=FakeProvider(fail=True); b=FakeProvider()
    f=FallbackEmbeddingProvider([a,b])
    assert len(f.encode("x")) == 3
    assert a.calls == 1 and b.calls == 1 and f.active == 1

def test_embedding_fallback_rejects_different_models_or_dimensions():
    import pytest
    with pytest.raises(EmbeddingError): FallbackEmbeddingProvider([FakeProvider("a"),FakeProvider("b")])
    with pytest.raises(EmbeddingError): FallbackEmbeddingProvider([FakeProvider(dimension=3),FakeProvider(dimension=4)])

def test_embedding_model_new_env_wins_and_legacy_is_supported():
    assert embedding_model_from_env({"LEGAL_MODEL":"legacy"}) == "legacy"
    assert embedding_model_from_env({"LEGAL_MODEL":"legacy","LEGAL_EMBEDDING_MODEL":"new"}) == "new"

def test_factory_remote_offline_can_fall_back_to_local(monkeypatch):
    import legal.retrieval.embeddings as e
    class Offline:
        def __init__(self, *a, **k): raise e.EmbeddingProviderUnavailable("off")
    class Local(FakeProvider):
        provider_name="local"
        def __init__(self, *a, **k): super().__init__(name="same", dimension=3)
    monkeypatch.setattr(e, "RemoteEmbeddingProvider", Offline)
    monkeypatch.setattr(e, "SentenceTransformerEmbedder", Local)
    p=e.create_embedding_provider({"LEGAL_EMBEDDING_PROVIDERS":"remote,local","LEGAL_EMBEDDING_REMOTE_URL":"http://gpu/v1"}, model_name="same")
    assert p.provider_name == "local"
