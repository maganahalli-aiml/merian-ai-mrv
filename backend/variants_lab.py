"""Variants lab: ways to change retrieval, tried on 22 sentences. Run from backend/:  uv run python variants_lab.py"""
import math
import re

from langchain_chroma import Chroma
from langchain_core.documents import Document
from pydantic import BaseModel, Field

from config.settings import settings
from rag.embeddings import get_embeddings
from rag.llm import extract_text, get_llm
from variants_data import SENTENCES

DOCS = [Document(page_content=text, metadata={"id": id_, "source": source}) for id_, source, text in SENTENCES]
BY_ID = {doc.metadata["id"]: doc for doc in DOCS}

store = Chroma(collection_name="variants_lab", embedding_function=get_embeddings(), persist_directory=settings.chroma_dir)
store.reset_collection()  # start clean every run
store.add_documents(DOCS, ids=list(BY_ID))


def basic(question, k=3):
    return store.similarity_search(question, k=k)


def mmr(question, k=3):
    """Maximal marginal relevance: relevant, but not three copies of the same idea."""
    return store.max_marginal_relevance_search(question, k=k, fetch_k=10)


def hyde(question, k=3):
    """Search with an imagined answer instead of the question (HyDE)."""
    reply = get_llm().invoke(f"Write one sentence that could answer this question: {question}")
    imagined = extract_text(reply.content)  # a plain string; the embedding client rejects reply.text
    return store.similarity_search(imagined, k=k)


def words(text):
    return set(re.findall(r"[a-z0-9]+", text.lower()))


def keyword_rank(question):
    """A tiny keyword ranking: count the shared words, and let rare words count more."""
    vocabulary = set().union(*(words(d.page_content) for d in DOCS))
    rarity = {w: math.log(len(DOCS) / sum(w in words(d.page_content) for d in DOCS)) for w in vocabulary}
    score = {}
    for doc in DOCS:
        shared = words(question) & words(doc.page_content)
        score[doc.metadata["id"]] = sum(rarity[w] for w in shared)
    return sorted(score, key=score.get, reverse=True)


def hybrid(question, k=3):
    """Keyword ranking plus meaning ranking, merged with reciprocal rank fusion."""
    by_meaning = [d.metadata["id"] for d in store.similarity_search(question, k=len(DOCS))]
    fused = {}
    for ranking in (keyword_rank(question), by_meaning):
        for position, id_ in enumerate(ranking):
            fused[id_] = fused.get(id_, 0) + 1 / (60 + position)
    return [BY_ID[id_] for id_ in sorted(fused, key=fused.get, reverse=True)[:k]]


class SubQuestions(BaseModel):
    questions: list[str] = Field(description="the separate simple questions inside the question, at most 3")


def decompose(question, k=2):
    """Split a many-part question into simple ones, search for each, merge the results."""
    splitter = get_llm().with_structured_output(SubQuestions)
    parts = splitter.invoke(f"Split this into separate simple questions: {question}")
    found = {}
    for sub in parts.questions:
        for doc in store.similarity_search(sub, k=k):
            found[doc.metadata["id"]] = doc
    return list(found.values()), parts.questions


def standalone(history, follow_up):
    """Turn a follow-up such as 'And for moderate risk?' into a question that makes sense alone."""
    reply = get_llm().invoke(
        f"Chat so far: {history}\nRewrite the last question so it can be understood alone: {follow_up}"
    )
    return extract_text(reply.content)


class Scores(BaseModel):
    scores: list[int] = Field(description="one relevance score from 0 to 10 per sentence, in the same order")


def rerank(question, k=3):
    """Fetch 8 candidates, let the model score each one, keep the best k."""
    candidates = store.similarity_search(question, k=8)
    numbered = "\n".join(f"{n}. {d.page_content}" for n, d in enumerate(candidates, 1))
    result = get_llm().with_structured_output(Scores).invoke(
        f"Question: {question}\nScore each sentence from 0 to 10 for how well it answers the question.\n{numbered}"
    )
    ranked = sorted(zip(result.scores, candidates), key=lambda pair: pair[0], reverse=True)
    return [doc for _, doc in ranked[:k]]


def parent_page(question, k=3):
    """Search small pieces, hand over the whole page they came from."""
    pages = {}
    for hit in store.similarity_search(question, k=k):
        source = hit.metadata["source"]
        text = " ".join(d.page_content for d in DOCS if d.metadata["source"] == source)
        pages[source] = Document(page_content=text, metadata={"id": source})
    return list(pages.values())


if __name__ == "__main__":
    question = "When do we pay servo motor suppliers?"
    for method in (basic, mmr, hyde, hybrid, rerank, parent_page):
        print(f"{method.__name__:12}", [d.metadata["id"] for d in method(question)])

    two_parts = "What payment terms do servo motor suppliers get, and what duty do we pay on servo motors?"
    docs, sub_questions = decompose(two_parts)
    print("decompose   ", [d.metadata["id"] for d in docs], sub_questions)
    print("standalone  ", standalone("Q: What terms do low risk vendors get? A: Net-45.", "And for moderate risk?"))
