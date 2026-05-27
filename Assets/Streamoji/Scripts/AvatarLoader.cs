using System;
using System.Threading;
using System.Threading.Tasks;
using GLTFast;
using UnityEngine;
using UnityEngine.InputSystem;
using UnityEngine.Networking;
using static Components;

public class AvatarLoader : MonoBehaviour
{
    private const string ProcessUrl = "https://glb.streamoji.com/api/process";
    private const string DefaultBodyType = "Full";

    [SerializeField] private string avatarUrl;

    [Header("Input")]
    [SerializeField] private InputActionAsset inputActionsAsset;

    [Header("Animation")]
    [SerializeField] private Avatar maleAvatar;
    [SerializeField] private Avatar femaleAvatar;
    [SerializeField] private RuntimeAnimatorController animatorController;

    [Header("UI")]
    [SerializeField] private GameObject loadingPanel;

    private GameObject currentAvatar;
    private GameObject maleFullBody;
    private GameObject maleHalfBody;
    private GameObject femaleFullBody;
    private GameObject femaleHalfBody;
    private GameObject currentPlayer;

    private CancellationTokenSource loadCts;
    private CancellationTokenSource downloadCts;

    #region Unity Lifecycle

    private void Awake()
    {
        CreatePlayers();
    }

    private void OnDestroy()
    {
        loadCts?.Cancel();
        downloadCts?.Cancel();
    }

    #endregion

    #region Public API

    [ContextMenu("Load Avatar")]
    public void LoadAvatarTest()
    {
        LoadAvatarFromUrl(avatarUrl);
    }

    public async void LoadAvatarFromUrl(string url)
    {
        if (string.IsNullOrWhiteSpace(url))
        {
            Debug.LogError("Avatar URL is empty");
            return;
        }

        try
        {
            ShowLoading(true);
            DestroyCurrentAvatar();

            var gltf = new GltfImport();
            bool loaded = await gltf.Load(url);
            if (!loaded)
            {
                Debug.LogError("Failed to load GLB from URL");
                return;
            }

            currentAvatar = new GameObject("Avatar");
            currentAvatar.transform.SetParent(transform, false);
            currentAvatar.transform.localPosition = Vector3.zero;
            currentAvatar.transform.localScale = Vector3.one;

            var instantiator = new SafeGameObjectInstantiator(gltf, currentAvatar.transform);
            await gltf.InstantiateMainSceneAsync(instantiator);

            Debug.Log("Avatar loaded successfully");
        }
        catch (Exception e)
        {
            Debug.LogError($"Avatar URL load failed: {e}");
        }
        finally
        {
            ShowLoading(false);
        }
    }

    public async void GenerateAvatar(string authToken, Config avatarConfig)
    {
        loadCts?.Cancel();
        loadCts = new CancellationTokenSource();
        var token = loadCts.Token;

        try
        {
            string bodyType = avatarConfig?.bodyType ?? DefaultBodyType;
            byte[] glbBytes = await RequestAvatarGLB(authToken, avatarConfig, token);
            await LoadAvatarFromBytes(glbBytes, bodyType, token);
        }
        catch (Exception e)
        {
            Debug.LogError($"Avatar generation failed: {e}");
            ShowLoading(false);
        }
    }

    public async void GenerateAvatarFromId(string authToken, string avatarId)
    {
        loadCts?.Cancel();
        loadCts = new CancellationTokenSource();
        var token = loadCts.Token;

        try
        {
            byte[] glbBytes = await RequestAvatarGLBById(authToken, avatarId, token);
            await LoadAvatarFromBytes(glbBytes, DefaultBodyType, token);
        }
        catch (Exception e)
        {
            Debug.LogError($"Avatar generation failed: {e}");
            ShowLoading(false);
        }
    }

    public void GenerateAvatarFromId(string authToken, string avatarId, string bodyType)
    {
        GenerateAvatarFromId(authToken, avatarId, bodyType, true);
    }

    public async void GenerateAvatarFromId(
        string authToken,
        string avatarId,
        string bodyType,
        bool cancelExisting
    )
    {
        CancellationToken token;

        if (cancelExisting)
        {
            loadCts?.Cancel();
            loadCts = new CancellationTokenSource();
            token = loadCts.Token;
        }
        else
        {
            downloadCts?.Cancel();
            downloadCts = new CancellationTokenSource();
            token = downloadCts.Token;
        }

        try
        {
            byte[] glbBytes = await RequestAvatarGLBById(authToken, avatarId, token);
            await LoadAvatarFromBytes(glbBytes, string.IsNullOrWhiteSpace(bodyType) ? DefaultBodyType : bodyType, token);
        }
        catch (Exception e)
        {
            Debug.LogError($"Avatar generation failed: {e}");
            ShowLoading(false);
        }
    }

