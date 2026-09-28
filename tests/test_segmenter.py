from app.segmenter import clean_inline, segment_markdown, split_sentences


def test_clean_inline_strips_markdown():
    assert clean_inline("**Bold** and [link](http://x) with `code` and ![img](a.png)") == "Bold and link with code and"
    assert clean_inline(r"snake\_case &amp; more <!-- image -->") == "snake_case & more"


def test_split_keeps_abbreviations_and_initials():
    text = "O Dr. Silva chegou cedo ao hospital. J. R. R. Tolkien escreveu muitos livros! Você já leu algum deles?"
    assert split_sentences(text) == [
        "O Dr. Silva chegou cedo ao hospital.",
        "J. R. R. Tolkien escreveu muitos livros!",
        "Você já leu algum deles?",
    ]


def test_short_sentences_are_merged():
    assert split_sentences("Sim. Ele saiu de casa bem cedo hoje.") == ["Sim. Ele saiu de casa bem cedo hoje."]


def test_split_cjk_without_spaces():
    first = "今天天气很好，阳光明媚，微风轻轻吹过，我们一起去公园散步吧。"
    second = "你想一起去吗？"
    assert split_sentences(first + second) == [first, second]


def test_long_sentence_is_split_at_natural_breaks():
    long = ", ".join(["uma parte razoavelmente longa da frase"] * 20) + "."
    pieces = split_sentences(long)
    assert len(pieces) > 1
    assert all(len(p) <= 280 for p in pieces)
    assert " ".join(pieces) == long


def test_segment_markdown_structure():
    md = """## Título

Primeira frase do parágrafo. Segunda frase dele.

- item um
- item dois

| a | b |
|---|---|
| 1 | 2 |

```python
print("não deve ser lido")
```

<!-- image -->
> Uma citação.
"""
    content = segment_markdown(md)
    types = [b["type"] for b in content["blocks"]]
    assert types == ["heading", "paragraph", "list", "list", "table", "quote"]
    texts = [s["text"] for s in content["segments"]]
    assert "print" not in " ".join(texts)
    assert texts[0] == "Título"
    assert content["blocks"][4]["rows"] == ["a · b", "1 · 2"]
    # cada segmento aponta para o bloco dono
    for s in content["segments"]:
        assert s["id"] in content["blocks"][s["block"]]["segments"]
