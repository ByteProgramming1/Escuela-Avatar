using System.Collections;
using UnityEngine;
using UnityEngine.Networking;

/// <summary>
/// Sistema de conversación dual entre dos avatares.
///
/// Teclas:
///   W / Espacio → Graba audio del usuario → el avatar activo responde con IA
///   Tab         → Alterna tab activo: Rectora ↔ Oswaldo
///   R           → Nueva familia: el servidor olvida la conversación anterior (POST /reset)
///   1-9         → Reproduce pregunta pregrabada del tab activo (pregunta 1-9)
///   0           → Reproduce pregunta 10 del tab activo
/// </summary>
public class VoiceAssistant : MonoBehaviour
{
    [Header("Servidor")]
    public string serverUrl = "http://localhost:5000";

    [Tooltip("Reproduce la respuesta mientras el servidor aún la genera (POST /audio/stream). " +
             "Desactívalo para volver a la descarga completa (POST /audio).")]
    public bool useStreaming = true;
    [Tooltip("Bytes que deben llegar antes de empezar a sonar. Con el MP3 de 48 kbps del servidor, " +
             "6000 bytes ≈ 1 s de audio. Más = más margen contra cortes; menos = empieza antes. " +
             "Las muletillas del servidor (~4 s ≈ 24000 bytes) lo superan de golpe, así que suenan nada más llegar.")]
    public int streamPrebufferBytes = 7000;

    [Header("Avatar Rectora (682bca91f23c99d01dd49ed4)")]
    public AudioSource audioRectora;
    public MonoBehaviour voiceHandlerRectora;
    [Tooltip("Nombre del speaker en el servidor (coincide con VOICE_ID_<NOMBRE> en .env)")]
    public string speakerRectora = "rectora";

    [Header("Avatar Oswaldo (S08EeYdBk5kmUyDobiiY)")]
    public AudioSource audioECI;
    public MonoBehaviour voiceHandlerECI;
    [Tooltip("Nombre del speaker en el servidor (coincide con VOICE_ID_<NOMBRE> en .env)")]
    public string speakerOswaldo = "oswaldo";

    // true = responde la rectora, false = responde el ECI
    private bool rectoraResponde = true;
    private string micDevice;
    private AudioClip recordedClip;
    // Instante en que se soltó la tecla: base de los cronómetros "⏱️" del log (cuánto tarda en sonar la respuesta)
    private float releasedAt;

    [System.Serializable]
    class ServerResponse
    {
        public string result;
        public string file;
        public int question;
        public string speaker;
    }

    void Start()
    {
        if (Microphone.devices.Length > 0)
            micDevice = Microphone.devices[0];
        else
            Debug.LogError("❌ No hay micrófono disponible");

        Debug.Log("Tab=Cambiar tab (Rectora/Oswaldo) | R=Nueva familia | 0-9=Pregunta pregrabada | W/Espacio=Hablar");
    }

    void Update()
    {
        // Tab: alterna el tab activo (Rectora ↔ Oswaldo)
        if (Input.GetKeyDown(KeyCode.Tab))
        {
            rectoraResponde = !rectoraResponde;
            Debug.Log(rectoraResponde ? "📋 Tab: RECTORA" : "📋 Tab: OSWALDO");
        }

        // R: nueva familia → el servidor olvida lo conversado (si no, la siguiente pregunta hereda el contexto)
        if (Input.GetKeyDown(KeyCode.R))
            StartCoroutine(ResetConversation());

        // W o Espacio: grabar audio del usuario → el avatar del tab activo responde
        bool startRec = Input.GetKeyDown(KeyCode.W) || Input.GetKeyDown(KeyCode.Space);
        bool stopRec  = Input.GetKeyUp(KeyCode.W)   || Input.GetKeyUp(KeyCode.Space);

        if (startRec)
        {
            recordedClip = Microphone.Start(micDevice, false, 300, 44100);
            Debug.Log("🎤 Grabando...");
        }

        if (stopRec && recordedClip != null)
        {
            releasedAt = Time.realtimeSinceStartup;
            int len = Microphone.GetPosition(micDevice);
            Microphone.End(micDevice);
            if (len > 0)
            {
                AudioSource   targetAudio   = rectoraResponde ? audioRectora       : audioECI;
                MonoBehaviour targetHandler = rectoraResponde ? voiceHandlerRectora : voiceHandlerECI;
                string        speaker       = rectoraResponde ? speakerRectora      : speakerOswaldo;
                string        respFile      = rectoraResponde ? "response_rectora.mp3" : "response_oswaldo.mp3";

                StartCoroutine(SendRecordedAudio(recordedClip, len, speaker, respFile, targetAudio, targetHandler));
            }
            recordedClip = null;
        }

        // Teclas 0-9: pregunta pregrabada del tab activo
        // 0 → pregunta 10, 1-9 → pregunta 1-9
        for (int key = 0; key <= 9; key++)
        {
            if (Input.GetKeyDown(KeyCode.Alpha0 + key) || Input.GetKeyDown(KeyCode.Keypad0 + key))
            {
                int questionNumber = (key == 0) ? 10 : key;
                string speaker = rectoraResponde ? speakerRectora : speakerOswaldo;
                StartCoroutine(PlayPreguntaPregrabada(questionNumber, speaker));
                break;
            }
        }
    }

