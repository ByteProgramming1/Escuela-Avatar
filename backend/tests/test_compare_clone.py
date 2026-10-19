"""scripts.compare_clone: la página de escucha a ciegas no debe delatar qué modelo es cuál hasta pulsar «Revelar»."""
import json

from scripts.compare_clone import PROVIDERS, write_page


def test_blind_page_hides_which_model_is_a_or_b_until_revealed(tmp_path):
    clips = lambda key: {"label": PROVIDERS[key][0], "clips": [{"speaker": "rectora", "n": 1, "file": f"{key}_rectora_1.mp3"}]}  # noqa: E731
    page = write_page(tmp_path, {"clone": clips("clone"), "fish": clips("fish")}, ["rectora"], ["Una frase."], seed=3)
    html = page.read_text(encoding="utf-8")
    body = html.split("<script>")[0]
    assert "Qwen3-TTS" not in body and "Fish Audio" not in body  # nada delata el modelo antes de revelar
    assert body.count("<audio") == 3  # referencia + A + B
    answers = json.loads(html.split("const A=")[1].split(";function")[0])
    assert sorted(answers["rectora-1"].values()) == ["Fish Audio S2", "Qwen3-TTS"]
