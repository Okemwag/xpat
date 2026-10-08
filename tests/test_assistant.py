"""The Xpat assistant: documentation search, grounded answers, figure checks and the no-AI fallback (fake LLM only)."""

import pytest
from floodcat.ai.assistant import KnowledgeBase, Passage, answer
from floodcat.core.errors import ModelError


class FakeLLM:
    model = "fake-gemini"

    def __init__(self, response):
        self.response, self.calls = response, []

    def generate_json(self, system, prompt, schema):
        self.calls.append((system, prompt))
        return self.response


@pytest.fixture(scope="module")
def kb():
    return KnowledgeBase.from_files()


def test_search_finds_the_right_documentation(kb):
    assert (
        kb.search("what is the organisation code")[0].heading == "The organisation code"
    )
    assert (
        kb.search("how do I create an account as a user")[0].heading
        == "Creating an account"
    )
    assert any(
        "Drainage" in p.heading or "baseline hazard" in p.heading
        for p in kb.search("why does the model miss Kibera drainage", 3)
    )
    assert kb.search("zzzz qqqq") == []


def test_without_a_model_it_quotes_the_best_passage(kb):
    out = answer("How do I sign in?", kb)
    assert (
        out["mode"] == "search"
        and out["answerable"]
        and out["sources"][0]["heading"] == "Signing in"
    )
    assert "Signing in" in out["answer"]
    nothing = answer("zzzz qqqq", kb)
    assert not nothing["answerable"] and nothing["sources"] == []


def test_model_answer_cites_real_passages_and_flags_invented_figures(kb):
    passages = kb.search("organisation code")
    llm = FakeLLM(
        {
            "answerable": True,
            "answer": "The code looks like ABCD-EFGH and costs KES 5,000.",
            "sources": [passages[0].pid, 9999],
        }
    )
    out = answer("What is the organisation code? mail me at a@b.com", kb, llm)
    assert out["mode"] == "ai" and [s["heading"] for s in out["sources"]] == [
        passages[0].heading
    ]  # unknown id dropped
    assert "5000" in out["unsupported_figures"]
    system, prompt = llm.calls[0]
    assert (
        "a@b.com" not in prompt
        and '"question": "What is the organisation code?' in prompt
    )  # redacted, sent as data
    assert "never tell anyone to bind" in system


def test_uncited_answer_is_not_marked_answerable_and_results_facts_count(kb):
    out = answer(
        "Will it rain tomorrow?",
        kb,
        FakeLLM({"answerable": True, "answer": "Probably.", "sources": []}),
    )
    assert not out["answerable"]
    facts = [
        {
            "label": "Average annual loss",
            "text": "average annual loss KES 85.0 m",
            "provenance": "ASSUMPTION",
        }
    ]
    out = answer(
        "What is my average annual loss?",
        kb,
        FakeLLM(
            {
                "answerable": True,
                "answer": "Your average annual loss is KES 85.0 m.",
                "sources": [],
            }
        ),
        facts=facts,
    )
    assert out["answerable"] and out["unsupported_figures"] == []


def test_follow_up_questions_use_the_conversation(kb):
    history = [
        {"role": "user", "content": "What is the organisation code?"},
        {"role": "assistant", "content": "It looks like ABCD-EFGH."},
    ]
    out = answer("and who sees it?", kb, history=history)
    assert out["sources"] and out["sources"][0]["heading"] == "The organisation code"


def test_input_limits_and_bad_model_output(kb):
    with pytest.raises(ModelError):
        answer("   ", kb)
    with pytest.raises(ModelError):
        answer("x" * 801, kb)
    with pytest.raises(ModelError):
        answer("How do I sign in?", kb, FakeLLM({"answer": ""}))


def test_long_sections_are_split_and_titles_weigh_more():
    small = KnowledgeBase(
        [
            Passage(1, "a.md", "A", "Pricing", "premium premium"),
            Passage(2, "b.md", "B", "Other", "pricing mentioned once"),
        ]
    )
    assert small.search("pricing")[0].pid == 1


def test_round_figures_are_reported_plainly_not_in_exponent_form():
    from floodcat.ai.briefing import unsupported_numbers

    assert unsupported_numbers(
        ["It costs KES 5,000 or 1,200,000."], [{"text": "nothing here"}]
    ) == ["1200000", "5000"]
    assert unsupported_numbers(["KES 5,000"], [{"text": "a fee of 5000.00"}]) == []