    #endregion

    #region Player Setup

    private void CreatePlayers()
    {
        if (inputActionsAsset == null)
        {
            Debug.LogError("InputActionsAsset is not assigned.");
            return;
        }

        // Create male players
        if (maleFullBody == null)
            maleFullBody = CreatePlayerObject("Male_FullBody");

        if (maleHalfBody == null)
        {
            maleHalfBody = CreatePlayerObject("Male_HalfBody");
            maleHalfBody.SetActive(false);
        }

        // Create female players
        if (femaleFullBody == null)
        {
            femaleFullBody = CreatePlayerObject("Female_FullBody");
            femaleFullBody.SetActive(false);
        }

        if (femaleHalfBody == null)
        {
            femaleHalfBody = CreatePlayerObject("Female_HalfBody");
            femaleHalfBody.SetActive(false);
        }

        // Start with male full body as default and ensure it's active
        currentPlayer = maleFullBody;
        maleFullBody.SetActive(true);
    }

    private GameObject CreatePlayerObject(string name)
    {
        var playerObj = new GameObject(name);

        var cc = playerObj.AddComponent<CharacterController>();
        cc.height = 2f;
        cc.center = new Vector3(0, 1f, 0);
        cc.skinWidth = 0.08f;

        var controller = playerObj.AddComponent<SimpleThirdPersonController>();

        var input = playerObj.AddComponent<PlayerInput>();
        input.actions = inputActionsAsset;
        input.defaultActionMap = "Player";
        input.notificationBehavior = PlayerNotifications.InvokeCSharpEvents;
        input.neverAutoSwitchControlSchemes = true;
        input.onActionTriggered += controller.OnActionTriggered;

        return playerObj;
    }

    private GameObject GetPlayerForGenderAndBodyType(string genderType, string bodyType)
    {
        bool isFemale = genderType != null && genderType.Equals(GenderType.Female.ToString(), StringComparison.OrdinalIgnoreCase);
        bool isHalf = bodyType != null && bodyType.Equals("Half", StringComparison.OrdinalIgnoreCase);

        if (isFemale)
        {
            return isHalf ? femaleHalfBody : femaleFullBody;
        }
        else
        {
            return isHalf ? maleHalfBody : maleFullBody;
        }
    }

    private void SwitchToPlayer(string bodyType)
    {
        // Get current gender from UIHandler
        string genderType = UIHandler.Instance != null ? UIHandler.Instance.CurrentGenderType : "male";
        var targetPlayer = GetPlayerForGenderAndBodyType(genderType, bodyType);

        if (targetPlayer == null)
        {
            Debug.LogError($"Player for gender '{genderType}' and body type '{bodyType}' not found.");
            return;
        }

        if (currentPlayer != null)
            currentPlayer.SetActive(false);

        targetPlayer.SetActive(true);
        currentPlayer = targetPlayer;
        Debug.Log($"Switched to player: {genderType} {bodyType}");
    }

    #endregion

    #region Loading Pipeline

    private async Task LoadAvatarFromBytes(byte[] glbBytes, string bodyType, CancellationToken token)
    {
        if (glbBytes == null || glbBytes.Length == 0)
            throw new Exception("GLB bytes are empty.");

        ShowLoading(true);
        SwitchToPlayer(bodyType);

        SetCurrentControllerAnimator(null);
        DestroyCurrentAvatar();
        await Task.Yield();

        var gltf = new GltfImport(logger: new UnityGltfLogger());
        var settings = new ImportSettings { AnimationMethod = AnimationMethod.None };
        var baseUri = new Uri("memory://streamoji-avatar");

        bool loaded = await gltf.LoadGltfBinary(glbBytes, baseUri, settings, token);
        if (!loaded)
            throw new Exception("GLTFast failed to parse GLB.");

        currentAvatar = new GameObject("Avatar");
        currentAvatar.transform.SetParent(currentPlayer.transform, false);
        currentAvatar.transform.localPosition = Vector3.zero;
        currentAvatar.transform.localScale = Vector3.one;

        var instantiator = new SafeGameObjectInstantiator(gltf, currentAvatar.transform);
        await gltf.InstantiateMainSceneAsync(instantiator, cancellationToken: token);

        currentAvatar.AddComponent<AvatarRotate>();
        SetupAnimator(currentAvatar);

        Debug.Log($"Avatar replaced successfully for '{bodyType}' body type.");
        ShowLoading(false);
    }

    private void DestroyCurrentAvatar()
    {
        if (currentAvatar == null)
            return;

        Destroy(currentAvatar);
        currentAvatar = null;
    }

    #endregion

    #region Networking

