using UnityEditor;
using UnityEditor.Animations;
using UnityEditor.SceneManagement;
using UnityEngine;

public static class SetupAvatarWalk
{
    private const string AvatarName      = "avatar-S08EeYdBk5kmUyDobiiY";
    private const string ControllerPath  = "Assets/Ready Player Me/Core/Samples/QuickStart/Animations/RpmPlayer.controller";
    private const string WalkControllerPath = "Assets/Animations/AvatarWalkController.controller";
    private const string MaleWalkFbx     = "Assets/Streamoji/Animations/M_Walk_002.fbx";

    [MenuItem("Tools/Cambiar Walk a Locomotion Casual Walk (Masculino)")]
    public static void SetLocomotionCasualWalk()
    {
        AnimatorController ctrl = AssetDatabase.LoadAssetAtPath<AnimatorController>(WalkControllerPath);
        if (ctrl == null)
        {
            Debug.LogError($"[WalkAnim] No se encontró el controlador: {WalkControllerPath}");
            return;
        }

        AnimationClip walkClip = null;
        foreach (Object asset in AssetDatabase.LoadAllAssetsAtPath(MaleWalkFbx))
        {
            if (asset is AnimationClip clip && !clip.name.StartsWith("__preview__"))
            {
                walkClip = clip;
                break;
            }
        }

        if (walkClip == null)
        {
            Debug.LogError($"[WalkAnim] No se encontró AnimationClip en: {MaleWalkFbx}");
            return;
        }

        bool changed = false;
        foreach (AnimatorControllerLayer layer in ctrl.layers)
        {
            foreach (ChildAnimatorState state in layer.stateMachine.states)
            {
                if (state.state.name == "Walk")
                {
                    state.state.motion = walkClip;
                    state.state.speed = 1f;
                    EditorUtility.SetDirty(state.state);
                    changed = true;
                    Debug.Log($"[WalkAnim] Walk state → {walkClip.name} ({MaleWalkFbx})");
                }
            }
        }

        if (changed)
        {
            EditorUtility.SetDirty(ctrl);
            AssetDatabase.SaveAssets();
            AssetDatabase.Refresh();
            Debug.Log("[WalkAnim] AvatarWalkController guardado con animación M_Walk_002.");
            EditorUtility.DisplayDialog("Listo", "Animación de caminata cambiada a M_Walk_002 (Locomotion Casual Walk).", "OK");
        }
        else
        {
            Debug.LogWarning("[WalkAnim] No se encontró el estado 'Walk' en el controlador.");
        }
    }


    [MenuItem("Tools/Configurar Avatar para Caminar")]
    public static void Setup()
    {
        GameObject avatar = GameObject.Find(AvatarName);
        if (avatar == null)
        {
            Debug.LogError($"[SetupWalk] No se encontró el avatar: {AvatarName}");
            return;
        }

        // 1. Asignar RpmPlayer.controller al Animator
        RuntimeAnimatorController controller =
            AssetDatabase.LoadAssetAtPath<RuntimeAnimatorController>(ControllerPath);
        if (controller == null)
        {
            Debug.LogError($"[SetupWalk] No se encontró el controlador en: {ControllerPath}");
            return;
        }

        Animator animator = avatar.GetComponent<Animator>();
        if (animator != null)
        {
            animator.runtimeAnimatorController = controller;
            EditorUtility.SetDirty(animator);
            Debug.Log("[SetupWalk] Controlador RpmPlayer asignado.");
        }

        // 2. Añadir WalkToPoint si no existe
        WalkToPoint walk = avatar.GetComponent<WalkToPoint>();
        if (walk == null)
        {
            walk = avatar.AddComponent<WalkToPoint>();
            Debug.Log("[SetupWalk] WalkToPoint añadido.");
        }

        // 3. Crear un GameObject vacío 'WalkTarget' en la escena como punto destino
        GameObject existing = GameObject.Find("WalkTarget");
        if (existing == null)
        {
            existing = new GameObject("WalkTarget");
            // Colocarlo a 1.5 m delante del avatar como punto de ejemplo
            existing.transform.position = avatar.transform.position +
                                          avatar.transform.forward * 1.5f;
            Debug.Log("[SetupWalk] WalkTarget creado delante del avatar.");
        }

        walk.targetPoint = existing.transform;
        EditorUtility.SetDirty(walk);

        EditorSceneManager.MarkSceneDirty(avatar.scene);
        EditorSceneManager.SaveOpenScenes();

        Debug.Log($"[SetupWalk] Listo. Mueve 'WalkTarget' en la escena al punto deseado.");
        EditorUtility.DisplayDialog(
            "Listo",
            "Avatar configurado.\n\n" +
            "1. Mueve el objeto 'WalkTarget' al punto B deseado.\n" +
            "2. En Play, llama avatar.GetComponent<WalkToPoint>().StartWalk()\n" +
            "   (o activa la opción 'walkOnStart' en el Inspector).",
            "OK");
    }
}
