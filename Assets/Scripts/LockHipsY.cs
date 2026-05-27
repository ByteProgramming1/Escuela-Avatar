using UnityEngine;

/// <summary>
/// Bloquea la posición Y local del hueso Hips para que el avatar
/// no suba ni baje mientras camina. Añadir al mismo GameObject del Animator.
/// </summary>
public class LockHipsY : MonoBehaviour
{
    private Animator _animator;
    private Transform _hips;
    private float _lockedY;
    private bool _ready;

    private void Start()
    {
        _animator = GetComponentInChildren<Animator>();
        if (_animator == null || !_animator.isHuman) return;

        _hips = _animator.GetBoneTransform(HumanBodyBones.Hips);
        if (_hips == null) return;

        // Espera un frame para que el avatar termine de inicializarse
        Invoke(nameof(CaptureY), 0.1f);
    }

    private void CaptureY()
    {
        if (_hips != null)
        {
            _lockedY = _hips.localPosition.y;
            _ready = true;
        }
    }

    private void LateUpdate()
    {
        if (!_ready || _hips == null) return;
        Vector3 p = _hips.localPosition;
        p.y = _lockedY;
        _hips.localPosition = p;
    }
}