    private async Task<byte[]> RequestAvatarGLB(
        string authToken,
        Config avatarConfig,
        CancellationToken token
    )
    {
        string optionsJson = JsonUtility.ToJson(
            new OptionsWrapper { data = new DataWrapper { assets = avatarConfig } }
        );

        WWWForm form = new WWWForm();
        form.AddField("options", optionsJson);

        Debug.Log("Avatar options json: " + optionsJson);
        return await SendProcessRequest(ProcessUrl, authToken, form, token);
    }

    private async Task<byte[]> RequestAvatarGLBById(
        string authToken,
        string avatarId,
        CancellationToken token
    )
    {
        string url = $"{ProcessUrl}?avatarId={avatarId}";
        Debug.Log("Requesting avatar with avatarId: " + avatarId);
        return await SendProcessRequest(url, authToken, null, token);
    }

    private async Task<byte[]> SendProcessRequest(
        string url,
        string authToken,
        WWWForm form,
        CancellationToken token
    )
    {
        using UnityWebRequest request = form == null
            ? UnityWebRequest.PostWwwForm(url, string.Empty)
            : UnityWebRequest.Post(url, form);

        request.SetRequestHeader("Authorization", $"Bearer {authToken}");
        request.downloadHandler = new DownloadHandlerBuffer();

        ShowLoading(true);

        var operation = request.SendWebRequest();
        while (!operation.isDone)
        {
            if (token.IsCancellationRequested)
                request.Abort();

            await Task.Yield();
        }

        if (request.result != UnityWebRequest.Result.Success)
            throw new Exception(request.error);

        return request.downloadHandler.data;
    }

    #endregion

    #region Animation

    private void SetupAnimator(GameObject avatarRoot)
    {
        var animator = avatarRoot.GetComponentInChildren<Animator>();
        if (animator == null)
            animator = avatarRoot.AddComponent<Animator>();

        // Try to resolve an embedded avatar first
        var resolvedAvatar = ResolveAnimatorAvatar(avatarRoot);
        if (resolvedAvatar != null)
        {
            animator.avatar = resolvedAvatar;
        }
        else
        {
            // If no embedded avatar, assign gender-specific fallback avatar
            if (UIHandler.Instance != null &&
                UIHandler.Instance.CurrentGenderType == GenderType.Female.ToString().ToLower())
            {
                animator.avatar = femaleAvatar != null ? femaleAvatar : maleAvatar;
            }
            else
            {
                animator.avatar = maleAvatar != null ? maleAvatar : femaleAvatar;
            }
        }

        if (animatorController != null)
            animator.runtimeAnimatorController = animatorController;

        animator.applyRootMotion = false;
        animator.cullingMode = AnimatorCullingMode.AlwaysAnimate;
        animator.speed = 1f;

        SetCurrentControllerAnimator(animator);
    }

    private Avatar ResolveAnimatorAvatar(GameObject avatarRoot)
    {
        // Try to find embedded avatar in the loaded GLB model
        foreach (var existingAnimator in avatarRoot.GetComponentsInChildren<Animator>())
        {
            if (existingAnimator.avatar != null &&
                existingAnimator.avatar.isValid &&
                existingAnimator.avatar.isHuman)
            {
                Debug.Log("Using model embedded avatar.");
                return existingAnimator.avatar;
            }
        }

        // No embedded avatar; fall back to gender-specific configured avatar
        if (UIHandler.Instance != null &&
            UIHandler.Instance.CurrentGenderType == GenderType.Female.ToString().ToLower())
        {
            if (femaleAvatar != null)
            {
                Debug.Log("Using fallback femaleAvatar.");
                return femaleAvatar;
            }
            else if (maleAvatar != null)
            {
                Debug.Log("Female avatar not assigned; using maleAvatar as fallback.");
                return maleAvatar;
            }
        }
        else
        {
            if (maleAvatar != null)
            {
                Debug.Log("Using fallback maleAvatar.");
                return maleAvatar;
            }
            else if (femaleAvatar != null)
            {
                Debug.Log("Male avatar not assigned; using femaleAvatar as fallback.");
                return femaleAvatar;
            }
        }

        Debug.LogWarning("No valid avatar found for animator. Both gender avatars are unassigned. Animations may not work correctly.");
        return null;
    }

    private void SetCurrentControllerAnimator(Animator animator)
    {
        if (currentPlayer == null)
            return;

        var controller = currentPlayer.GetComponent<SimpleThirdPersonController>();
        if (controller != null)
            controller.SetAnimator(animator);
    }

    #endregion

    #region Helpers

    private void ShowLoading(bool show)
    {
        if (loadingPanel != null)
            loadingPanel.SetActive(show);
    }

    #endregion
}
