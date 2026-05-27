using UnityEditor;
using UnityEditor.SceneManagement;
using UnityEngine;

public static class PlaceNewAvatar
{
    private const string NewGlbPath    = "Assets/Ready Player Me/Avatars/S08EeYdBk5kmUyDobiiY/avatar-S08EeYdBk5kmUyDobiiY.glb";
    private const string ExistingName  = "682bca91f23c99d01dd49ed4";
    private const string NewAvatarName = "S08EeYdBk5kmUyDobiiY";
    private const float  SideOffset    = 0.8f; // metros a la derecha del avatar existente

    [MenuItem("Tools/Colocar Nuevo Avatar al Lado")]
    public static void Place()
    {
        // Importar el GLB si Unity no lo ha procesado aún
        AssetDatabase.ImportAsset(NewGlbPath, ImportAssetOptions.ForceUpdate);
        AssetDatabase.Refresh();

        GameObject prefab = AssetDatabase.LoadAssetAtPath<GameObject>(NewGlbPath);
        if (prefab == null)
        {
            Debug.LogError($"[PlaceNewAvatar] No se encontró el GLB en: {NewGlbPath}");
            return;
        }

        // Encontrar el avatar existente en la escena para tomar su posición
        GameObject existing = GameObject.Find(ExistingName);
        Vector3 basePos = existing != null
            ? existing.transform.position
            : new Vector3(0.187f, 0f, -2.338f);

        Quaternion baseRot = existing != null
            ? existing.transform.rotation
            : Quaternion.identity;

        // Verificar que el nuevo avatar no esté ya en la escena
        if (GameObject.Find(NewAvatarName) != null)
        {
            Debug.LogWarning("[PlaceNewAvatar] El avatar nuevo ya existe en la escena.");
            return;
        }

        Vector3 newPos = basePos + new Vector3(SideOffset, 0f, 0f);
        GameObject instance = (GameObject)PrefabUtility.InstantiatePrefab(prefab);
        instance.transform.position = newPos;
        instance.transform.rotation = baseRot;
        instance.name = NewAvatarName;

        EditorSceneManager.MarkSceneDirty(instance.scene);
        EditorSceneManager.SaveOpenScenes();

        Debug.Log($"[PlaceNewAvatar] Avatar colocado en {newPos}. Escena guardada.");
        EditorUtility.DisplayDialog("Listo", $"Avatar '{NewAvatarName}' colocado a {SideOffset}m del avatar existente.", "OK");
    }
}
