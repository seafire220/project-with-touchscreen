"""Web search for characters whose language model has none of its own.

Claude models search through Anthropic's own web search tool (see
anthropic_llm.py). Other models ask for a search with a [search ...] tag;
the device runs it here with the owner's search key and gives the results
back to the model for a short spoken answer.

The search service is Tavily (it has a free monthly allowance). Its key is
stored as the "search" key.
"""
import aiohttp

from .providers import ProviderError, _status_error

URL = "https://api.tavily.com/search"
MAX_RESULTS = 4
MAX_CHARS = 1800


class TavilySearch:
    def __init__(self, key):
        if not key:
            raise ProviderError("no web search key is set")
        self.key = key

    async def search(self, query):
        body = {"query": query[:300], "max_results": MAX_RESULTS, "search_depth": "basic", "include_answer": False}
        headers = {"Authorization": "Bearer " + self.key, "Content-Type": "application/json"}
        async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=20)) as session:
            try:
                async with session.post(URL, json=body, headers=headers) as r:
                    if r.status != 200:
                        raise _status_error("Web search", r.status, await r.text())
                    data = await r.json(content_type=None)
            except aiohttp.ClientError as error:
                raise ProviderError("web search could not be reached (%s)" % type(error).__name__, retry=True)
        return [{"title": item.get("title", ""), "url": item.get("url", ""), "content": item.get("content", "")}
                for item in data.get("results", [])]


def results_for_model(query, results):
    """Search results as a message the model can answer from."""
    if not results:
        return "(The web search for \"%s\" found nothing. Say so briefly.)" % query
    lines, used = [], 0
    for item in results:
        text = "- %s: %s" % (item["title"], " ".join(item["content"].split()))
        if used + len(text) > MAX_CHARS:
            text = text[:max(0, MAX_CHARS - used)]
        lines.append(text)
        used += len(text)
        if used >= MAX_CHARS:
            break
    return ("(Web search results for \"%s\":\n%s\nAnswer the person's question from these, in one to three "
            "spoken sentences. Do not read out web addresses.)" % (query, "\n".join(lines)))
