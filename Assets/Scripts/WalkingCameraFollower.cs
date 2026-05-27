using UnityEngine;

/// <summary>
/// Cámara que se desplaza por delante del grupo de avatares y los encuadra mientras caminan.
/// Incluye detección de paredes para no atravesarlas.
/// </summary>
public class WalkingCameraFollower : MonoBehaviour
{
    [Header("Avatares a seguir")]
    public Transform avatar1;
    public Transform avatar2;

    [Header("Posición relativa")]
    [Tooltip("Metros por delante del punto medio entre los dos avatares")]
    public float forwardOffset = 3.5f;
    [Tooltip("Altura de la cámara sobre el suelo")]
    public float heightOffset  = 1.7f;
    [Tooltip("Suavidad del movimiento (mayor = más rígido)")]
    public float followSpeed   = 4f;

    [Header("Punto de mira")]
    [Tooltip("Altura del punto central al que mira la cámara (aprox. pecho de los avatares)")]
    public float lookHeight = 1.3f;
    [Tooltip("Suavidad de la rotación")]
    public float rotationSpeed = 5f;

    [Header("Anti-pared")]
    [Tooltip("Margen de separación con la pared al retroceder la cámara")]
    public float wallMargin = 0.4f;

    void LateUpdate()
    {
        if (avatar1 == null || avatar2 == null) return;

        Vector3 mid     = (avatar1.position + avatar2.position) * 0.5f;
        Vector3 forward = (avatar1.forward  + avatar2.forward).normalized;
        if (forward.sqrMagnitude < 0.001f) return;

        // Destino ideal: delante del grupo a la altura configurada
        Vector3 targetPos = mid + forward * forwardOffset;
        targetPos.y = mid.y + heightOffset;

        // Anti-pared: raycast desde el punto medio (a altura de cámara) hacia targetPos
        Vector3 rayOrigin = new Vector3(mid.x, targetPos.y, mid.z);
        Vector3 toTarget  = targetPos - rayOrigin;
        if (toTarget.magnitude > 0.1f)
        {
            if (Physics.Raycast(rayOrigin, toTarget.normalized, out RaycastHit hit,
                                toTarget.magnitude, ~0, QueryTriggerInteraction.Ignore))
                targetPos = hit.point - toTarget.normalized * wallMargin;
        }

        transform.position = Vector3.Lerp(transform.position, targetPos,
                                          Time.deltaTime * followSpeed);

        // Mira al punto medio al nivel del pecho
        Vector3 lookAt = mid + Vector3.up * lookHeight;
        Vector3 dir    = lookAt - transform.position;
        if (dir.sqrMagnitude > 0.001f)
        {
            transform.rotation = Quaternion.Slerp(transform.rotation,
                                     Quaternion.LookRotation(dir),
                                     Time.deltaTime * rotationSpeed);
        }
    }
}