    // ── Flujo W/Espacio ────────────────────────────────────────────────────────

    IEnumerator SendRecordedAudio(AudioClip clip, int length,
        string speaker, string respFile,
        AudioSource targetAudio, MonoBehaviour targetHandler)
    {
        float[] samples = new float[length * clip.channels];
        clip.GetData(samples, 0);
        AudioClip trimmed = AudioClip.Create("Trimmed", length, clip.channels, clip.frequency, false);
        trimmed.SetData(samples, 0);

        byte[] wav = WavUtility.FromAudioClip(trimmed);
        WWWForm form = new WWWForm();
        form.AddBinaryData("audio", wav, "input.wav", "audio/wav");
        form.AddField("speaker", speaker);
        form.AddField("response_file", respFile);

        Debug.Log("⏳ Procesando audio...");

        if (useStreaming)
        {
            StreamResult result = StreamResult.ServerError;
            yield return StreamAndPlay(form, targetAudio, targetHandler, r => result = r);
            if (result != StreamResult.NotPlayable)
                yield break;

            // El servidor respondió bien pero Unity no pudo reproducir el stream:
            // el archivo completo ya quedó en /static, así que se descarga como antes.
            Debug.LogWarning("⚠️ No se pudo reproducir en streaming; descargo el archivo completo.");
            yield return DownloadAndPlay($"{serverUrl}/static/{respFile}", targetAudio, targetHandler);
            yield break;
        }

        using (var www = UnityWebRequest.Post($"{serverUrl}/audio", form))
        {
            yield return www.SendWebRequest();
            if (www.result == UnityWebRequest.Result.Success)
            {
                Debug.Log("✅ Respuesta AI recibida");
                yield return DownloadAndPlay($"{serverUrl}/static/{respFile}", targetAudio, targetHandler);
            }
            else
            {
                Debug.LogError($"❌ Error enviando audio: {www.error}");
            }
        }
    }

    // ── Streaming: empieza a sonar mientras el servidor sigue generando ───────

    enum StreamResult { Played, ServerError, NotPlayable }

    IEnumerator StreamAndPlay(WWWForm form, AudioSource target, MonoBehaviour handler,
        System.Action<StreamResult> done)
    {
        string url = $"{serverUrl}/audio/stream";
        var audioHandler = new DownloadHandlerAudioClip(url, AudioType.MPEG) { streamAudio = true };

        using (var www = UnityWebRequest.Post(url, form))
        {
            www.downloadHandler = audioHandler;
            var op = www.SendWebRequest();

            // 1) Esperar a que llegue un colchón de audio (o a que la petición termine)
            while (!op.isDone && www.downloadedBytes < (ulong)streamPrebufferBytes)
                yield return null;
            Debug.Log($"⏱️ Llegó el colchón de audio ({www.downloadedBytes} bytes) a {Time.realtimeSinceStartup - releasedAt:F1}s de soltar la tecla");

            if (www.result != UnityWebRequest.Result.Success &&
                www.result != UnityWebRequest.Result.InProgress)
            {
                Debug.LogError($"❌ Error en streaming de audio: {www.error}");
                done(StreamResult.ServerError);
                yield break;
            }

            // 2) El clip en streaming puede tardar unos frames en existir
            AudioClip streamClip = audioHandler.audioClip;
            float giveUpAt = Time.realtimeSinceStartup + 3f;
            while (streamClip == null && !op.isDone && Time.realtimeSinceStartup < giveUpAt)
            {
                yield return null;
                streamClip = audioHandler.audioClip;
            }

            if (streamClip == null || target == null)
            {
                // Dejar que termine la petición: así el servidor completa y guarda el archivo
                while (!op.isDone) yield return null;
                done(www.result == UnityWebRequest.Result.Success
                    ? StreamResult.NotPlayable : StreamResult.ServerError);
                yield break;
            }

            // 3) Reproducir ya (mismo patrón que DownloadAndPlay) y seguir recibiendo
            target.clip = streamClip;
            target.Play();
            if (handler != null)
                handler.SendMessage("PlayAudioClip", streamClip, SendMessageOptions.DontRequireReceiver);
            Debug.Log($"🔊 Reproduciendo en streaming en {target.gameObject.name} — suena a {Time.realtimeSinceStartup - releasedAt:F1}s de soltar la tecla");

            while (!op.isDone) yield return null;
            if (www.result != UnityWebRequest.Result.Success)
                Debug.LogError($"❌ El streaming se cortó: {www.error}");

            // El clip en streaming depende de la petición: no liberarla hasta que termine de sonar
            while (target != null && target.isPlaying && target.clip == streamClip)
                yield return null;

            done(StreamResult.Played);
        }
    }

