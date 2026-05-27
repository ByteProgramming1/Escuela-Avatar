using UnityEngine;
using UnityEngine.InputSystem;

public class AvatarRotate : MonoBehaviour
{
    public float rotationSpeed = 0.2f;

    private Vector2 lastPos;
    private bool dragging;
    private float yaw;

    void Start()
    {
        yaw = transform.localEulerAngles.y;
    }

    void Update()
    {
        if (Mouse.current == null)
            return;

        if (Mouse.current.leftButton.wasPressedThisFrame)
        {
            dragging = true;
            lastPos = Mouse.current.position.ReadValue();
        }

        if (Mouse.current.leftButton.wasReleasedThisFrame)
        {
            dragging = false;
        }

        if (!dragging)
            return;

        Vector2 pos = Mouse.current.position.ReadValue();
        float deltaX = pos.x - lastPos.x;

        yaw -= deltaX * rotationSpeed;
        transform.localRotation = Quaternion.Euler(0, yaw, 0);

        lastPos = pos;
    }
}
