using TMPro;
using UnityEngine;
using UnityEngine.EventSystems;
using UnityEngine.UI;

/// <summary>
/// Barra superior en español que indica en qué momento está la experiencia y quién escucha / quién habla:
///   presentación → listo (mantén W o Espacio) → escuchando → pensando → muletilla → respuesta.
/// Botones: iniciar / saltar la presentación, saltar la pregunta en curso, reiniciar (nueva familia),
/// y cambiar de personaje pulsando su tarjeta.
/// Se crea sola al cargar cualquier escena que tenga un VoiceAssistant: no hay que añadirla a mano.
/// </summary>
public class BarraSuperior : MonoBehaviour
{
    const float BAR_HEIGHT = 104f;
    const float ERROR_SECONDS = 4f;

    static readonly Color BarColor      = new Color(0.06f, 0.08f, 0.13f, 0.90f);
    static readonly Color TextColor     = new Color(0.97f, 0.98f, 1f);
    static readonly Color MutedText     = new Color(0.68f, 0.73f, 0.82f);
    static readonly Color IdleChip      = new Color(0.16f, 0.19f, 0.26f, 1f);
    static readonly Color ListeningChip = new Color(0.13f, 0.40f, 0.85f, 1f);
    static readonly Color SpeakingChip  = new Color(0.09f, 0.56f, 0.38f, 1f);
    static readonly Color ButtonColor   = new Color(0.22f, 0.26f, 0.35f, 1f);
    static readonly Color DangerButton  = new Color(0.70f, 0.24f, 0.24f, 1f);
    static readonly Color PrimaryButton = new Color(0.13f, 0.40f, 0.85f, 1f);

    static readonly Color DotReady    = new Color(0.30f, 0.80f, 0.50f);
    static readonly Color DotRecord   = new Color(0.95f, 0.30f, 0.30f);
    static readonly Color DotThinking = new Color(0.98f, 0.75f, 0.25f);
    static readonly Color DotSpeaking = new Color(0.35f, 0.65f, 1f);
    static readonly Color DotIntro    = new Color(0.75f, 0.55f, 1f);
    static readonly Color DotError    = new Color(0.95f, 0.30f, 0.30f);

    VoiceAssistant assistant;
    IntroSequence intro;

    Image dot;
    TMP_Text title, subtitle;
    Chip rectoraChip, oswaldoChip;
    GameObject startIntroButton, skipIntroButton, skipQuestionButton, resetButton;
    bool pulseDot;

    class Chip
    {
        public Image background;
        public TMP_Text name, role;
    }

    [RuntimeInitializeOnLoadMethod(RuntimeInitializeLoadType.AfterSceneLoad)]
    static void CreateForScene()
    {
        if (FindObjectOfType<BarraSuperior>() != null) return;
        if (FindObjectOfType<VoiceAssistant>(true) == null) return;
        new GameObject("BarraSuperior").AddComponent<BarraSuperior>();
    }

    void Awake()
    {
        assistant = FindObjectOfType<VoiceAssistant>(true);
        intro = FindObjectOfType<IntroSequence>(true);
        EnsureEventSystem();
        BuildUI();
    }

    // ── Estado → textos ────────────────────────────────────────────────────────

