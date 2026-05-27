using UnityEngine;
using UnityEngine.InputSystem;

[RequireComponent(typeof(CharacterController))]
public class SimpleThirdPersonController : MonoBehaviour
{
    [Header("Movement")]
    public float moveSpeed = 4f;
    public float groundAcceleration = 22f;
    public float groundDeceleration = 28f;
    public float airAcceleration = 10f;

    [Header("Jump")]
    public float jumpForce = 6f;
    public float gravity = -20f;
    public float groundedStickForce = -2f;

    [Header("Rotation")]
    public float rotationSpeed = 720f;
    public float mouseSensitivity = 0.15f;

    private Vector2 moveInput;
    private float verticalVelocity;
    private Vector3 horizontalVelocity;

    private CharacterController controller;
    private Camera cam;
    private Animator animator;

    void Awake()
    {
        controller = GetComponent<CharacterController>();
        cam = Camera.main;
        // animator = GetComponentInChildren<Animator>();
    }

    public void SetAnimator(Animator newAnimator)
    {
        animator = newAnimator;
    }

    void Update()
    {
        HandleMouseRotation();
        HandleMovementAndGravity();
    }

    // MOUSE ROTATION

    void HandleMouseRotation()
    {
        if (Mouse.current == null)
            return;

        float mouseX = Mouse.current.delta.ReadValue().x;

        if (Mathf.Abs(mouseX) > 0.01f)
            transform.Rotate(Vector3.up, mouseX * mouseSensitivity, Space.World);
    }

    // MOVEMENT

    void HandleMovementAndGravity()
    {
        if (cam == null)
            cam = Camera.main;

        if (cam == null)
            return;

        Vector3 inputDir = new Vector3(moveInput.x, 0, moveInput.y);
        float inputMagnitude = Mathf.Clamp01(inputDir.magnitude);

        if (animator)
            animator.SetFloat("speed", inputMagnitude);

        Vector3 camForward = cam.transform.forward;
        camForward.y = 0;
        camForward.Normalize();

        Vector3 camRight = cam.transform.right;
        camRight.y = 0;
        camRight.Normalize();

        Vector3 desiredMove = (camForward * inputDir.z + camRight * inputDir.x).normalized * moveSpeed * inputMagnitude;
        bool isGrounded = controller.isGrounded;

        float accel = isGrounded
            ? (inputMagnitude > 0.01f ? groundAcceleration : groundDeceleration)
            : airAcceleration;

        horizontalVelocity = Vector3.MoveTowards(horizontalVelocity, desiredMove, accel * Time.deltaTime);

        if (animator)
            animator.SetBool("IsGrounded", isGrounded);

        if (isGrounded && verticalVelocity < 0)
            verticalVelocity = groundedStickForce;

        verticalVelocity += gravity * Time.deltaTime;
        Vector3 totalVelocity = horizontalVelocity + Vector3.up * verticalVelocity;
        controller.Move(totalVelocity * Time.deltaTime);

        Vector3 lookDirection = horizontalVelocity;
        lookDirection.y = 0f;
        if (lookDirection.sqrMagnitude > 0.0001f)
        {
            Quaternion targetRotation = Quaternion.LookRotation(lookDirection.normalized);
            transform.rotation = Quaternion.RotateTowards(
                transform.rotation,
                targetRotation,
                rotationSpeed * Time.deltaTime
            );
        }

    }

    // INPUT CALLBACK

    public void OnActionTriggered(InputAction.CallbackContext context)
    {
        if (context.action.name == "Move")
        {
            moveInput = context.ReadValue<Vector2>();
        }

        if (context.action.name == "Jump" && context.performed)
        {
            if (controller.isGrounded)
            {
                verticalVelocity = jumpForce;
                if (animator)
                    animator.SetTrigger("Jump");
            }
        }
    }
}
