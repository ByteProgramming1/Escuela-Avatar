using System.Collections;
using System.Collections.Generic;
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

    [Tooltip("Usa POST /audio/stream: las muletillas suenan en cuanto llegan y la respuesta después. " +
             "Desactívalo para volver a la descarga completa (POST /audio).")]
    public bool useStreaming = true;

    [Header("Pausa para \"pensar\" tras las muletillas")]
    [Tooltip("Tras la última muletilla («un momento, por favor…») y con la respuesta ya lista, el avatar se queda " +
             "en silencio un instante antes de responder, en vez de empalmarla al instante. Solo pasa si sonó alguna muletilla.")]
    public bool thinkingPause = true;
    [Tooltip("Duración de la pausa en segundos: se elige al azar entre x (mínimo) e y (máximo)")]
    public Vector2 thinkingPauseSeconds = new Vector2(1.2f, 2.0f);

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
    // El servidor pasa todo a 16 kHz para Whisper: grabar ya a 16 kHz evita ese remuestreo
    // y sube ~2,7 veces menos datos que a 44,1 kHz
    private const int MIC_FREQUENCY = 16000;
    private int micFrequency = MIC_FREQUENCY;
    private AudioClip recordedClip;
    // Instante en que se soltó la tecla: base de los cronómetros "⏱️" del log (cuánto tarda en sonar la respuesta)
    private float releasedAt;

    // ── Estado para la barra superior (BarraSuperior) ──────────────────────────

    public enum Phase
    {
        Listo,          // esperando a que alguien pregunte
        Grabando,       // W/Espacio pulsado: el personaje activo escucha
        Procesando,     // pregunta enviada, aún no suena nada
        Muletilla,      // suena una muletilla ("un momento, por favor...")
        Pensando,       // pausa en silencio antes de la respuesta
        Respondiendo,   // suena la respuesta
        Pregrabada      // suena una pregunta pregrabada (teclas 0-9)
    }

    public Phase CurrentPhase { get; private set; } = Phase.Listo;
    public bool RectoraActiva => rectoraResponde;
    /// <summary>Speaker que está respondiendo ahora (null si nadie).</summary>
    public string RespondingSpeaker { get; private set; }
    public int PregrabadaActual { get; private set; }
    public string LastError { get; private set; }
    public float LastErrorAt { get; private set; } = -100f;

    // Respuesta en curso: lo que hay que cortar al saltar la pregunta
    private Coroutine activeRoutine;
    private UnityWebRequest activeRequest;
    private readonly List<Coroutine> activeHelpers = new List<Coroutine>();

    void SetPhase(Phase phase, string speaker = null)
    {
        CurrentPhase = phase;
        RespondingSpeaker = phase == Phase.Listo || phase == Phase.Grabando ? null : speaker ?? RespondingSpeaker;
    }

    void ReportError(string message)
    {
        LastError = message;
        LastErrorAt = Time.realtimeSinceStartup;
    }

    public void SetActiveCharacter(bool rectora)
    {
        if (CurrentPhase != Phase.Listo) return;  // no cambiar de personaje a mitad de una respuesta
        rectoraResponde = rectora;
        Debug.Log(rectoraResponde ? "📋 Tab: RECTORA" : "📋 Tab: OSWALDO");
    }

    /// <summary>Corta la pregunta en curso (grabación, espera o respuesta) y vuelve a "Listo".</summary>
    public void SkipCurrent()
    {
        if (CurrentPhase == Phase.Grabando)
        {
            Microphone.End(micDevice);
            recordedClip = null;
        }
        if (activeRoutine != null) StopCoroutine(activeRoutine);
        foreach (var helper in activeHelpers)
            if (helper != null) StopCoroutine(helper);
        activeHelpers.Clear();
        activeRoutine = null;
        if (activeRequest != null)
        {
            activeRequest.Abort();
            activeRequest.Dispose();
            activeRequest = null;
        }
        if (audioRectora != null) audioRectora.Stop();
        if (audioECI != null) audioECI.Stop();
        if (CurrentPhase != Phase.Listo)
            Debug.Log("⏭️ Pregunta saltada");
        SetPhase(Phase.Listo);
    }

    /// <summary>Nueva familia: corta lo que suene y el servidor olvida la conversación.</summary>
    public void ResetAll()
    {
        SkipCurrent();
        StartCoroutine(ResetConversation());
    }

    bool Busy => CurrentPhase != Phase.Listo && CurrentPhase != Phase.Grabando;

    void Run(IEnumerator routine)
    {
        activeRoutine = StartCoroutine(Tracked(routine));
    }

    IEnumerator Tracked(IEnumerator routine)
    {
        yield return routine;
        activeRoutine = null;
        activeRequest = null;
        activeHelpers.Clear();
        SetPhase(Phase.Listo);
    }

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
        {
            micDevice = Microphone.devices[0];
            // minFreq = maxFreq = 0 → el micrófono acepta cualquier frecuencia
            Microphone.GetDeviceCaps(micDevice, out int minFreq, out int maxFreq);
            if (maxFreq > 0)
                micFrequency = Mathf.Clamp(MIC_FREQUENCY, minFreq, maxFreq);
        }
        else
            Debug.LogError("❌ No hay micrófono disponible");

        StartCoroutine(LoadFillers(speakerRectora));
        StartCoroutine(LoadFillers(speakerOswaldo));

        Debug.Log("Tab=Cambiar tab (Rectora/Oswaldo) | R=Nueva familia | 0-9=Pregunta pregrabada | W/Espacio=Hablar");
    }

    void Update()
    {
        // Tab: alterna el tab activo (Rectora ↔ Oswaldo)
        if (Input.GetKeyDown(KeyCode.Tab))
            SetActiveCharacter(!rectoraResponde);

        // R: nueva familia → el servidor olvida lo conversado (si no, la siguiente pregunta hereda el contexto)
        if (Input.GetKeyDown(KeyCode.R))
            ResetAll();

        // W o Espacio: grabar audio del usuario → el avatar del tab activo responde
        bool startRec = Input.GetKeyDown(KeyCode.W) || Input.GetKeyDown(KeyCode.Space);
        bool stopRec  = Input.GetKeyUp(KeyCode.W)   || Input.GetKeyUp(KeyCode.Space);

        if (startRec)
        {
            if (Busy) SkipCurrent();  // una pregunta nueva interrumpe la respuesta que esté sonando
            recordedClip = Microphone.Start(micDevice, false, 300, micFrequency);
            SetPhase(Phase.Grabando);
            Debug.Log("🎤 Grabando...");
        }

        if (stopRec && recordedClip != null)
        {
            releasedAt = Time.realtimeSinceStartup;
            int len = Microphone.GetPosition(micDevice);
            Microphone.End(micDevice);
            SetPhase(Phase.Listo);
            if (len > 0)
            {
                AudioSource   targetAudio   = rectoraResponde ? audioRectora       : audioECI;
                MonoBehaviour targetHandler = rectoraResponde ? voiceHandlerRectora : voiceHandlerECI;
                string        speaker       = rectoraResponde ? speakerRectora      : speakerOswaldo;
                string        respFile      = rectoraResponde ? "response_rectora.mp3" : "response_oswaldo.mp3";

                SetPhase(Phase.Procesando, speaker);
                Run(SendRecordedAudio(recordedClip, len, speaker, respFile, targetAudio, targetHandler));
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
                if (Busy) SkipCurrent();
                PregrabadaActual = questionNumber;
                SetPhase(Phase.Pregrabada, speaker);
                Run(PlayPreguntaPregrabada(questionNumber, speaker));
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
            yield return StreamAndPlay(form, speaker, targetAudio, targetHandler, r => result = r);
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
            activeRequest = www;
            yield return www.SendWebRequest();
            activeRequest = null;
            if (www.result == UnityWebRequest.Result.Success)
            {
                Debug.Log("✅ Respuesta AI recibida");
                yield return DownloadAndPlay($"{serverUrl}/static/{respFile}", targetAudio, targetHandler);
            }
            else
            {
                Debug.LogError($"❌ Error enviando audio: {www.error}");
                ReportError("No se pudo conectar con el servidor");
            }
        }
    }

    // ── Streaming: muletillas al instante, silencio para "pensar" y luego la respuesta ──
    //
    // El servidor manda en un solo MP3, uno detrás de otro: 0-3 muletillas y la respuesta. Las muletillas son clips
    // ya hechos que también sirve en /static/filler_<speaker>_<etapa>NN.mp3 y van en el stream byte a byte, así que
    // Unity los descarga al arrancar y reconoce cada una por su contenido:
    //   - cada muletilla suena en cuanto termina de llegar (ya decodificada; el clip en streaming de Unity no empezaba
    //     a sonar hasta tener casi toda la descarga, ~3-4 s tarde);
    //   - lo primero que no es una muletilla es la respuesta: se guarda hasta que llega completa y suena después de
    //     las muletillas y de una pausa en silencio, como si el personaje pensara.
    // No se puede distinguir por cómo llegan los bytes: si la respuesta ya estaba lista, llega de golpe igual que una muletilla.

    enum StreamResult { Played, ServerError, NotPlayable }

    static readonly string[] FILLER_STAGES = { "opening", "continue" };
    const int MAX_FILLERS_PER_STAGE = 100;

    class Filler
    {
        public byte[] bytes;
        public AudioClip clip;
    }

    readonly Dictionary<string, List<Filler>> fillerLibrary = new Dictionary<string, List<Filler>>();
    readonly HashSet<string> fillersLoading = new HashSet<string>();

    /// <summary>Descarga y decodifica las muletillas de un personaje (se repite tras cada respuesta por si el
    /// servidor las regeneró con otra voz).</summary>
    IEnumerator LoadFillers(string speaker)
    {
        if (!fillersLoading.Add(speaker)) yield break;
        var loaded = new List<Filler>();
        foreach (string stage in FILLER_STAGES)
        {
            for (int i = 0; i < MAX_FILLERS_PER_STAGE; i++)
            {
                byte[] bytes;
                using (var www = UnityWebRequest.Get($"{serverUrl}/static/filler_{speaker}_{stage}{i:D2}.mp3"))
                {
                    yield return www.SendWebRequest();
                    if (www.result != UnityWebRequest.Result.Success) break;  // 404 = no hay más de esta etapa
                    bytes = www.downloadHandler.data;
                }
                AudioClip clip = null;
                yield return DecodeMp3(bytes, c => clip = c);
                if (clip != null)
                    loaded.Add(new Filler { bytes = bytes, clip = clip });
            }
        }
        if (loaded.Count > 0 || !fillerLibrary.ContainsKey(speaker))
            fillerLibrary[speaker] = loaded;
        fillersLoading.Remove(speaker);
        if (loaded.Count == 0)
            Debug.LogWarning($"⚠️ No se pudieron cargar las muletillas de {speaker} (¿servidor apagado?): la respuesta sonará sin pausa previa");
    }

    /// <summary>Recoge los bytes de la respuesta según llegan (ReceiveData corre en el hilo principal).</summary>
    class Mp3Collector : DownloadHandlerScript
    {
        readonly System.IO.MemoryStream received = new System.IO.MemoryStream();
        public long Length => received.Length;

        public Mp3Collector() : base(new byte[16 * 1024]) { }

        protected override bool ReceiveData(byte[] chunk, int dataLength)
        {
            if (chunk == null || dataLength <= 0) return true;
            received.Write(chunk, 0, dataLength);
            return true;
        }

        /// <summary>¿Los `count` bytes desde `start` son iguales al principio de `expected`?</summary>
        public bool Matches(long start, byte[] expected, int count)
        {
            byte[] buf = received.GetBuffer();
            for (int i = 0; i < count; i++)
                if (buf[start + i] != expected[i]) return false;
            return true;
        }

        public byte[] Slice(long start, long end)
        {
            var slice = new byte[end - start];
            System.Array.Copy(received.GetBuffer(), start, slice, 0, slice.Length);
            return slice;
        }
    }

    class StreamState
    {
        public readonly Queue<AudioClip> fillers = new Queue<AudioClip>();
        public int fillersPlayed;
        public long answerStart = -1;    // byte donde empieza la respuesta (-1 = aún no llega)
        public bool finished;            // la petición terminó (bien o mal)
    }

    int decodeCounter;

    IEnumerator StreamAndPlay(WWWForm form, string speaker, AudioSource target, MonoBehaviour handler,
        System.Action<StreamResult> done)
    {
        if (target == null)
        {
            Debug.LogWarning("⚠️  AudioSource no asignado, no se puede reproducir.");
            done(StreamResult.ServerError);
            yield break;
        }

        string url = $"{serverUrl}/audio/stream";
        var collector = new Mp3Collector();
        var state = new StreamState();
        fillerLibrary.TryGetValue(speaker, out List<Filler> known);

        using (var www = UnityWebRequest.Post(url, form))
        {
            www.downloadHandler = collector;
            activeRequest = www;
            var op = www.SendWebRequest();
            activeHelpers.Add(StartCoroutine(SplitStream(op, collector, known ?? new List<Filler>(), state)));

            // 1) Muletillas: cada una suena en cuanto llega entera
            while (true)
            {
                if (state.fillers.Count > 0)
                {
                    AudioClip filler = state.fillers.Dequeue();
                    if (state.fillersPlayed == 0)
                        Debug.Log($"⏱️ Primera muletilla suena a {Time.realtimeSinceStartup - releasedAt:F1}s de soltar la tecla");
                    state.fillersPlayed++;
                    SetPhase(Phase.Muletilla, speaker);
                    yield return PlayToEnd(target, handler, filler);
                    SetPhase(Phase.Procesando, speaker);
                    continue;
                }
                // Ya no puede llegar otra muletilla: empezó la respuesta o terminó la petición
                if (state.answerStart >= 0 || state.finished)
                    break;
                yield return null;
            }

            // 2) La respuesta, completa
            while (!state.finished) yield return null;
            StartCoroutine(LoadFillers(speaker));  // al terminar, por si el servidor regeneró sus muletillas
            activeRequest = null;
            if (www.result != UnityWebRequest.Result.Success)
            {
                Debug.LogError($"❌ Error en streaming de audio: {www.error}");
                ReportError("No se pudo conectar con el servidor");
                done(state.fillersPlayed > 0 ? StreamResult.Played : StreamResult.ServerError);
                yield break;
            }
            if (state.answerStart < 0)
            {
                done(StreamResult.Played);  // solo hubo muletillas: ya sonó todo
                yield break;
            }
            Debug.Log($"⏱️ Respuesta completa a {Time.realtimeSinceStartup - releasedAt:F1}s de soltar la tecla");

            float pauseEndsAt = Time.realtimeSinceStartup;
            if (thinkingPause && state.fillersPlayed > 0)
            {
                // 3) Silencio total: nadie habla mientras el personaje "piensa" (la boca queda cerrada)
                float seconds = Random.Range(thinkingPauseSeconds.x, thinkingPauseSeconds.y);
                pauseEndsAt += seconds;
                SetPhase(Phase.Pensando, speaker);
                Debug.Log($"🤔 Pausa de {seconds:F1}s en silencio tras {state.fillersPlayed} muletilla(s), antes de la respuesta");
            }

            AudioClip answer = null;
            yield return DecodeMp3(collector.Slice(state.answerStart, collector.Length), c => answer = c);  // durante la pausa
            while (Time.realtimeSinceStartup < pauseEndsAt) yield return null;

            if (answer == null)
            {
                Debug.LogError("❌ No se pudo decodificar la respuesta");
                if (state.fillersPlayed > 0) ReportError("No se pudo reproducir la respuesta");
                done(state.fillersPlayed > 0 ? StreamResult.Played : StreamResult.NotPlayable);
                yield break;
            }

            SetPhase(Phase.Respondiendo, speaker);
            Debug.Log($"🔊 Respuesta ({answer.length:F1}s) en {target.gameObject.name} — suena a {Time.realtimeSinceStartup - releasedAt:F1}s de soltar la tecla");
            yield return PlayToEnd(target, handler, answer);
            done(StreamResult.Played);
        }
    }

    /// <summary>Recorre el stream según llega: reconoce las muletillas por sus bytes y marca dónde empieza la respuesta.</summary>
    IEnumerator SplitStream(UnityWebRequestAsyncOperation op, Mp3Collector collector, List<Filler> known, StreamState state)
    {
        long pos = 0;
        while (state.answerStart < 0)
        {
            bool finished = op.isDone;
            long available = collector.Length - pos;

            if (available > 0)
            {
                Filler complete = null;
                bool stillPossible = false;
                foreach (Filler f in known)
                {
                    int n = (int)System.Math.Min(available, f.bytes.Length);
                    if (!collector.Matches(pos, f.bytes, n)) continue;
                    if (n == f.bytes.Length) { complete = f; break; }
                    stillPossible = true;
                }

                if (complete != null)
                {
                    state.fillers.Enqueue(complete.clip);
                    pos += complete.bytes.Length;
                    continue;  // puede venir otra muletilla justo detrás
                }
                if (!stillPossible || finished)
                {
                    state.answerStart = pos;  // lo primero que no es una muletilla: aquí empieza la respuesta
                    break;
                }
            }

            if (finished) break;
            yield return null;
        }

        while (!op.isDone) yield return null;
        state.finished = true;
    }

    /// <summary>MP3 en memoria → AudioClip: se escribe a un archivo temporal y lo decodifica Unity.</summary>
    IEnumerator DecodeMp3(byte[] mp3, System.Action<AudioClip> done)
    {
        string path = System.IO.Path.Combine(Application.temporaryCachePath, $"decode_{decodeCounter++}.mp3");
        System.IO.File.WriteAllBytes(path, mp3);

        using (var www = UnityWebRequestMultimedia.GetAudioClip(new System.Uri(path).AbsoluteUri, AudioType.MPEG))
        {
            yield return www.SendWebRequest();
            AudioClip clip = www.result == UnityWebRequest.Result.Success ? DownloadHandlerAudioClip.GetContent(www) : null;
            done(clip != null && clip.length > 0 ? clip : null);
        }
        try { System.IO.File.Delete(path); } catch (System.IO.IOException) { }
    }

    IEnumerator PlayToEnd(AudioSource target, MonoBehaviour handler, AudioClip clip)
    {
        target.clip = clip;
        target.Play();
        if (handler != null)
            handler.SendMessage("PlayAudioClip", clip, SendMessageOptions.DontRequireReceiver);
        while (target != null && target.isPlaying && target.clip == clip)
            yield return null;
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
            activeRequest = www;
            yield return www.SendWebRequest();
            activeRequest = null;

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
                ReportError("No se pudo conectar con el servidor");
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
            activeRequest = www;
            yield return www.SendWebRequest();
            activeRequest = null;

            if (www.result == UnityWebRequest.Result.Success)
            {
                AudioClip clip = DownloadHandlerAudioClip.GetContent(www);
                if (clip != null && clip.length > 0)
                {
                    if (CurrentPhase != Phase.Pregrabada)
                        SetPhase(Phase.Respondiendo);
                    target.clip = clip;
                    target.Play();

                    // Activar animación de boca en el VoiceHandler del avatar
                    if (handler != null)
                        handler.SendMessage("PlayAudioClip", clip, SendMessageOptions.DontRequireReceiver);

                    Debug.Log($"🔊 Reproduciendo {clip.length:F1}s en {target.gameObject.name}");
                    // Hasta que acabe: la barra superior muestra quién habla mientras suena
                    while (target != null && target.isPlaying && target.clip == clip)
                        yield return null;
                }
            }
            else
            {
                Debug.LogError($"❌ Error descargando audio: {www.error}");
                ReportError("No se pudo descargar el audio");
            }
        }
    }
}
