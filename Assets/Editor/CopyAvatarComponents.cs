using System;
using UnityEditor;
using UnityEditor.SceneManagement;
using UnityEditorInternal;
using UnityEngine;

public static class CopyAvatarComponents
{
    private const string SourceName = "682bca91f23c99d01dd49ed4";
    private const string TargetName = "avatar-S08EeYdBk5kmUyDobiiY";

    [MenuItem("Tools/Copiar Componentes al Nuevo Avatar")]
    public static void Copy()
    {
        GameObject source = GameObject.Find(SourceName);
        if (source == null)
        {
            Debug.LogError($"[CopyAvatar] No se encontró el avatar origen: {SourceName}");
            return;
        }

        GameObject target = GameObject.Find(TargetName);
        if (target == null)
        {
            Debug.LogError($"[CopyAvatar] No se encontró el avatar destino: {TargetName}");
            return;
        }

        // Copiar el Animator controller
        Animator srcAnim = source.GetComponent<Animator>();
        Animator dstAnim = target.GetComponent<Animator>();
        if (srcAnim != null && dstAnim != null && srcAnim.runtimeAnimatorController != null)
        {
            dstAnim.runtimeAnimatorController = srcAnim.runtimeAnimatorController;
            EditorUtility.SetDirty(dstAnim);
            Debug.Log("[CopyAvatar] Animator controller copiado.");
        }

        // Copiar componentes extra (AudioSource + MonoBehaviours RPM)
        Type[] typesToCopy = { typeof(AudioSource), typeof(MonoBehaviour) };

        foreach (Component comp in source.GetComponents<Component>())
        {
            if (comp == null) continue;
            Type t = comp.GetType();
            // Saltar Transform y Animator (ya están en el prefab / copiado arriba)
            if (t == typeof(Transform) || t == typeof(Animator)) continue;

            // Comprobar si ya existe en destino
            Component existing = target.GetComponent(t);
            if (existing == null)
            {
                ComponentUtility.CopyComponent(comp);
                ComponentUtility.PasteComponentAsNew(target);
                Debug.Log($"[CopyAvatar] Componente añadido: {t.Name}");
            }
            else
            {
                ComponentUtility.CopyComponent(comp);
                ComponentUtility.PasteComponentValues(existing);
                Debug.Log($"[CopyAvatar] Componente actualizado: {t.Name}");
            }
        }

        // Reasignar AudioSource en VoiceHandler si existe
        AudioSource targetAudio = target.GetComponent<AudioSource>();
        foreach (MonoBehaviour mb in target.GetComponents<MonoBehaviour>())
        {
            if (mb == null) continue;
            var field = mb.GetType().GetField("AudioSource");
            if (field != null && targetAudio != null)
            {
                field.SetValue(mb, targetAudio);
                EditorUtility.SetDirty(mb);
                Debug.Log($"[CopyAvatar] AudioSource reasignado en {mb.GetType().Name}.");
            }
        }

        EditorSceneManager.MarkSceneDirty(target.scene);
        EditorSceneManager.SaveOpenScenes();

        Debug.Log($"[CopyAvatar] Listo. Componentes copiados de '{SourceName}' a '{TargetName}'.");
        EditorUtility.DisplayDialog("Listo", $"Componentes copiados al avatar '{TargetName}'.", "OK");
    }
}
