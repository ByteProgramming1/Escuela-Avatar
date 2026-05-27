using System;
using System.Collections;
using TMPro;
using UnityEngine;
using UnityEngine.Networking;
using UnityEngine.UI;
using static Components;

public class ItemInfo : MonoBehaviour
{
    [SerializeField]
    private Image icon;

    [SerializeField]
    private Image highlightImage;

    private AssetData assetData;

    private string assetType;
    private string assetId;

    [SerializeField] private Color selectedColor;
    private Color deSelectedColor = Color.white;
    public void SetInfo(AssetData assetData)
    {
        this.assetData = assetData;

        if (!string.IsNullOrEmpty(assetData.iconUrl))
        {
            if (isActiveAndEnabled)
            {
                StartCoroutine(LoadImageCoroutine(assetData.iconUrl));
            }
            else if (UIHandler.Instance != null)
            {
                UIHandler.Instance.StartCoroutine(LoadImageCoroutine(assetData.iconUrl));
            }
        }
    }
    public void SetColorInfo(String color, string type, string id)
    {
        icon.color = SetImageColor(icon, color);
        assetType = type;
        assetId = id;
    }
    public void EnableHightlight(bool enable)
    {
        highlightImage.color = enable ? selectedColor : deSelectedColor;
    }

    public void OnButtonClick()
    {
        Debug.Log("assetType :" + assetType);
        if (assetData == null)
        {
            if (assetType == "skinColor" || assetType == "eyebrowColor" || assetType == "beardColor")
            {
                APIHandler.Instance.AddDataToConfig(assetType, assetId);
                EnableHightlight(true);
            }
        }
        else
        {
            Debug.Log("Item clicked: " + assetData.name);
            highlightImage.enabled = false;
            Debug.Log("Type: " + assetData.type + ", ID: " + assetData.id);
            APIHandler.Instance.AddDataToConfig(assetData.type, assetData.id);
            highlightImage.enabled = true;
        }
    }


    public Color SetImageColor(Image image, string hexColor)
    {
        if (image == null)
            return Color.white;

        if (ColorUtility.TryParseHtmlString(hexColor, out Color color))
        {
            return color;
        }
        return Color.white;
    }


    public string GetAssetName()
    {
        return assetData != null ? assetData.name : "";
    }

    IEnumerator LoadImageCoroutine(string url)
    {
        if (icon == null)
            yield break;

        UnityWebRequest request = UnityWebRequestTexture.GetTexture(url);
        yield return request.SendWebRequest();

        if (request.result != UnityWebRequest.Result.Success)
        {
            Debug.Log("Url : " + url);
            Debug.LogError("Image load failed: " + request.error);
            yield break;
        }

        Texture2D texture = DownloadHandlerTexture.GetContent(request);
        Sprite sprite = Sprite.Create(
            texture,
            new Rect(0, 0, texture.width, texture.height),
            new Vector2(0.5f, 0.5f)
        );
        icon.sprite = sprite;
    }
}