    // ── R: nueva familia ───────────────────────────────────────────────────────

    IEnumerator ResetConversation()
    {
        using (var www = UnityWebRequest.Post($"{serverUrl}/reset", new WWWForm()))
        {
            yield return www.SendWebRequest();
            if (www.result == UnityWebRequest.Result.Success)
                Debug.Log("🧹 Conversación reiniciada: el servidor olvidó lo anterior");
            else
                Debug.LogError($"❌ No se pudo reiniciar la conversación: {www.error}");
        }
    }

    // ── Flujo 0-9: pregunta pregrabada del tab activo ─────────────────────────

    IEnumerator PlayPreguntaPregrabada(int questionNumber, string speaker)
    {
        string label = speaker == speakerRectora ? "RECTORA" : "OSWALDO";
        Debug.Log($"💬 [{label}] Pregunta {questionNumber}");

        string json = $"{{\"question\":{questionNumber},\"speaker\":\"{speaker}\"}}";
        byte[] body = System.Text.Encoding.UTF8.GetBytes(json);

        using (var www = new UnityWebRequest($"{serverUrl}/presentation", "POST"))
        {
            www.uploadHandler   = new UploadHandlerRaw(body);
            www.downloadHandler = new DownloadHandlerBuffer();
            www.SetRequestHeader("Content-Type", "application/json");
            yield return www.SendWebRequest();

            if (www.result == UnityWebRequest.Result.Success)
            {
                ServerResponse resp = JsonUtility.FromJson<ServerResponse>(www.downloadHandler.text);
                AudioSource   targetAudio   = rectoraResponde ? audioRectora       : audioECI;
                MonoBehaviour targetHandler = rectoraResponde ? voiceHandlerRectora : voiceHandlerECI;
                Debug.Log($"▶️  Reproduciendo pregunta {resp.question} en avatar {label}");
                yield return DownloadAndPlay($"{serverUrl}/static/{resp.file}", targetAudio, targetHandler);
            }
            else
            {
                Debug.LogError($"❌ Error solicitando pregunta: {www.error}");
            }
        }
    }

    // ── Descarga y reproduce audio en el avatar correcto ──────────────────────

    IEnumerator DownloadAndPlay(string url, AudioSource target, MonoBehaviour handler)
    {
        if (target == null)
        {
            Debug.LogWarning("⚠️  AudioSource no asignado, no se puede reproducir.");
            yield break;
        }

        // Cache-bust
        url += $"?t={System.DateTime.Now.Ticks}";

        using (var www = UnityWebRequestMultimedia.GetAudioClip(url, AudioType.MPEG))
        {
            yield return www.SendWebRequest();

            if (www.result == UnityWebRequest.Result.Success)
            {
                AudioClip clip = DownloadHandlerAudioClip.GetContent(www);
                if (clip != null && clip.length > 0)
                {
                    target.clip = clip;
                    target.Play();

                    // Activar animación de boca en el VoiceHandler del avatar
                    if (handler != null)
                        handler.SendMessage("PlayAudioClip", clip, SendMessageOptions.DontRequireReceiver);

                    Debug.Log($"🔊 Reproduciendo {clip.length:F1}s en {target.gameObject.name}");
                }
            }
            else
            {
                Debug.LogError($"❌ Error descargando audio: {www.error}");
            }
        }
    }
}