    void Update()
    {
        if (assistant == null) return;

        bool introPending = intro != null && intro.isActiveAndEnabled && !intro.Finished;
        bool introRunning = introPending && intro.Running;
        VoiceAssistant.Phase phase = assistant.CurrentPhase;
        bool rectoraActiva = assistant.RectoraActiva;
        string speaking = introRunning ? intro.CurrentSpeaker : assistant.RespondingSpeaker;
        bool hasError = !introPending && Time.realtimeSinceStartup - assistant.LastErrorAt < ERROR_SECONDS
                        && phase == VoiceAssistant.Phase.Listo;

        string activeName = rectoraActiva ? "la Rectora" : "Oswaldo";
        string speakingName = NameOf(speaking) ?? activeName;
        pulseDot = false;

        if (introRunning)
        {
            SetStatus(DotIntro, "Presentación en curso",
                      speaking != null ? $"Habla {NameOf(speaking)}" : "Oswaldo y la Rectora se presentan");
        }
        else if (introPending)
        {
            SetStatus(DotIntro, "Bienvenidos",
                      "Pulsa P o «Iniciar presentación» para comenzar");
        }
        else if (hasError)
        {
            SetStatus(DotError, assistant.LastError, "Inténtalo de nuevo: mantén pulsada W o Espacio para hablar");
        }
        else
        {
            switch (phase)
            {
                case VoiceAssistant.Phase.Grabando:
                    pulseDot = true;
                    SetStatus(DotRecord, "Escuchando...", $"Habla ahora: te escucha {activeName}. Suelta W o Espacio al terminar");
                    break;
                case VoiceAssistant.Phase.Procesando:
                    SetStatus(DotThinking, "Procesando tu pregunta...", $"{Capitalize(speakingName)} está preparando la respuesta");
                    break;
                case VoiceAssistant.Phase.Muletilla:
                    SetStatus(DotThinking, "Un momento, por favor...", $"{Capitalize(speakingName)} está preparando la respuesta");
                    break;
                case VoiceAssistant.Phase.Pensando:
                    pulseDot = true;
                    SetStatus(DotThinking, "Pensando...", $"{Capitalize(speakingName)} está organizando su respuesta");
                    break;
                case VoiceAssistant.Phase.Respondiendo:
                    SetStatus(DotSpeaking, "Respondiendo", $"{Capitalize(speakingName)} responde tu pregunta");
                    break;
                case VoiceAssistant.Phase.Pregrabada:
                    SetStatus(DotSpeaking, $"Pregunta {assistant.PregrabadaActual}", $"Responde {speakingName}");
                    break;
                default:
                    SetStatus(DotReady, "Listo para tu pregunta",
                              $"Mantén pulsada W o Espacio para hablar con {activeName} · Tab: cambiar de personaje");
                    break;
            }
        }

        // Tarjetas: quién escucha (personaje activo esperando o grabando) y quién habla
        bool listeningPhase = !introPending && (phase == VoiceAssistant.Phase.Listo || phase == VoiceAssistant.Phase.Grabando);
        bool speakingPhase = introRunning ? speaking != null
                             : phase == VoiceAssistant.Phase.Muletilla || phase == VoiceAssistant.Phase.Respondiendo
                               || phase == VoiceAssistant.Phase.Pregrabada;
        bool thinkingPhase = !introPending && (phase == VoiceAssistant.Phase.Procesando || phase == VoiceAssistant.Phase.Pensando);
        UpdateChip(rectoraChip, "rectora", rectoraActiva, listeningPhase, speakingPhase, thinkingPhase, speaking, introPending);
        UpdateChip(oswaldoChip, "oswaldo", !rectoraActiva, listeningPhase, speakingPhase, thinkingPhase, speaking, introPending);

        // Botones según el momento
        startIntroButton.SetActive(introPending && !introRunning);
        skipIntroButton.SetActive(introPending);
        skipQuestionButton.SetActive(!introPending && phase != VoiceAssistant.Phase.Listo);
        resetButton.SetActive(!introPending);

        float alpha = pulseDot ? 0.45f + 0.55f * Mathf.Abs(Mathf.Sin(Time.realtimeSinceStartup * 3f)) : 1f;
        dot.color = new Color(dot.color.r, dot.color.g, dot.color.b, alpha);
    }

    void UpdateChip(Chip chip, string speaker, bool isActive, bool listeningPhase, bool speakingPhase,
                    bool thinkingPhase, string speaking, bool introPending)
    {
        bool talking = speakingPhase && speaking == speaker;
        bool listening = listeningPhase && isActive;
        bool thinking = thinkingPhase && speaking == speaker;

        if (talking)        { chip.background.color = SpeakingChip;  chip.role.text = "Hablando"; }
        else if (listening) { chip.background.color = ListeningChip; chip.role.text = assistant.CurrentPhase == VoiceAssistant.Phase.Grabando ? "Escuchando" : "Te escucha"; }
        else if (thinking)  { chip.background.color = IdleChip;      chip.role.text = "Pensando..."; }
        else                { chip.background.color = IdleChip;      chip.role.text = introPending ? "Presentación" : "En espera"; }
    }

    void SetStatus(Color color, string main, string hint)
    {
        dot.color = color;
        title.text = main;
        subtitle.text = hint;
    }

    static string NameOf(string speaker) =>
        speaker == "rectora" ? "la Rectora" : speaker == "oswaldo" ? "Oswaldo" : null;

    static string Capitalize(string s) => string.IsNullOrEmpty(s) ? s : char.ToUpper(s[0]) + s.Substring(1);

    // ── Acciones de los botones ────────────────────────────────────────────────

    void OnStartIntro() { if (intro != null) intro.StartIntro(); }
    void OnSkipIntro()  { if (intro != null) intro.SkipIntro(); }
    void OnSkipQuestion() => assistant.SkipCurrent();
    void OnReset() => assistant.ResetAll();
    void OnPickRectora() { if (IntroDone()) assistant.SetActiveCharacter(true); }
    void OnPickOswaldo() { if (IntroDone()) assistant.SetActiveCharacter(false); }
    bool IntroDone() => intro == null || !intro.isActiveAndEnabled || intro.Finished;

