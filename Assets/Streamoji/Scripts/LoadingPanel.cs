using System.Collections;
using UnityEngine;
using UnityEngine.UI;

public class LoadingPanel : MonoBehaviour
{
    [SerializeField]
    private Image spinner;

    [SerializeField]
    private float fillSpeed = 1.2f;
    private Coroutine fillRoutine;

    private void OnEnable()
    {
        StartLoading();
    }

    private void OnDisable()
    {
        StopLoading();
    }

    private void StartLoading()
    {
        if (spinner == null)
            return;

        spinner.fillAmount = 0f;
        fillRoutine = StartCoroutine(FillLoop());
    }

    private void StopLoading()
    {
        if (fillRoutine != null)
            StopCoroutine(fillRoutine);

        fillRoutine = null;

        if (spinner != null)
            spinner.fillAmount = 0f;
    }

    private IEnumerator FillLoop()
    {
        while (true)
        {
            spinner.fillAmount += Time.deltaTime * fillSpeed;

            if (spinner.fillAmount >= 1f)
                spinner.fillAmount = 0f;

            yield return null;
        }
    }
}
