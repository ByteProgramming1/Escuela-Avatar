import json
import time

import pytest
from fastapi.testclient import TestClient

from app.assistant import Assistant
from app.config import Settings
from app.knowledge import load_knowledge
from app.main import create_app

from .fakes import FakeLLM, FakeSTT, FakeTTS, chains


@pytest.fixture
def env(tmp_path):
    settings = Settings(static_dir=tmp_path / "static", prime_cache_on_start=False, preload_presentation=False)
    stt, llm, tts = FakeSTT(), FakeLLM(), FakeTTS()
    assistant = Assistant(settings, load_knowledge(settings.knowledge_dir), *chains([stt], [llm], [tts]))
    with TestClient(create_app(assistant, settings)) as client:
        yield client, settings, stt, llm, tts, assistant


def wait_for(cond, timeout=3.0):
    """Espera a una condición que cumple una tarea en segundo plano del servidor (corre en otro hilo)."""
    end = time.monotonic() + timeout
    while not cond():
        assert time.monotonic() < end, "la tarea en segundo plano no terminó a tiempo"
        time.sleep(0.01)


def post_audio(client, path="/audio", **form):
    return client.post(path, files={"audio": ("input.wav", b"RIFFfake", "audio/wav")}, data=form)


def test_audio_flow_writes_mp3_with_the_right_voice(env):
    client, settings, stt, llm, tts, _ = env
    r = post_audio(client, speaker="oswaldo", response_file="response_oswaldo.mp3")
    assert r.status_code == 200
    body = r.json()
    assert body["file"] == "response_oswaldo.mp3" and body["transcript"].startswith("¿Cuánto")
    assert "Responde oswaldo" in body["result"]
    assert {"stt", "llm_first_token", "first_audio", "total"} <= set(body["timings"])
    assert all(speaker == "oswaldo" for _, speaker in tts.calls)
    served = client.get("/static/response_oswaldo.mp3")
    assert served.status_code == 200 and served.content.startswith(b"<fake-tts:oswaldo:")
    assert client.head("/static/nope.mp3").status_code == 404  # el cliente Unity usa HEAD para decidir si generar


def test_stream_endpoint_returns_same_audio_as_the_saved_file(env):
    client, settings, _, llm, tts, assistant = env
    with client.stream("POST", "/audio/stream", files={"audio": ("input.wav", b"RIFFfake", "audio/wav")},
                       data={"speaker": "rectora", "response_file": "response_rectora.mp3"}) as r:
        assert r.status_code == 200 and r.headers["content-type"] == "audio/mpeg"
        streamed = b"".join(r.iter_bytes())
    assert streamed.startswith(b"<fake-tts:rectora:") and streamed.count(b"<fake-tts") >= 2
    assert (settings.static_dir / "response_rectora.mp3").read_bytes() == streamed  # respaldo completo en disco
    assert len(assistant.history.messages()) == 2  # la conversación quedó en memoria


def test_stream_leaves_transcript_answer_and_timings_next_to_the_mp3(env):
    """La página /e2e no puede leerlos del stream: los lee de /static/<nombre>.json, que debe existir al cerrarse la respuesta."""
    client, *_ = env
    with client.stream("POST", "/audio/stream", files={"audio": ("input.wav", b"RIFFfake", "audio/wav")},
                       data={"speaker": "oswaldo", "response_file": "web_e2e_oswaldo.mp3"}) as r:
        b"".join(r.iter_bytes())
    saved = client.get("/static/web_e2e_oswaldo.json").json()
    assert saved["transcript"].startswith("¿Cuánto") and "Responde oswaldo" in saved["answer"]
    assert {"stt", "llm_first_token", "first_audio_total", "total"} <= set(saved["timings"])


def test_stream_reports_the_reprompt_when_nothing_was_understood(env):
    client, _, stt, llm, _, _ = env
    stt.text = ""
    with client.stream("POST", "/audio/stream", files={"audio": ("input.wav", b"RIFFfake", "audio/wav")},
                       data={"speaker": "rectora", "response_file": "web_e2e_rectora.mp3"}) as r:
        b"".join(r.iter_bytes())
    saved = client.get("/static/web_e2e_rectora.json").json()
    assert saved["transcript"] == "" and "repetir" in saved["answer"] and llm.calls == []


