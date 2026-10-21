using System.Collections.Generic;
using UnityEngine;

/// <summary>
/// Lip sync simple por volumen. Funciona con:
///   - Wolf3D_Avatar (Rectora): un solo mesh combinado con "mouthOpen".
///   - Streamoji / ARKit (Oswaldo): cabeza, dientes y ojos separados, con "jawOpen".
/// Mueve la boca en TODOS los meshes que tengan el blendshape (cabeza + dientes), no solo en el primero.
/// Lee el audio con GetOutputData, así que también funciona con los clips en streaming de VoiceAssistant
/// (el VoiceHandler de Ready Player Me usa clip.GetData, que no tiene datos en un clip en streaming).
/// Auto-detecta el AudioSource del mismo GameObject — no requiere asignación manual.
/// </summary>
public class SimpleLipSync : MonoBehaviour
{
    [Range(0f, 1f)]
    public float maxWeight = 0.25f;
    [Range(1f, 50f)]
    public float sensitivity = 8f;

    private AudioSource _audioSource;
    // Mesh → índice del blendshape de boca. Los ojos de Streamoji también traen jawOpen; se excluyen.
    private readonly List<KeyValuePair<SkinnedMeshRenderer, int>> _targets = new List<KeyValuePair<SkinnedMeshRenderer, int>>();
    private const int SAMPLE_SIZE = 256;
    private float[] _samples = new float[SAMPLE_SIZE];
    private float _smoothed = 0f;

    private void Awake()
    {
        _audioSource = GetComponent<AudioSource>();
        if (_audioSource == null)
            Debug.LogError($"[SimpleLipSync] No se encontró AudioSource en {gameObject.name}");

        // El VoiceHandler de Ready Player Me escribe 0 en la boca cada frame con clips en streaming
        // (no puede leer sus muestras) y pisa este componente: con los dos activos la boca no se mueve.
        var voiceHandler = GetComponent("VoiceHandler") as Behaviour;
        if (voiceHandler != null && voiceHandler.enabled)
        {
            voiceHandler.enabled = false;
            Debug.Log($"[SimpleLipSync] VoiceHandler desactivado en {gameObject.name}: el lip sync lo hace SimpleLipSync");
        }
    }

    private void Start()
    {
        foreach (var smr in GetComponentsInChildren<SkinnedMeshRenderer>(true))
        {
            if (smr.sharedMesh == null || smr.name.StartsWith("Eye")) continue;
            int idx = smr.sharedMesh.GetBlendShapeIndex("mouthOpen");
            if (idx < 0) idx = smr.sharedMesh.GetBlendShapeIndex("jawOpen");
            if (idx < 0) continue;
            _targets.Add(new KeyValuePair<SkinnedMeshRenderer, int>(smr, idx));
            Debug.Log($"[SimpleLipSync] '{smr.sharedMesh.GetBlendShapeName(idx)}' en {smr.name} idx={idx}");
        }

        if (_targets.Count == 0)
            Debug.LogWarning($"[SimpleLipSync] No se encontró mouthOpen/jawOpen en {gameObject.name}");
    }

    // LateUpdate: se aplica después del Animator y de cualquier otro script que toque la boca en Update
    private void LateUpdate()
    {
        if (_targets.Count == 0 || _audioSource == null) return;

        float target = 0f;

        if (_audioSource.isPlaying)
        {
            _audioSource.GetOutputData(_samples, 0);
            float sum = 0f;
            foreach (var s in _samples) sum += s * s;
            float rms = Mathf.Sqrt(sum / SAMPLE_SIZE);
            target = Mathf.Clamp01(rms * sensitivity) * maxWeight;
        }

        _smoothed = Mathf.Lerp(_smoothed, target, Time.deltaTime * 15f);
        foreach (var t in _targets)
            t.Key.SetBlendShapeWeight(t.Value, _smoothed * 3f);
    }

    // Compatible con VoiceAssistant.SendMessage("PlayAudioClip", clip)
    public void PlayAudioClip(AudioClip clip)
    {
        // VoiceAssistant ya lo está reproduciendo: volver a llamar a Play() lo reiniciaría
        if (_audioSource.clip == clip && _audioSource.isPlaying) return;
        _audioSource.clip = clip;
        _audioSource.Play();
    }
}
