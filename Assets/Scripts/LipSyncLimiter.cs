using UnityEngine;

/// <summary>
/// Limita el peso del blendshape mouthOpen/jawOpen después de que VoiceHandler lo aplica.
/// Añadir este componente al mismo GameObject que VoiceHandler.
/// </summary>
public class LipSyncLimiter : MonoBehaviour
{
    [Range(0f, 1f)]
    public float maxWeight = 0.3f;

    private SkinnedMeshRenderer _mesh;
    private int _blendshapeIndex = -1;

    private void Start()
    {
        foreach (var smr in GetComponentsInChildren<SkinnedMeshRenderer>(true))
        {
            int idx = smr.sharedMesh.GetBlendShapeIndex("jawOpen");
            if (idx < 0) idx = smr.sharedMesh.GetBlendShapeIndex("mouthOpen");
            if (idx >= 0)
            {
                _mesh = smr;
                _blendshapeIndex = idx;
                break;
            }
        }
    }

    private void LateUpdate()
    {
        if (_blendshapeIndex < 0 || _mesh == null) return;
        float current = _mesh.GetBlendShapeWeight(_blendshapeIndex);
        if (current > maxWeight)
            _mesh.SetBlendShapeWeight(_blendshapeIndex, maxWeight);
    }
}