def test_e2e_page_is_served(env):
    client, *_ = env
    r = client.get("/e2e")
    assert r.status_code == 200 and r.headers["content-type"].startswith("text/html")
    assert "/audio/stream" in r.text


def test_stream_errors_before_first_audio_are_normal_http_errors(env):
    client, _, stt, llm, tts, _ = env
    tts.fail = True
    r = post_audio(client, "/audio/stream", speaker="rectora")
    assert r.status_code == 503 and "fake-tts caído" in r.json()["detail"]
    stt.fail = True
    assert post_audio(client, "/audio/stream", speaker="rectora").status_code == 503


def test_stream_with_no_tts_for_the_speaker_says_so(tmp_path):
    settings = Settings(static_dir=tmp_path / "s", prime_cache_on_start=False, preload_presentation=False)
    a = Assistant(settings, load_knowledge(settings.knowledge_dir), *chains(tts_list=[FakeTTS(speakers=("oswaldo",))]))
    with TestClient(create_app(a, settings)) as client:
        r = post_audio(client, "/audio/stream", speaker="rectora")
        assert r.status_code == 503 and "No hay TTS" in r.json()["detail"]


def test_follow_up_question_receives_history_and_reset_clears_it(env):
    client, _, _, llm, _, _ = env
    post_audio(client, speaker="rectora"); post_audio(client, speaker="rectora")
    assert llm.calls[0][2] == [] and len(llm.calls[1][2]) == 2
    client.post("/reset")
    post_audio(client, speaker="rectora")
    assert llm.calls[2][2] == []


@pytest.mark.parametrize("path", ["/audio", "/audio/stream"])
def test_empty_transcript_asks_to_repeat_without_calling_llm(env, path):
    client, _, stt, llm, _, _ = env
    stt.text = ""
    r = post_audio(client, path, speaker="rectora")
    assert r.status_code == 200 and llm.calls == []
    assert ("repetir" in r.json()["result"]) if path == "/audio" else r.content.startswith(b"<fake-tts")


def test_bad_inputs_are_rejected(env):
    client, *_ = env
    assert post_audio(client, speaker="nadie").status_code == 400
    assert post_audio(client, speaker="rectora", response_file="../x.mp3").status_code == 400
    assert client.post("/tts", json={"text": "hola", "speaker": "rectora", "filename": "a/b.mp3"}).status_code == 400
    assert client.post("/presentation", json={"question": 99, "speaker": "rectora"}).status_code == 404


def test_tts_endpoint_for_intro_lines(env):
    client, _, _, llm, tts, _ = env
    r = client.post("/tts", json={"text": "¡Rectora! Qué gusto verla.", "speaker": "oswaldo", "filename": "intro_0.mp3"})
    assert r.json() == {"result": "ok", "file": "intro_0.mp3", "speaker": "oswaldo"}
    assert client.get("/static/intro_0.mp3").content.startswith(b"<fake-tts:oswaldo:") and llm.calls == []


def test_presentation_is_generated_once_then_served_from_disk(env):
    client, settings, _, llm, tts, _ = env
    a = client.post("/presentation", json={"question": 3, "speaker": "rectora"}).json()
    n_tts = len(tts.calls)
    b = client.post("/presentation", json={"question": 3, "speaker": "rectora"}).json()
    assert a == b and a["file"] == "presentation_rectora_q3.mp3" and a["question"] == 3
    assert len(llm.calls) == 1 and len(tts.calls) == n_tts
    c = client.post("/presentation", json={"question": 3, "speaker": "oswaldo"}).json()
    assert c["file"] == "presentation_oswaldo_q3.mp3" and len(llm.calls) == 2


def stale_key(settings, name):
    meta = settings.static_dir / f"{name}.json"
    data = json.loads(meta.read_text(encoding="utf-8"))
    data["key"] = "viejo"
    meta.write_text(json.dumps(data), encoding="utf-8")


