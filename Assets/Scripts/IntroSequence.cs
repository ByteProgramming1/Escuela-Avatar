using System.Collections;
using UnityEngine;
using UnityEngine.Networking;

/// <summary>
/// Secuencia de introducción entre Oswaldo y la Rectora.
/// Tecla P  → reproduce la intro (usa audios cacheados si existen).
/// Inspector → activa "Regenerate Audio" para forzar nueva generación TTS.
/// </summary>
public class IntroSequence : MonoBehaviour
{
    [Header("Servidor")]
    public string serverUrl = "http://localhost:5000";

    [Header("Avatar Oswaldo")]
    public Transform oswaldoRoot;
    public AudioSource audioOswaldo;
    public MonoBehaviour voiceHandlerOswaldo;

    [Header("Avatar Rectora")]
    public Transform rectoraRoot;
    public AudioSource audioRectora;
    public MonoBehaviour voiceHandlerRectora;

    [Header("Sistema")]
    public MonoBehaviour voiceAssistant;

    [Header("Caminata de entrada")]
    [Tooltip("WalkToPoint de Oswaldo")]
    public WalkToPoint oswaldoWalk;
    [Tooltip("WalkToPoint de la Rectora (añadir el componente al avatar de la Rectora)")]
    public WalkToPoint rectoraWalk;
    [Tooltip("Cámara que sigue a los avatares durante la caminata")]
    public Camera walkingCamera;
    [Tooltip("Duración máxima de la fase de caminata en segundos")]
    public float walkingPhaseDuration = 30f;

    [Header("Audio")]
    [Tooltip("Fuerza regenerar todos los audios desde ElevenLabs aunque ya existan en disco.")]
    public bool regenerateAudio = false;

    [Header("Tiempos")]
    public float rotationDuration = 1.2f;
    public float pauseBetweenLines = 0.6f;
    public float pauseBeforeCameraFace = 0.8f;

    private bool _started;

    // Líneas 0-3: avatares mirándose entre sí
    // Líneas 4-7: ambos mirando a la cámara
    private const int CameraPivot = 4;

    private static readonly string[] Lines =
    {
        // --- Fase 1: se miran entre sí ---
        "¡¡Rectora! Qué gusto tan grande verla aquí hoy en este encuentro de padres pues es un momento que todos esperábamos con mucha ilusión y alegría .",
        "¡Oswaldo! que gusto de verlo aquí Igualmente. Yo también estoy muy emocionada. Estos momentos con las familias de nuestros estudiantes son los que le dan sentido a todo lo que hacemos dentro de nuestra Universidad.",
        "Y este año tenemos tanto que compartirles. ¡Nuestros estudiantes han conseguido logros verdaderamente increíbles en toda nuestra comunidad educativa!",
        "¡Así es! Pero mejor se los contamos a todos juntos. ",

        // --- Fase 2: mirando a la cámara ---
        "¡Buenos días a todos! y Bienvenidos a este encuentro tan especial en la Escuela Colombiana de Ingeniería Julio Garavito .",
        "Es un honor recibirlos. Y con mucha alegría les comparto que en las pruebas Saber Pro dos mil veinticinco, nuestra Escuela ocupó el puesto doce a nivel nacional entre doscientas setenta y cinco instituciones de educación superior, y el puesto cinco en Bogotá entre noventa y una instituciones. ¡Un logro del que todos podemos sentirnos muy orgullosos!",
        "¡Con resultados como estos y muchos más ... los padres tienen muchísimas razones para estar emocionados con que sus hijos e hijas estén aquí con nosotros.",
        "Absolutamente. y Para mí es un verdadero honor estar aquí hoy con ustedes. Estoy lista para escucharlos y responder cada una de sus inquietudes y preguntas ."
    };

    private static readonly string[] Speakers =
    {
        "oswaldo", "rectora", "oswaldo", "rectora",
        "oswaldo", "rectora", "oswaldo", "rectora"
    };