    // ── Construcción de la interfaz ────────────────────────────────────────────

    static void EnsureEventSystem()
    {
        if (FindObjectOfType<EventSystem>() != null) return;
        var es = new GameObject("EventSystem");
        es.AddComponent<EventSystem>();
        es.AddComponent<StandaloneInputModule>();
    }

    void BuildUI()
    {
        var canvas = gameObject.AddComponent<Canvas>();
        canvas.renderMode = RenderMode.ScreenSpaceOverlay;
        canvas.sortingOrder = 100;
        var scaler = gameObject.AddComponent<CanvasScaler>();
        scaler.uiScaleMode = CanvasScaler.ScaleMode.ScaleWithScreenSize;
        scaler.referenceResolution = new Vector2(1920, 1080);
        scaler.matchWidthOrHeight = 0.5f;
        gameObject.AddComponent<GraphicRaycaster>();

        // Barra
        var bar = NewRect("Barra", transform);
        bar.anchorMin = new Vector2(0, 1);
        bar.anchorMax = new Vector2(1, 1);
        bar.pivot = new Vector2(0.5f, 1);
        bar.sizeDelta = new Vector2(0, BAR_HEIGHT);
        bar.anchoredPosition = Vector2.zero;
        bar.gameObject.AddComponent<Image>().color = BarColor;

        // Izquierda: punto de estado + título + indicación
        var status = NewRect("Estado", bar);
        status.anchorMin = new Vector2(0, 0);
        status.anchorMax = new Vector2(0, 1);
        status.pivot = new Vector2(0, 0.5f);
        status.anchoredPosition = new Vector2(32, 0);
        status.sizeDelta = new Vector2(760, 0);

        var dotRect = NewRect("Punto", status);
        dotRect.anchorMin = dotRect.anchorMax = new Vector2(0, 0.5f);
        dotRect.pivot = new Vector2(0, 0.5f);
        dotRect.sizeDelta = new Vector2(22, 22);
        dotRect.anchoredPosition = new Vector2(0, 14);
        dot = dotRect.gameObject.AddComponent<Image>();
        dot.sprite = RoundedSprite(32, 32);

        title = NewText("Titulo", status, 34, FontStyles.Bold, TextColor);
        Place(title.rectTransform, new Vector2(38, 14), new Vector2(720, 44));
        subtitle = NewText("Indicacion", status, 21, FontStyles.Normal, MutedText);
        Place(subtitle.rectTransform, new Vector2(38, -22), new Vector2(720, 30));

        // Centro: tarjetas de los personajes (pulsar una la elige para la siguiente pregunta)
        var chips = NewRect("Personajes", bar);
        chips.anchorMin = chips.anchorMax = new Vector2(0.5f, 0.5f);
        chips.sizeDelta = new Vector2(520, 76);
        chips.anchoredPosition = new Vector2(70, 0);
        var chipsLayout = chips.gameObject.AddComponent<HorizontalLayoutGroup>();
        chipsLayout.spacing = 16;
        chipsLayout.childControlWidth = chipsLayout.childControlHeight = true;
        chipsLayout.childForceExpandWidth = chipsLayout.childForceExpandHeight = true;
        rectoraChip = NewChip(chips, "Rectora", OnPickRectora);
        oswaldoChip = NewChip(chips, "Oswaldo", OnPickOswaldo);

        // Derecha: botones
        var buttons = NewRect("Botones", bar);
        buttons.anchorMin = new Vector2(1, 0);
        buttons.anchorMax = new Vector2(1, 1);
        buttons.pivot = new Vector2(1, 0.5f);
        buttons.anchoredPosition = new Vector2(-28, 0);
        buttons.sizeDelta = new Vector2(560, -36);
        var layout = buttons.gameObject.AddComponent<HorizontalLayoutGroup>();
        layout.spacing = 12;
        layout.childAlignment = TextAnchor.MiddleRight;
        layout.childControlWidth = layout.childControlHeight = true;
        layout.childForceExpandWidth = false;
        layout.childForceExpandHeight = true;

        startIntroButton   = NewButton(buttons, "Iniciar presentación", PrimaryButton, OnStartIntro);
        skipIntroButton    = NewButton(buttons, "Saltar intro", ButtonColor, OnSkipIntro);
        skipQuestionButton = NewButton(buttons, "Saltar pregunta", DangerButton, OnSkipQuestion);
        resetButton        = NewButton(buttons, "Reiniciar (R)", ButtonColor, OnReset);
    }

