using UnityEngine;

/// <summary>
/// Lip sync simple compatible con Wolf3D_Avatar (mesh combinado).
/// Auto-detecta el AudioSource del mismo GameObject — no requiere asignación manual.
/// </summary>
public class SimpleLipSync : MonoBehaviour
{
    [Range(0f, 1f)]
    public float maxWeight = 0.25f;
    [Range(1f, 50f)]
    public float sensitivity = 8f;

    private AudioSource _audioSource;
    private SkinnedMeshRenderer _targetMesh;
    private int _blendshapeIndex = -1;
    private const int SAMPLE_SIZE = 256;
    private float[] _samples = new float[SAMPLE_SIZE];
    private float _smoothed = 0f;

    private void Awake()
    {
        _audioSource = GetComponent<AudioSource>();
        if (_audioSource == null)
            Debug.LogError($"[SimpleLipSync] No se encontró AudioSource en {gameObject.name}");
    }

    private void Start()
    {
        foreach (var smr in GetComponentsInChildren<SkinnedMeshRenderer>(true))
        {
            int idx = smr.sharedMesh.GetBlendShapeIndex("mouthOpen");
            if (idx < 0) idx = smr.sharedMesh.GetBlendShapeIndex("jawOpen");
            if (idx >= 0)
            {
                _targetMesh = smr;
                _blendshapeIndex = idx;
                Debug.Log($"[SimpleLipSync] '{smr.sharedMesh.GetBlendShapeName(idx)}' en {smr.name} idx={idx}");
                break;
            }
        }

        if (_blendshapeIndex < 0)
            Debug.LogWarning($"[SimpleLipSync] No se encontró mouthOpen/jawOpen en {gameObject.name}");
    }

    private void Update()
    {
        if (_blendshapeIndex < 0 || _audioSource == null) return;

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
        _targetMesh.SetBlendShapeWeight(_blendshapeIndex, _smoothed * 3f);
    }

    // Compatible con VoiceAssistant.SendMessage("PlayAudioClip", clip)
    public void PlayAudioClip(AudioClip clip)
    {
        _audioSource.clip = clip;
        _audioSource.Play();
    }
}
