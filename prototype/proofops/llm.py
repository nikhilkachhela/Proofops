"""Optional LLM access. ProofOps runs fully without an API key (heuristic mode)."""
import os

def available() -> bool:
    return bool(os.getenv("ANTHROPIC_API_KEY") or os.getenv("OPENAI_API_KEY"))

def complete(prompt: str, max_tokens: int = 400) -> str:
    if os.getenv("ANTHROPIC_API_KEY"):
        import anthropic
        client = anthropic.Anthropic()
        model = os.getenv("PROOFOPS_MODEL", "claude-haiku-5-5")
        msg = client.messages.create(model=model, max_tokens=max_tokens,
                                     messages=[{"role": "user", "content": prompt}])
        return "".join(b.text for b in msg.content if getattr(b, "type", "") == "text").strip()
    if os.getenv("OPENAI_API_KEY"):
        from openai import OpenAI
        client = OpenAI()
        model = os.environ["PROOFOPS_MODEL"]  # set explicitly for OpenAI
        r = client.chat.completions.create(model=model, max_tokens=max_tokens,
                                           messages=[{"role": "user", "content": prompt}])
        return r.choices[0].message.content.strip()
    raise RuntimeError("No LLM API key configured")
