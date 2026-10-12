"""Cliente LLM OpenAI-compatible (OpenRouter) — self-contained, só httpx.

Modelo trocável (default GLM-5.2). Retry generoso (a rede reseta muito) +
salvage de JSON (modelos embrulham em cerca markdown). Sem Google, sem torch.
Chave: env OPENROUTER_API_KEY (ou DEEPSEEK_API_KEY, compat com os experimentos).
"""
from __future__ import annotations

import json
import os
import random
import re
import time

import httpx

MODELO_PADRAO = "z-ai/glm-5.2"
BASE_URL = "https://openrouter.ai/api/v1"


def _desembrulhar(v) -> dict | None:
    """O objeto pedido, ou None.

    Mesmo com `response_format: json_object` o modelo às vezes embrulha a
    resposta num ARRAY de um elemento (visto no gemini-3.1-flash-lite, caso
    1289: extração perfeita, `[{...}]`). Sem isto o chamador recebe uma `list`,
    chama `.get` e o caso inteiro morre com AttributeError — 2 em 6 no piloto.
    Array de VÁRIOS elementos é ambíguo (qual conta?) e vira None de propósito.
    """
    if isinstance(v, dict):
        return v
    if isinstance(v, list) and len(v) == 1 and isinstance(v[0], dict):
        return v[0]
    return None


def salvage_json(txt: str) -> dict | None:
    if not txt:
        return None
    t = re.sub(r"^```(?:json)?|```$", "", txt.strip(), flags=re.M).strip()
    try:
        return _desembrulhar(json.loads(t))
    except Exception:
        pass
    i, j = t.find("{"), t.rfind("}")
    if i >= 0 and j > i:
        try:
            return _desembrulhar(json.loads(t[i:j + 1]))
        except Exception:
            return None
    return None


class LLM:
    def __init__(self, modelo: str | None = None, api_key: str | None = None,
                 base_url: str | None = None, reasoning: str = "off"):
        self.modelo = modelo or os.environ.get("PREFILL_MODELO", MODELO_PADRAO)
        self.key = (api_key or os.environ.get("OPENROUTER_API_KEY")
                    or os.environ.get("DEEPSEEK_API_KEY"))
        if not self.key:
            raise RuntimeError("Sem API key (OPENROUTER_API_KEY).")
        self.base = base_url or os.environ.get("OPENROUTER_BASE_URL", BASE_URL)
        self.reasoning = reasoning
        self.custo_total = 0.0

    def responder(self, prompt: str, max_tokens: int = 8192) -> tuple[str, dict]:
        body = {
            "model": self.modelo,
            "messages": [{"role": "user", "content": prompt}],
            "response_format": {"type": "json_object"},
            "temperature": 0.0,
            "max_tokens": max_tokens,
        }
        if self.reasoning == "off":
            body["reasoning"] = {"enabled": False}
        ultimo = None
        for tent in range(8):  # rede reseta muito (WinError 10054) → retry generoso
            try:
                t0 = time.perf_counter()
                r = httpx.post(f"{self.base}/chat/completions",
                               headers={"Authorization": f"Bearer {self.key}"},
                               json=body, timeout=180.0)
                lat = time.perf_counter() - t0
                if r.status_code == 400 and "reasoning" in r.text.lower():
                    body.pop("reasoning", None)
                    continue
                if r.status_code == 429 or r.status_code >= 500:
                    ultimo = f"HTTP {r.status_code}"
                    time.sleep(2 * (2 ** tent) + random.uniform(0, 1))
                    continue
                r.raise_for_status()
                d = r.json()
                if "error" in d:
                    ultimo = str(d["error"])[:160]
                    time.sleep(2 * (2 ** tent) + random.uniform(0, 1))
                    continue
                u = d.get("usage", {}) or {}
                self.custo_total += float(u.get("cost", 0) or 0)
                return d["choices"][0]["message"]["content"] or "", {
                    "lat": lat, "custo": float(u.get("cost", 0) or 0)}
            except (httpx.TransportError, httpx.TimeoutException) as e:
                ultimo = type(e).__name__
                time.sleep(2 * (2 ** tent) + random.uniform(0, 1))
        raise RuntimeError(f"LLM falhou após retries: {ultimo}")