    void Start()
    {
        if (voiceAssistant != null)
            voiceAssistant.enabled = false;

        // Auto-buscar SimpleLipSync si los campos handler no están asignados en el Inspector
        if (voiceHandlerOswaldo == null && audioOswaldo != null)
            voiceHandlerOswaldo = FindLipSync(audioOswaldo.transform);

        if (voiceHandlerRectora == null && audioRectora != null)
            voiceHandlerRectora = FindLipSync(audioRectora.transform);
    }

    static SimpleLipSync FindLipSync(Transform t)
    {
        if (t == null) return null;
        return t.GetComponentInChildren<SimpleLipSync>(true)
            ?? t.GetComponentInParent<SimpleLipSync>();
    }

    void Update()
    {
        if (!_started && Input.GetKeyDown(KeyCode.P))
        {
            _started = true;
            StartCoroutine(RunIntro());
        }
    }

    IEnumerator RunIntro()
    {
        bool hasWalk = oswaldoWalk != null || rectoraWalk != null;
        Camera mainCam = Camera.main;

        // ── Fase 0: Arrancar caminata y activar cámara de seguimiento ─────────
        if (hasWalk)
        {
            if (walkingCamera != null)
            {
                if (mainCam != null) mainCam.enabled = false;
                walkingCamera.enabled = true;
            }
            if (rectoraWalk != null) rectoraWalk.StartWalk();
            yield return new WaitForSeconds(1.5f);
            if (oswaldoWalk != null) oswaldoWalk.StartWalk();
        }

        // ── Fase 1: Diálogo mientras caminan ─────────────────────────────────
        for (int i = 0; i < CameraPivot; i++)
        {
            AudioSource   audio   = Speakers[i] == "oswaldo" ? audioOswaldo        : audioRectora;
            MonoBehaviour handler = Speakers[i] == "oswaldo" ? voiceHandlerOswaldo : voiceHandlerRectora;
            yield return PlayLine(i, audio, handler);
            yield return new WaitForSeconds(pauseBetweenLines);
        }

        // ── Esperar a que ambos lleguen (si aún están caminando) ──────────────
        if (hasWalk)
        {
            float elapsed = 0f;
            while (elapsed < walkingPhaseDuration)
            {
                elapsed += Time.deltaTime;
                bool oswaldoDone = oswaldoWalk == null || !oswaldoWalk.IsWalking;
                bool rectoraDone = rectoraWalk == null || !rectoraWalk.IsWalking;
                if (oswaldoDone && rectoraDone) break;
                yield return null;
            }

            if (oswaldoWalk != null) oswaldoWalk.enabled = false;
            if (rectoraWalk != null) rectoraWalk.enabled = false;

            if (walkingCamera != null) walkingCamera.enabled = false;
            if (mainCam != null)       mainCam.enabled       = true;

            yield return new WaitForSeconds(0.5f);
        }

        // ── Pausa y giro hacia la cámara ──────────────────────────────────────
        yield return new WaitForSeconds(pauseBeforeCameraFace);

        Transform cam = Camera.main != null ? Camera.main.transform : null;
        if (cam != null)
            yield return RotateBoth(GetFacing(oswaldoRoot, cam),
                                    GetFacing(rectoraRoot, cam));

        yield return new WaitForSeconds(1.0f);

        // ── Fase 2: Hablan al público ─────────────────────────────────────────
        for (int i = CameraPivot; i < Lines.Length; i++)
        {
            AudioSource   audio   = Speakers[i] == "oswaldo" ? audioOswaldo        : audioRectora;
            MonoBehaviour handler = Speakers[i] == "oswaldo" ? voiceHandlerOswaldo : voiceHandlerRectora;
            yield return PlayLine(i, audio, handler);
            yield return new WaitForSeconds(pauseBetweenLines);
        }

        if (voiceAssistant != null)
            voiceAssistant.enabled = true;

        Debug.Log("✅ Intro terminada — VoiceAssistant activo");
    }

