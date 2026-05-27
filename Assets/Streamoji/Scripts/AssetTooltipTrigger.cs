using System.Globalization;
using TMPro;
using UnityEngine;
using UnityEngine.EventSystems;

public class AssetTooltipTrigger : MonoBehaviour, IPointerEnterHandler, IPointerExitHandler
{
    public RectTransform tooltip;
    public TextMeshProUGUI tooltipText;
    public Vector2 offset = new Vector2(10f, 10f); // spacing from button

    ItemInfo itemUI;
    RectTransform buttonRect;
    Canvas canvas;

    void Awake()
    {
        itemUI = GetComponent<ItemInfo>();
        buttonRect = transform as RectTransform;
        canvas = tooltip.GetComponentInParent<Canvas>();
    }

    public void OnPointerEnter(PointerEventData eventData)
    {
        if (itemUI == null)
            return;

        tooltip.gameObject.SetActive(true);
        tooltipText.text = FormatName(itemUI.GetAssetName());

        PositionTooltip();
    }

    public void OnPointerExit(PointerEventData eventData)
    {
        tooltip.gameObject.SetActive(false);
    }

    void PositionTooltip()
    {
        // Get button world corners
        Vector3[] corners = new Vector3[4];
        buttonRect.GetWorldCorners(corners);

        // Top-right corner of button
        Vector3 topRightWorld = corners[2];

        // Convert to screen point
        Vector2 screenPoint = RectTransformUtility.WorldToScreenPoint(null, topRightWorld);

        // Convert screen → canvas local position
        RectTransformUtility.ScreenPointToLocalPointInRectangle(
            canvas.transform as RectTransform,
            screenPoint,
            canvas.worldCamera,
            out Vector2 localPoint
        );

        // Apply position + offset
        tooltip.localPosition = localPoint + offset;
    }

    public static string FormatName(string input)
    {
        if (string.IsNullOrEmpty(input))
            return input;

        // Replace hyphens with spaces
        input = input.Replace("-", " ");

        // Convert to Title Case
        TextInfo textInfo = CultureInfo.InvariantCulture.TextInfo;
        return textInfo.ToTitleCase(input);
    }
}
