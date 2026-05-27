using System.IO;
using System.Net;
using UnityEditor;
using UnityEngine;

public static class FixAvatarBlendshapes
{
    private const string MORPH_TARGETS = "eyeBlinkLeft,eyeBlinkRight,mouthOpen";

    [MenuItem("Tools/Re-descargar Blendshapes - Rectora (S08EeYdBk5kmUyDobiiY)")]
    public static void DownloadRectora()
    {
        const string avatarId  = "S08EeYdBk5kmUyDobiiY";
        const string assetPath = "Assets/Ready Player Me/Avatars/S08EeYdBk5kmUyDobiiY/avatar-S08EeYdBk5kmUyDobiiY.glb";
        DownloadAvatar(avatarId, assetPath, "Rectora");
    }

    [MenuItem("Tools/Re-descargar Blendshapes - Oswaldo (682bca91f23c99d01dd49ed4)")]
    public static void DownloadOswaldo()
    {
        const string avatarId  = "682bca91f23c99d01dd49ed4";
        const string assetPath = "Assets/Ready Player Me/Avatars/682bca91f23c99d01dd49ed4/2fac66e374c947c41bc74325c6e3d934/682bca91f23c99d01dd49ed4.glb";
        DownloadAvatar(avatarId, assetPath, "Oswaldo");
    }

    private static void DownloadAvatar(string avatarId, string assetPath, string displayName)
    {
        string url = $"https://models.readyplayer.me/{avatarId}.glb" +
                     $"?morphTargets={MORPH_TARGETS}" +
                     $"&useHands=false" +
                     $"&textureAtlas=1024" +
                     $"&lod=0";

        string absolutePath = Path.GetFullPath(assetPath);

        Debug.Log($"[FixBlendshapes] Descargando {displayName}: {url}");

        try
        {
            using (var client = new WebClient())
            {
                client.Headers["User-Agent"] = "UnityEditor";
                client.DownloadFile(url, absolutePath);
            }

            AssetDatabase.ImportAsset(assetPath, ImportAssetOptions.ForceUpdate);
            AssetDatabase.Refresh();

            Debug.Log($"[FixBlendshapes] ¡{displayName} re-descargado con blendshapes correctamente!");
            EditorUtility.DisplayDialog(
                $"{displayName} actualizado",
                $"El avatar fue re-descargado con los morph targets:\n" +
                "• eyeBlinkLeft\n• eyeBlinkRight\n• mouthOpen\n\n" +
                "EyeAnimationHandler y VoiceHandler ahora deberían funcionar en Play.",
                "OK");
        }
        catch (System.Exception e)
        {
            Debug.LogError($"[FixBlendshapes] Error: {e.Message}");
            EditorUtility.DisplayDialog(
                "Error",
                $"No se pudo descargar el avatar {displayName}:\n{e.Message}\n\n" +
                "Verifica tu conexión a internet.",
                "OK");
        }
    }
}
