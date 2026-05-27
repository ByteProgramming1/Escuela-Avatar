using System.Collections;
using UnityEngine;
using UnityEngine.Networking;

/// <summary>
/// Sistema de conversación dual entre dos avatares.
///
/// Teclas:
///   W / Espacio → Graba audio del usuario → el avatar activo responde con IA
///   Tab         → Alterna tab activo: Rectora ↔ Oswaldo
///   1-9         → Reproduce pregunta pregrabada del tab activo (pregunta 1-9)
///   0           → Reproduce pregunta 10 del tab activo
/// </summary>
public class VoiceAssistant : MonoBehaviour
{
    [Header("Servidor")]
    public string serverUrl = "http://localhost:5000";

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

        Debug.Log("Tab=Cambiar tab (Rectora/Oswaldo) | 0-9=Pregunta pregrabada | W/Espacio=Hablar");
    }

    void Update()
    {
        // Tab: alterna el tab activo (Rectora ↔ Oswaldo)
        if (Input.GetKeyDown(KeyCode.Tab))
        {
            rectoraResponde = !rectoraResponde;
            Debug.Log(rectoraResponde ? "📋 Tab: RECTORA" : "📋 Tab: OSWALDO");
        }

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