    Chip NewChip(Transform parent, string label, UnityEngine.Events.UnityAction onClick)
    {
        var rect = NewRect(label, parent);
        var bg = rect.gameObject.AddComponent<Image>();
        bg.sprite = RoundedSprite(64, 14);
        bg.type = Image.Type.Sliced;
        bg.color = IdleChip;
        AddButton(rect.gameObject, onClick);

        var name = NewText("Nombre", rect, 26, FontStyles.Bold, TextColor);
        name.alignment = TextAlignmentOptions.Center;
        Stretch(name.rectTransform, new Vector2(0, 0.45f), new Vector2(1, 1));
        name.text = label;
        var role = NewText("Rol", rect, 18, FontStyles.Normal, new Color(1, 1, 1, 0.85f));
        role.alignment = TextAlignmentOptions.Center;
        Stretch(role.rectTransform, new Vector2(0, 0), new Vector2(1, 0.5f));
        return new Chip { background = bg, name = name, role = role };
    }

    GameObject NewButton(Transform parent, string label, Color color, UnityEngine.Events.UnityAction onClick)
    {
        var rect = NewRect(label, parent);
        var img = rect.gameObject.AddComponent<Image>();
        img.sprite = RoundedSprite(64, 14);
        img.type = Image.Type.Sliced;
        img.color = color;
        AddButton(rect.gameObject, onClick);
        var fitter = rect.gameObject.AddComponent<LayoutElement>();
        fitter.minWidth = 150;

        var text = NewText("Texto", rect, 22, FontStyles.Bold, TextColor);
        text.alignment = TextAlignmentOptions.Center;
        text.text = label;
        Stretch(text.rectTransform, Vector2.zero, Vector2.one);
        text.margin = new Vector4(18, 0, 18, 0);
        fitter.preferredWidth = text.GetPreferredValues(label).x + 36;
        return rect.gameObject;
    }

    static RectTransform NewRect(string name, Transform parent)
    {
        var go = new GameObject(name, typeof(RectTransform));
        go.transform.SetParent(parent, false);
        return (RectTransform)go.transform;
    }

    static TMP_Text NewText(string name, Transform parent, float size, FontStyles style, Color color)
    {
        var rect = NewRect(name, parent);
        var text = rect.gameObject.AddComponent<TextMeshProUGUI>();
        text.fontSize = size;
        text.fontStyle = style;
        text.color = color;
        text.enableWordWrapping = false;
        text.overflowMode = TextOverflowModes.Ellipsis;
        text.raycastTarget = false;
        return text;
    }

    static void Place(RectTransform rect, Vector2 pos, Vector2 size)
    {
        rect.anchorMin = rect.anchorMax = new Vector2(0, 0.5f);
        rect.pivot = new Vector2(0, 0.5f);
        rect.anchoredPosition = pos;
        rect.sizeDelta = size;
    }

    static void Stretch(RectTransform rect, Vector2 min, Vector2 max)
    {
        rect.anchorMin = min;
        rect.anchorMax = max;
        rect.offsetMin = rect.offsetMax = Vector2.zero;
    }

    static void AddButton(GameObject go, UnityEngine.Events.UnityAction onClick)
    {
        var button = go.AddComponent<Button>();
        button.navigation = new Navigation { mode = Navigation.Mode.None };
        button.onClick.AddListener(onClick);
        // Espacio también es "Submit" en la UI: sin esto, al pulsar Espacio para hablar se volvería a pulsar el botón
        button.onClick.AddListener(() => EventSystem.current?.SetSelectedGameObject(null));
    }

    /// <summary>Rectángulo blanco con esquinas redondeadas (radio = size/2 → círculo), listo para 9-slice.
    /// Se genera aquí porque los sprites de UI que trae Unity no siempre entran en el build.</summary>
    static Sprite RoundedSprite(int size, int radius)
    {
        var tex = new Texture2D(size, size, TextureFormat.RGBA32, false) { wrapMode = TextureWrapMode.Clamp };
        var pixels = new Color32[size * size];
        for (int y = 0; y < size; y++)
        for (int x = 0; x < size; x++)
        {
            // distancia al rectángulo interior: 0 dentro, crece en las esquinas
            float dx = Mathf.Max(radius - (x + 0.5f), (x + 0.5f) - (size - radius), 0f);
            float dy = Mathf.Max(radius - (y + 0.5f), (y + 0.5f) - (size - radius), 0f);
            float alpha = Mathf.Clamp01(radius - Mathf.Sqrt(dx * dx + dy * dy) + 0.5f);
            pixels[y * size + x] = new Color32(255, 255, 255, (byte)(alpha * 255));
        }
        tex.SetPixels32(pixels);
        tex.Apply();
        return Sprite.Create(tex, new Rect(0, 0, size, size), new Vector2(0.5f, 0.5f), 100f,
                             0, SpriteMeshType.FullRect, new Vector4(radius, radius, radius, radius));
    }
}
