using GLTFast.Schema;
using UnityEngine;
using UnityEngine.EventSystems;

public class ButtonHover : MonoBehaviour, IPointerEnterHandler, IPointerExitHandler
{
    public GameObject hoverText;
    public GameObject hoverImage;

    public void OnPointerEnter(PointerEventData eventData)
    {
        hoverImage.SetActive(true);
        hoverText.SetActive(true);
    }

    public void OnPointerExit(PointerEventData eventData)
    {
        hoverImage.SetActive(false);
        hoverText.SetActive(false);
    }
}
