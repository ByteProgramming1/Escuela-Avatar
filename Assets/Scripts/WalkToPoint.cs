using UnityEngine;

public class WalkToPoint : MonoBehaviour
{
    [Header("Destino")]
    public Transform targetPoint;

    [Header("Ruta (opcional)")]
    [Tooltip("Puntos intermedios por donde pasa antes de llegar a targetPoint")]
    public Transform[] waypoints;

    [Header("Configuración")]
    public float walkSpeed      = 0.8f;
    public float rotationSpeed  = 8f;
    public float stopDistance   = 0.1f;
    public bool  walkOnStart    = false;

    [Header("Al llegar")]
    public Transform lookAtTarget;
    public float turnSpeed = 4f;

    private Animator _animator;
    private bool _walking;
    private bool _turning;
    private bool _hasIsWalkingParam;
    private int  _waypointIndex;
    private float _lockedY;

    public bool IsWalking => _walking;

    private static readonly int IsWalkingHash = Animator.StringToHash("IsWalking");

    void Start()
    {
        _animator = GetComponent<Animator>();
        if (_animator != null)
            _animator.applyRootMotion = false;
        CacheAnimatorParams();
        _lockedY = transform.position.y;
        SnapFacingToFirstTarget();
        if (walkOnStart)
            StartWalk();
    }

    private void SnapFacingToFirstTarget()
    {
        Transform first = (waypoints != null && waypoints.Length > 0) ? waypoints[0] : targetPoint;
        if (first == null) return;
        Vector3 dir = first.position - transform.position;
        dir.y = 0f;
        if (dir.sqrMagnitude > 0.001f)
            transform.rotation = Quaternion.LookRotation(dir.normalized);
    }

    private void CacheAnimatorParams()
    {
        _hasIsWalkingParam = false;
        if (_animator == null) return;
        foreach (var p in _animator.parameters)
            if (p.nameHash == IsWalkingHash) { _hasIsWalkingParam = true; break; }
    }

    public void StartWalk()
    {
        if (targetPoint != null || (waypoints != null && waypoints.Length > 0))
        {
            _waypointIndex = 0;
            _walking = true;
            _turning = false;
        }
    }

    private Transform CurrentTarget()
    {
        if (waypoints != null && _waypointIndex < waypoints.Length)
            return waypoints[_waypointIndex];
        return targetPoint;
    }

    public void StopWalk()
    {
        _walking = false;
        _turning = true;
        SetWalking(false);
    }

    void Update()
    {
        if (_walking)
            HandleWalking();
        else if (_turning)
            HandleTurning();

        // Fija el eje Y para evitar que la animación haga flotar al avatar
        if (_walking || _turning)
        {
            Vector3 p = transform.position;
            p.y = _lockedY;
            transform.position = p;
        }
    }

    private void HandleWalking()
    {
        Transform current = CurrentTarget();
        if (current == null) { StopWalk(); return; }

        Vector3 dir = current.position - transform.position;
        dir.y = 0f;

        if (dir.magnitude <= stopDistance)
        {
            if (waypoints != null && _waypointIndex < waypoints.Length)
            {
                _waypointIndex++;
                return;
            }
            StopWalk();
            return;
        }

        transform.rotation = Quaternion.Slerp(
            transform.rotation,
            Quaternion.LookRotation(dir.normalized),
            Time.deltaTime * rotationSpeed);

        Vector3 move = transform.forward * walkSpeed * Time.deltaTime;
        move.y = 0f;
        transform.position += move;
        SetWalking(true);
    }

    private void HandleTurning()
    {
        Transform cam = lookAtTarget != null ? lookAtTarget : Camera.main?.transform;
        if (cam == null) { _turning = false; return; }

        // Dirección hacia la cámara, ignorando eje Y
        Vector3 dir = cam.position - transform.position;
        dir.y = 0f;
        if (dir.sqrMagnitude < 0.001f) { _turning = false; return; }

        Quaternion target = Quaternion.LookRotation(dir.normalized);
        transform.rotation = Quaternion.Slerp(transform.rotation, target, Time.deltaTime * turnSpeed);

        // Termina cuando el ángulo restante es menor a 1 grado
        if (Quaternion.Angle(transform.rotation, target) < 1f)
        {
            transform.rotation = target;
            _turning = false;
        }
    }

    private void SetWalking(bool value)
    {
        if (_animator != null && _animator.isInitialized && _hasIsWalkingParam)
            _animator.SetBool(IsWalkingHash, value);
    }
}
