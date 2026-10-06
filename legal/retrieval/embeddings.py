from __future__ import annotations

from dataclasses import dataclass
import json
import os
from typing import Any, Iterable
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


class EmbeddingError(RuntimeError):
    pass


class EmbeddingProviderUnavailable(EmbeddingError):
    pass


class EmbeddingProvider:
    """Common contract for local and remote embedding engines."""

    provider_name = "unknown"
    model_name: str
    dimension: int

    def encode_many(self, texts: list[str], *, normalize: bool = True, batch_size: int | None = None):
        raise NotImplementedError

    def encode(self, text: str, normalize: bool = True):
        return self.encode_many([text], normalize=normalize)[0]


class SentenceTransformerEmbedder(EmbeddingProvider):
    """Local SentenceTransformers provider (CPU/CUDA)."""

    provider_name = "local"

    def __init__(self, model_name: str, device: str | None = None, model: Any | None = None):
        self.model_name = model_name
        self.device = device
        if model is None:
            try:
                from sentence_transformers import SentenceTransformer
            except ImportError as exc:  # pragma: no cover
                raise RuntimeError("sentence-transformers est requis pour charger le modèle local.") from exc
            model = SentenceTransformer(model_name, device=device) if device else SentenceTransformer(model_name)
        self.model = model
        getter = getattr(self.model, "get_embedding_dimension", None) or getattr(self.model, "get_sentence_embedding_dimension")
        self.dimension = int(getter())

    def encode_many(self, texts: list[str], *, normalize: bool = True, batch_size: int | None = None):
        kwargs = {"convert_to_numpy": True, "normalize_embeddings": normalize}
        if batch_size is not None:
            kwargs.update(batch_size=batch_size, show_progress_bar=False)
        vectors = self.model.encode(texts, **kwargs)
        try:
            import numpy as np
            return [v.astype(np.float32) for v in vectors]
        except ImportError:  # pragma: no cover
            return list(vectors)


@dataclass(frozen=True)
class RemoteEmbeddingConfig:
    base_url: str
    model: str
    api_key: str | None = None
    timeout: float = 5.0
    expected_dimension: int | None = None


class RemoteEmbeddingProvider(EmbeddingProvider):
    """OpenAI-compatible /v1/embeddings client for a LAN GPU/AI box."""

    provider_name = "remote"

    def __init__(self, config: RemoteEmbeddingConfig, *, opener=urlopen):
        self.config = config
        self.model_name = config.model
        self._opener = opener
        self.dimension = config.expected_dimension or self._probe_dimension()

    def _request(self, texts: list[str]) -> list[list[float]]:
        url = f"{self.config.base_url.rstrip('/')}/embeddings"
        headers = {"Content-Type": "application/json"}
        if self.config.api_key:
            headers["Authorization"] = f"Bearer {self.config.api_key}"
        req = Request(url, data=json.dumps({"model": self.model_name, "input": texts}).encode(), headers=headers, method="POST")
        try:
            with self._opener(req, timeout=self.config.timeout) as response:
                data = json.load(response)
        except (URLError, TimeoutError, OSError) as exc:
            raise EmbeddingProviderUnavailable(f"provider embeddings distant indisponible: {exc}") from exc
        except HTTPError as exc:
            if exc.code in {408, 425, 429} or exc.code >= 500:
                raise EmbeddingProviderUnavailable(f"provider embeddings distant HTTP {exc.code}") from exc
            raise EmbeddingError(f"requête embeddings distante refusée: HTTP {exc.code}") from exc
        try:
            ordered = sorted(data["data"], key=lambda item: item.get("index", 0))
            return [item["embedding"] for item in ordered]
        except (KeyError, TypeError) as exc:
            raise EmbeddingError("réponse embeddings distante invalide") from exc

    def _probe_dimension(self) -> int:
        vectors = self._request(["dimension probe"])
        if len(vectors) != 1 or not vectors[0]:
            raise EmbeddingError("impossible de déterminer la dimension du modèle distant")
        return len(vectors[0])

    def encode_many(self, texts: list[str], *, normalize: bool = True, batch_size: int | None = None):
        # The remote server must expose the exact same normalized embedding model.
        vectors = self._request(texts)
        if len(vectors) != len(texts):
            raise EmbeddingError(f"le provider distant a renvoyé {len(vectors)} vecteurs pour {len(texts)} textes")
        if any(len(v) != self.dimension for v in vectors):
            raise EmbeddingError("dimension incohérente renvoyée par le provider distant")
        try:
            import numpy as np
            result = [np.asarray(v, dtype=np.float32) for v in vectors]
            if normalize:
                result = [v / np.linalg.norm(v) if np.linalg.norm(v) else v for v in result]
            return result
        except ImportError:  # pragma: no cover
            return vectors