    IEnumerator PlayLine(int index, AudioSource targetAudio, MonoBehaviour handler)
    {
        string filename = $"intro_{index}.mp3";
        string fileUrl  = $"{serverUrl}/static/{filename}";

        // Si no se pide regenerar, comprobar si el archivo ya existe en el servidor
        bool needsTts = regenerateAudio;
        if (!needsTts)
        {
            using (var head = UnityWebRequest.Head(fileUrl))
            {
                yield return head.SendWebRequest();
                needsTts = head.result != UnityWebRequest.Result.Success;
            }
        }

        if (needsTts)
        {
            string text    = Lines[index];
            string speaker = Speakers[index];
            string json    = "{\"text\":\"" + EscapeJson(text) + "\",\"speaker\":\"" + speaker + "\",\"filename\":\"" + filename + "\"}";
            byte[] body    = System.Text.Encoding.UTF8.GetBytes(json);

            using (var www = new UnityWebRequest($"{serverUrl}/tts", "POST"))
            {
                www.uploadHandler   = new UploadHandlerRaw(body);
                www.downloadHandler = new DownloadHandlerBuffer();
                www.SetRequestHeader("Content-Type", "application/json");
                yield return www.SendWebRequest();

                if (www.result != UnityWebRequest.Result.Success)
                {
                    Debug.LogError($"❌ TTS línea {index}: {www.error}");
                    yield break;
                }
            }
        }

        // Descargar y reproducir (cache-bust solo al regenerar para no romper el caché normal)
        string playUrl = regenerateAudio
            ? $"{fileUrl}?t={System.DateTime.Now.Ticks}"
            : fileUrl;

        using (var www = UnityWebRequestMultimedia.GetAudioClip(playUrl, AudioType.MPEG))
        {
            yield return www.SendWebRequest();

            if (www.result != UnityWebRequest.Result.Success)
            {
                Debug.LogError($"❌ Descarga audio {filename}: {www.error}");
                yield break;
            }

            AudioClip clip = DownloadHandlerAudioClip.GetContent(www);
            if (clip == null || clip.length <= 0)
                yield break;

            // Reproducir audio (siempre)
            if (targetAudio != null)
            {
                targetAudio.clip = clip;
                targetAudio.Play();
            }

            // Activar lip sync en el handler (SimpleLipSync o VoiceHandler)
            if (handler != null)
                handler.SendMessage("PlayAudioClip", clip, SendMessageOptions.DontRequireReceiver);

            // Un frame para que isPlaying sea true
            yield return null;
            yield return new WaitWhile(() => targetAudio != null && targetAudio.isPlaying);
        }
    }

    IEnumerator RotateBoth(Quaternion oswaldoTarget, Quaternion rectoraTarget)
    {
        if (oswaldoRoot == null || rectoraRoot == null)
            yield break;

        Quaternion oswaldoStart = oswaldoRoot.rotation;
        Quaternion rectoraStart = rectoraRoot.rotation;
        float elapsed = 0f;

        while (elapsed < rotationDuration)
        {
            elapsed += Time.deltaTime;
            float t = Mathf.SmoothStep(0f, 1f, Mathf.Clamp01(elapsed / rotationDuration));
            oswaldoRoot.rotation = Quaternion.Slerp(oswaldoStart, oswaldoTarget, t);
            rectoraRoot.rotation = Quaternion.Slerp(rectoraStart, rectoraTarget, t);
            yield return null;
        }

        oswaldoRoot.rotation = oswaldoTarget;
        rectoraRoot.rotation = rectoraTarget;
    }

    static Quaternion GetFacing(Transform from, Transform to)
    {
        if (from == null || to == null)
            return Quaternion.identity;
        Vector3 dir = to.position - from.position;
        dir.y = 0f;
        return dir.sqrMagnitude > 0.0001f
            ? Quaternion.LookRotation(dir.normalized)
            : from.rotation;
    }

    static string EscapeJson(string s) =>
        s.Replace("\\", "\\\\").Replace("\"", "\\\"");
}
