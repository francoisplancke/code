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