class FallbackEmbeddingProvider(EmbeddingProvider):
    """Use providers in order; a provider is disabled after a retryable failure."""

    provider_name = "fallback"

    def __init__(self, providers: list[EmbeddingProvider]):
        if not providers:
            raise EmbeddingError("aucun provider d'embeddings configuré")
        self.providers = providers
        self.active = 0
        self.model_name = providers[0].model_name
        dimensions = {p.dimension for p in providers}
        models = {p.model_name for p in providers}
        if len(dimensions) != 1:
            raise EmbeddingError(f"dimensions incompatibles entre providers: {sorted(dimensions)}")
        if len(models) != 1:
            raise EmbeddingError("les providers fallback doivent utiliser exactement le même modèle d'embeddings")
        self.dimension = providers[0].dimension

    @property
    def current_provider(self) -> EmbeddingProvider:
        return self.providers[self.active]

    def encode_many(self, texts: list[str], *, normalize: bool = True, batch_size: int | None = None):
        last = None
        for idx in range(self.active, len(self.providers)):
            provider = self.providers[idx]
            try:
                result = provider.encode_many(texts, normalize=normalize, batch_size=batch_size)
                self.active = idx
                return result
            except EmbeddingProviderUnavailable as exc:
                last = exc
                continue
        raise EmbeddingProviderUnavailable(f"tous les providers d'embeddings sont indisponibles: {last}")


def embedding_model_from_env(env=os.environ) -> str:
    return env.get("LEGAL_EMBEDDING_MODEL") or env.get("LEGAL_MODEL") or "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2"


def create_embedding_provider(env=os.environ, *, model_name: str | None = None, device: str | None = None) -> EmbeddingProvider:
    model = model_name or embedding_model_from_env(env)
    names = [x.strip().lower() for x in env.get("LEGAL_EMBEDDING_PROVIDERS", "local").split(",") if x.strip()]
    providers: list[EmbeddingProvider] = []
    for name in names:
        if name == "local":
            providers.append(SentenceTransformerEmbedder(model, device=device or env.get("LEGAL_EMBEDDING_DEVICE") or env.get("LEGAL_DEVICE")))
        elif name == "remote":
            base = env.get("LEGAL_EMBEDDING_REMOTE_URL")
            if not base:
                raise EmbeddingError("LEGAL_EMBEDDING_REMOTE_URL requis pour le provider remote")
            try:
                providers.append(RemoteEmbeddingProvider(RemoteEmbeddingConfig(
                    base_url=base,
                    model=model,
                    api_key=env.get("LEGAL_EMBEDDING_API_KEY"),
                    timeout=float(env.get("LEGAL_EMBEDDING_TIMEOUT", "5")),
                    expected_dimension=int(env["LEGAL_EMBEDDING_DIMENSION"]) if env.get("LEGAL_EMBEDDING_DIMENSION") else None,
                )))
            except EmbeddingProviderUnavailable:
                # Startup fallback: an optional LAN GPU may simply be powered off.
                if len(names) == 1:
                    raise
                continue
        else:
            raise EmbeddingError(f"provider d'embeddings inconnu: {name}")
    return providers[0] if len(providers) == 1 else FallbackEmbeddingProvider(providers)
