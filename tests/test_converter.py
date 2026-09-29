from app.converter import join_parts


def test_join_mends_paragraph_split_across_pages():
    head = "## Intro\n\nThe model runs when CUDA is available and"
    assert join_parts(head, "discovered by the runtime.") == head + " discovered by the runtime."


def test_join_keeps_separate_blocks():
    assert join_parts("Fim da frase.", "começo novo") == "Fim da frase.\n\ncomeço novo"
    assert join_parts("Sem ponto", "## Título") == "Sem ponto\n\n## Título"
    assert join_parts("Sem ponto", "Maiúscula inicia outro bloco") == "Sem ponto\n\nMaiúscula inicia outro bloco"
    assert join_parts("| a | b |", "continua") == "| a | b |\n\ncontinua"
    assert join_parts("", "texto") == "texto"
    assert join_parts("texto", "  ") == "texto"