def test_stale_presentation_is_served_at_once_and_regenerated_in_background(env):
    client, settings, _, llm, tts, assistant = env
    first = client.post("/presentation", json={"question": 1, "speaker": "rectora"}).json()
    stale_key(settings, "presentation_rectora_q1")
    again = client.post("/presentation", json={"question": 1, "speaker": "rectora"}).json()
    assert again == first  # no esperó al LLM: devolvió lo que había
    wait_for(lambda: len(llm.calls) == 2 and not assistant._tasks)
    meta = json.loads((settings.static_dir / "presentation_rectora_q1.json").read_text(encoding="utf-8"))
    assert meta["key"] != "viejo" and not meta["key"].endswith("!degraded")  # ya quedó vigente
    client.post("/presentation", json={"question": 1, "speaker": "rectora"})
    assert len(llm.calls) == 2  # y la siguiente sale de disco sin llamar al LLM


def test_presentation_is_not_regenerated_twice_for_repeated_key_presses(env):
    client, settings, _, llm, tts, assistant = env
    client.post("/presentation", json={"question": 4, "speaker": "oswaldo"})
    stale_key(settings, "presentation_oswaldo_q4")
    for _ in range(3):  # el usuario pulsa la tecla varias veces seguidas
        client.post("/presentation", json={"question": 4, "speaker": "oswaldo"})
    wait_for(lambda: not assistant._tasks)
    assert len(llm.calls) == 2  # la generación inicial + una sola regeneración


def test_presentation_with_unreadable_metadata_is_generated_again(env):
    client, settings, _, llm, *_ = env
    client.post("/presentation", json={"question": 2, "speaker": "rectora"})
    (settings.static_dir / "presentation_rectora_q2.json").write_text("{no es json", encoding="utf-8")
    r = client.post("/presentation", json={"question": 2, "speaker": "rectora"})
    assert r.status_code == 200 and len(llm.calls) == 2  # sin audio utilizable no queda más que esperar


def test_presentation_made_with_a_fallback_is_served_at_once_and_refreshed_when_the_primary_recovers(tmp_path):
    """El audio de emergencia suena de inmediato; en cuanto el principal vuelve se cambia por uno bueno."""
    settings = Settings(static_dir=tmp_path / "s", prime_cache_on_start=False, preload_presentation=False)
    primary, backup = FakeLLM("principal"), FakeLLM("respaldo")
    primary.fail_before = True
    a = Assistant(settings, load_knowledge(settings.knowledge_dir), *chains(llms=[primary, backup], cooldown=60))
    meta_path = settings.static_dir / "presentation_rectora_q2.json"
    with TestClient(create_app(a, settings)) as client:
        first = client.post("/presentation", json={"question": 2, "speaker": "rectora"}).json()  # no había nada: se genera
        assert len(backup.calls) == 1 and json.loads(meta_path.read_text(encoding="utf-8"))["key"].endswith("!degraded")
        again = client.post("/presentation", json={"question": 2, "speaker": "rectora"}).json()
        assert again == first and not a._tasks  # el principal sigue en cooldown: no tiene sentido regenerar
        assert len(primary.calls) == 1 and len(backup.calls) == 1

        primary.fail_before = False
        a.llm._failed_until.clear(); a.llm.degraded_at = 0.0  # el principal se recupera
        assert client.post("/presentation", json={"question": 2, "speaker": "rectora"}).json() == first  # aún el de emergencia
        wait_for(lambda: len(primary.calls) == 2 and not a._tasks)
        assert not json.loads(meta_path.read_text(encoding="utf-8"))["key"].endswith("!degraded")
        client.post("/presentation", json={"question": 2, "speaker": "rectora"})
        assert len(primary.calls) == 2 and len(backup.calls) == 1  # desde ahora sale de disco


def test_health_lists_active_providers(env):
    client, *_ = env
    body = client.get("/health").json()
    assert body["speakers"] == ["oswaldo", "rectora"]
    assert body["providers"]["stt"] == "fake-stt" and body["providers"]["tts[rectora]"] == "fake-tts"
