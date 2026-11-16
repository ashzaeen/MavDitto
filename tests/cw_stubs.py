"""A stub LLM client for the Content Writer tests: answers each call by the
requested output schema, so generate -> review -> redraft loops can be
driven end to end with no network and no credentials. Same Anthropic SDK
shapes as the other stubs (`messages.parse`, `messages.count_tokens`)."""

from types import SimpleNamespace


def usage(input_tokens=800, output_tokens=200):
    return SimpleNamespace(input_tokens=input_tokens, output_tokens=output_tokens,
                           cache_creation_input_tokens=0, cache_read_input_tokens=0)


class RoutingStub:
    """`routes` maps an output schema's class name to either a single parsed
    object (returned every time) or a list (returned in order, last one
    repeating)."""

    def __init__(self, routes):
        self.routes = routes
        self.calls = []
        self.messages = SimpleNamespace(parse=self._parse, count_tokens=self._count)

    def _count(self, **kw):
        return SimpleNamespace(input_tokens=800)

    def _parse(self, **kw):
        name = kw["output_format"].__name__
        self.calls.append((name, kw))
        route = self.routes[name]
        if isinstance(route, list):
            n = sum(1 for c, _ in self.calls if c == name) - 1
            route = route[min(n, len(route) - 1)]
        return SimpleNamespace(parsed_output=route, usage=usage(), stop_reason="end_turn")

    def count(self, name):
        return sum(1 for c, _ in self.calls if c == name)

    def system_text(self, name, n=0):
        kws = [kw for c, kw in self.calls if c == name]
        return kws[n]["system"][0]["text"]

    def user_text(self, name, n=0):
        kws = [kw for c, kw in self.calls if c == name]
        content = kws[n]["messages"][0]["content"]
        return content if isinstance(content, str) else " ".join(
            b.get("text", "") for b in content if isinstance(b, dict))


def clean_critic():
    from src.content_writer.review import CriticOutput
    return CriticOutput(voice_match=5, tone_fit=5, clarity=5, fact_fidelity=5)
