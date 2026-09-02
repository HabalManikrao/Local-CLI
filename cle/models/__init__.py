"""Model provider abstraction, registry, and router.

All LLM communication passes through :class:`~cle.models.base.ModelProvider`.
Ollama is one implementation; future online providers implement the same
interface without changing the rest of the system.
"""
