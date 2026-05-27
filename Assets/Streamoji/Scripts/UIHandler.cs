using System;
using System.Collections;
using System.Collections.Generic;
using System.Diagnostics;
using UnityEngine;
using UnityEngine.UI;
using static Components;

public class UIHandler : MonoBehaviour
{
    public static UIHandler Instance;

    #region Constants

    private const string FACE = "face";
    private const string CLOTHES = "clothes";
    private const string GENDER = "gender";
    private const string GLASSES = "glasses";
    private const string FACE_WEAR = "facewear";
    private const string FACE_MASK = "facemask";
    private const string HEAD_WEAR = "headwear";
    private const string HAIR_STYLE = "hairstyle";

    private const string FACE_SHAPE = "faceshape";
    private const string EYE_SHAPE = "eyeshape";
    private const string EYE_COLOR = "eyecolor";
    private const string EYEBROW_STYLE = "eyebrowstyle";
    private const string NOSE_SHAPE = "noseshape";
    private const string LIP_SHAPE = "lipshape";
    private const string BEARD_STYLE = "beardstyle";

    private const string TOP = "top";
    private const string SHIRT = "shirt";
    private const string FULL = "Full";
    private const string HALF = "Half";

    private const string SKIN_COLOR_KEY = "skinColor";
    private const string EYEBROW_COLOR_KEY = "eyebrowColor";
    private const string BEARD_COLOR_KEY = "beardColor";
    private const string HAIR_COLOR_KEY = "hairColor";
    private const string BODY_TYPE_KEY = "bodyType";
    private const string BODY_SHAPE_KEY = "bodyShape";

    private const string CLIENT_ID = "client_rdvS5090V1RQA5dQ1LlrwOwAaF22";
    private const string CLIENT_SECRET = "SAnyVdXRNEISVyoEHEPnKAWsnQhsuTAf";

    private static readonly HashSet<string> LargeCardTypes = new HashSet<string>(
        StringComparer.OrdinalIgnoreCase
    )
    {
        GLASSES,
        FACE_WEAR,
        FACE_MASK,
        HEAD_WEAR,
        HAIR_STYLE,
    };

    private static readonly HashSet<string> FaceContentTypes = new HashSet<string>(
        StringComparer.OrdinalIgnoreCase
    )
    {
        FACE_SHAPE,
        EYE_SHAPE,
        EYEBROW_STYLE,
        LIP_SHAPE,
        NOSE_SHAPE,
        BEARD_STYLE,
    };

    #endregion

    #region State

    private string requestedAvatarType = string.Empty;

    private string currentAvatarBodyType = BodyType.Full.ToString().ToLower();
    public string CurrentAvatarBodyType => currentAvatarBodyType;

    private string currentAvatarType = string.Empty;
    public string CurrentAvatarType => currentAvatarType;

    private string currentCategoryType = CategoryTypes.Face.ToString().ToLower();
    public string CurrentCategoryType => currentCategoryType;

    private string currentGenderType = GenderType.Male.ToString().ToLower();
    public string CurrentGenderType => currentGenderType;

    private string currentBodyPartType = BodyTypes.Athletic.ToString().ToLower();
    public string CurrentBodyPartType => currentBodyPartType;

    #endregion

    #region Auth Inputs

    [SerializeField] private InputField clientIDTMP;
    [SerializeField] private InputField clientSecretTMP;

    #endregion

    #region Panels

    [Header("Panels")]
    [SerializeField] private GameObject GetAuthTokenPanel;
    [SerializeField] private GameObject EditAvatarPanel;
    [SerializeField] private GameObject SavePanel;
    [SerializeField] private GameObject SaveLoadingPanel;
    [SerializeField] private GameObject SaveTextPanel;
    [SerializeField] private GameObject DownloadPanel;
    [SerializeField] private GameObject CongrualationsPanel;
    [SerializeField] private Text savedPathTMP;

    [SerializeField] private Image halfBodyIcon;
    [SerializeField] private Image fullBodyIcon;
    [SerializeField] private GameObject HalfBodyPanel;
    [SerializeField] private GameObject GlassesBodyPanel;
    [SerializeField] private GameObject GenderPanel;
    [SerializeField] private GameObject Facepanel;
    [SerializeField] private GameObject ClothesPanel;

    [SerializeField] private GameObject GamePanel;

    [SerializeField] private GameObject RightSidePanel;
    [SerializeField] private Transform rightSideContentTransform;
    [SerializeField] private Transform FaceContentTransform;

    #endregion

    #region Assets UI

    public ItemInfo itemCardInfo;
    public ItemInfo itemLargeCardInfo;
    public ItemInfo itemSmallCardInfo;

    public Transform FullBodyContentTransform;
    public Transform HalfBodyContentTransform;
    public Transform GlassesContentTransform;

    private AssetsRootData eyeAssetsRootData;

    #endregion

    #region Buttons And Colors

    public List<CategoryButtonList> categoryButtonList;
    public List<AccessoryButtonList> accessoryButtonList;
    public List<GenderButtonList> genderButtonList;
    public List<BodyPartButtonList> bodyPartButtonList;

    public Color selectedColor;
    public Color deSelectedColor = Color.white;
    public Color iconSelectedColor;

    public List<string> colorList = new List<string>
    {
        "#000000",
        "#191919",
        "#494949",
        "#4B3329",
        "#583C2F",
        "#764639",
        "#915334",
        "#695038",
        "#80623C",
        "#937A63",
        "#AD8057",
        "#BB8C4B",
        "#C79860",
        "#D89A70",
        "#E8AF6B",
        "#DAB57F",
        "#E7BB94",
        "#DBC9B4",
        "#7A697A",
        "#7D7270",
        "#878174",
        "#9B8F84",
        "#B5A198",
        "#C5B7AE",
        "#C8C8D7",
        "#75363B",
        "#9A1A1A",
        "#A12831",
        "#BD2816",
        "#E43430",
        "#9A310A",
        "#9E4524",
        "#D04E2E",
        "#E15D23",
        "#C07031",
        "#BF7A44",
        "#EC8C42",
        "#E9931B",
        "#E0B42B",
        "#E9BC2A",
        "#E1E156",
        "#9AD254",
        "#84A739",
        "#738747",
        "#83BC7F",
        "#68B374",
        "#3CB27F",
        "#5F907E",
        "#2A6C54",
        "#539B9B",
        "#4EA3C3",
        "#4D8EBC",
        "#4777A9",
        "#6085DB",
        "#6475B6",
        "#5C639F",
        "#665877",
        "#886687",
        "#A784B1",
        "#AD96D8",
        "#BE88BC",
        "#E073DB",
        "#E36F90",
        "#E7436E",
        "#D63E65",
        "#B35C8D",
        "#954472"
    };

    private readonly List<string> skinColorList = new List<string>
    {
        "#F4D2C4",
        "#ECCABC",
        "#E4C2B4",
        "#DCBAAC",
        "#D4B2A4",
        "#C4A294",
        "#9F8378",
        "#8C746A",
        "#7A655C",
        "#67554E",
        "#554640"
    };

    #endregion

    #region Save Loader

    [SerializeField] private Image saveSpinner;
    [SerializeField] private float fillSpeed = 1.2f;
    private Coroutine fillRoutine;

    #endregion

    #region Unity Lifecycle

    private void Awake()
    {
        if (Instance != null && Instance != this)
        {
            Destroy(gameObject);
            return;
        }

        Instance = this;
    }

    private void Start()
    {
        StartCoroutine(DelayedAuthCheck());
        EnableButtonClicks();
        SelectCategoryIcon(CategoryTypes.Face);

        int faceIndex = categoryButtonList.FindIndex(b => b.type == CategoryTypes.Face);
        if (faceIndex >= 0)
            CategoryButtonClick(categoryButtonList[faceIndex]);

        requestedAvatarType = FACE_SHAPE;
    }

    #endregion

    #region Auth Flow

    private IEnumerator DelayedAuthCheck()
    {
        yield return null;

        if (APIHandler.Instance.HasValidToken())
        {
            ShowEditAvatarPanel();
            APIHandler.Instance.FetchEyeColorAssets(false);
        }
        else
        {
            ShowGetAuthTokenPanel();
        }
    }

    public void GetAuthTokenButtonClick()
    {
        APIHandler.Instance.OnGetAuthToken(clientIDTMP.text, clientSecretTMP.text);
    }

    public void OnAuthTokenSuccess()
    {
        ShowEditAvatarPanel();
        APIHandler.Instance.FetchEyeColorAssets(false);
    }

    public void AutoFillClientId()
    {
        clientIDTMP.text = CLIENT_ID;
    }

    public void AutoFillClientSecret()
    {
        clientSecretTMP.text = CLIENT_SECRET;
    }

    #endregion

    #region Panel Switching

    public void EditAvatarPanelButtonClick()
    {
        GamePanel.SetActive(false);

        // If there's a valid token, open edit flow; otherwise go to auth panel
        if (APIHandler.Instance != null && APIHandler.Instance.HasValidToken())
        {
            ShowEditAvatarPanel();
        }
        else
        {
            ShowGetAuthTokenPanel();
        }
    }

    public void ExitAvatarButtonClick()
    {
        // Called from GamePanel: hide game UI and open avatar editor (or auth if no token)
        GamePanel.SetActive(false);

        if (APIHandler.Instance != null && APIHandler.Instance.HasValidToken())
        {
            ShowEditAvatarPanel();
        }
        else
        {
            ShowGetAuthTokenPanel();
        }
    }

    public void ShowGetAuthTokenPanel()
    {
        GetAuthTokenPanel.SetActive(true);
        EditAvatarPanel.SetActive(false);
    }

    public void ShowEditAvatarPanel()
    {
        GetAuthTokenPanel.SetActive(false);
        EditAvatarPanel.SetActive(true);
        DownloadPanel.SetActive(false);
        StartCoroutine(DelayedLoadAvatar());
    }

    private IEnumerator DelayedLoadAvatar()
    {
        yield return null;

        APIHandler.Instance.SetConfig(currentGenderType);
        APIHandler.Instance.LoadAvatar();

        if (accessoryButtonList.Count > 0)
            accessoryButtonList[0].Icon.color = selectedColor;

        EnsureDefaultFaceCategoryLoaded();
    }

    #endregion

    #region Assets Rendering

    public void ShowAssetsData(AssetsRootData assetsRootData = null)
    {
        if (assetsRootData == null)
            return;

        ClearAssetUI();

        bool renderedEyeShape = false;
        foreach (var item in assetsRootData.data)
        {
            if (!item.type.Equals(currentAvatarType, StringComparison.OrdinalIgnoreCase))
                continue;

            CreateItemCard(item);
            if (currentAvatarType.Equals(EYE_SHAPE, StringComparison.OrdinalIgnoreCase))
                renderedEyeShape = true;
        }

        if (renderedEyeShape)
            EnableEyeColorFeatures();
        else if (currentCategoryType == FACE)
            HandleRightSideFlow();
    }

    public void ShowEyeColorAssetsData(AssetsRootData assetsRootData = null)
    {
        if (assetsRootData == null)
            return;

        eyeAssetsRootData = assetsRootData;
        RightSidePanel.SetActive(true);

        foreach (var item in eyeAssetsRootData.data)
            CreateItemCard(item);
    }

    private void HandleRightSideFlow()
    {
        ClearRightSideContent();

        if (requestedAvatarType == FACE_SHAPE)
            EnableFaceColorFeatures();
        else if (requestedAvatarType == EYEBROW_STYLE)
            EnableEyeBrowColorFeatures();
        else if (requestedAvatarType == BEARD_STYLE)
            EnableBeardColorFeatures();
        else
            RightSidePanel.SetActive(false);
    }

    private void ClearAssetUI()
    {
        ClearChildren(FullBodyContentTransform);
        ClearChildren(HalfBodyContentTransform);
        ClearChildren(GlassesContentTransform);

        if (FaceContentTypes.Contains(currentAvatarType))
            ClearChildren(FaceContentTransform);
    }

    private void CreateItemCard(AssetData item)
    {
        string itemType = item.type.ToLower();
        Transform parentTransform = ResolveParentTransform(itemType);

        ItemInfo prefab =
            LargeCardTypes.Contains(itemType)
                ? itemLargeCardInfo
                : itemType == EYE_COLOR ? itemSmallCardInfo : itemCardInfo;

        ItemInfo itemInfo = Instantiate(prefab, parentTransform);
        itemInfo.gameObject.SetActive(true);
        itemInfo.SetInfo(item);
    }

    private Transform ResolveParentTransform(string itemType)
    {
        if (LargeCardTypes.Contains(itemType))
            return GlassesContentTransform;

        if (FaceContentTypes.Contains(itemType))
            return FaceContentTransform;

        if (itemType == EYE_COLOR)
            return rightSideContentTransform;

        return IsHalfBody() ? HalfBodyContentTransform : FullBodyContentTransform;
    }

    private void ClearChildren(Transform parent)
    {
        foreach (Transform child in parent)
            Destroy(child.gameObject);
    }

    private bool IsHalfBody()
    {
        return currentAvatarBodyType.Equals(BodyType.Half.ToString(), StringComparison.OrdinalIgnoreCase);
    }

    #endregion

    #region Category Button Logic

    public void EnableButtonClicks()
    {
        foreach (var item in accessoryButtonList)
        {
            AccessoryButtonList buttonItem = item;
            buttonItem.button.onClick.AddListener(() => AccessoryItemButtonClick(buttonItem));
        }

        foreach (var item in categoryButtonList)
        {
            CategoryButtonList buttonItem = item;
            buttonItem.button.onClick.AddListener(() => CategoryButtonClick(buttonItem));
        }

        foreach (var item in genderButtonList)
        {
            GenderButtonList buttonItem = item;
            buttonItem.button.onClick.AddListener(() => OnGenderItemButtonClick(buttonItem));
        }

        foreach (var item in bodyPartButtonList)
        {
            BodyPartButtonList buttonItem = item;
            buttonItem.button.onClick.AddListener(() => OnBodyPartItemButtonClick(buttonItem));
        }
    }

    private void AccessoryItemButtonClick(AccessoryButtonList item)
    {
        DeselectAllColors();
        item.Icon.color = selectedColor;

        if (currentCategoryType == CLOTHES && IsHalfBody())
        {
            SetAvatarTypeAndFetch(SHIRT);
            return;
        }

        string avatarType = item.type.ToString().ToLower();

        if (item.type == AccessoryTypes.EyeShape)
        {
            SetAvatarTypeAndFetch(EYE_SHAPE);
            return;
        }

        if (item.type == AccessoryTypes.BeardStyle || item.type == AccessoryTypes.EyeBrowStyle)
        {
            SetAvatarTypeAndFetch(avatarType);
            return;
        }

        SetAvatarTypeAndFetch(avatarType);
    }

    private void SetAvatarTypeAndFetch(string avatarType)
    {
        currentAvatarType = avatarType;
        requestedAvatarType = avatarType;
        APIHandler.Instance.ClearCachedAssets();
        APIHandler.Instance.FetchAssets();
    }

    private void DeselectAllColors()
    {
        foreach (var item in accessoryButtonList)
            item.Icon.color = deSelectedColor;
    }

    private void DeselectAllGenderIcons()
    {
        foreach (var item in genderButtonList)
            item.Icon.color = deSelectedColor;
    }

    private void DeSelectAllBodyPartIcons()
    {
        foreach (var item in bodyPartButtonList)
            item.Icon.color = deSelectedColor;
    }

    private void DeselectAllCategoryIcons()
    {
        foreach (var item in categoryButtonList)
            item.Icon.color = deSelectedColor;
    }

    private void CategoryButtonClick(CategoryButtonList item)
    {
        DeselectAllCategoryIcons();
        DisableAllPanels();
        ClearAssetUI();
        item.Icon.color = selectedColor;

        if (item.type != CategoryTypes.Face && item.type != CategoryTypes.HairStyle)
        {
            RightSidePanel.SetActive(false);
            ClearRightSideContent();
        }

        switch (item.type)
        {
            case CategoryTypes.Face:
                currentCategoryType = FACE;
                EnableFaceCategoryFeatures();
                break;
            case CategoryTypes.Clothes:
                currentCategoryType = CLOTHES;
                EnableClothesCategoryFeatures();
                break;
            case CategoryTypes.Gender:
                currentCategoryType = GENDER;
                EnableGenderFeatures();
                break;
            case CategoryTypes.Glasses:
                currentCategoryType = GLASSES;
                OnGlassesButtonClick();
                break;
            case CategoryTypes.FaceWear:
                currentCategoryType = FACE_WEAR;
                OnFaceWearButtonClick();
                break;
            case CategoryTypes.FaceMask:
                currentCategoryType = FACE_MASK;
                OnFaceMaskButtonClick();
                break;
            case CategoryTypes.HeadWear:
                currentCategoryType = HEAD_WEAR;
                OnHeadWearButtonClick();
                break;
            case CategoryTypes.HairStyle:
                currentCategoryType = HAIR_STYLE;
                OnHairStyleButtonClick();
                break;
            default:
                UnityEngine.Debug.Log("Category not handled.");
                break;
        }
    }

    private void SelectCategoryIcon(CategoryTypes type)
    {
        DeselectAllCategoryIcons();
        int index = categoryButtonList.FindIndex(b => b.type == type);
        if (index >= 0)
            categoryButtonList[index].Icon.color = selectedColor;
    }

    private void SelectAccessoryIcon(AccessoryTypes type)
    {
        DeselectAllColors();
        int index = accessoryButtonList.FindIndex(b => b.type == type);
        if (index >= 0)
            accessoryButtonList[index].Icon.color = selectedColor;
    }

    #endregion

    #region Save Flow

    public void OnSaveButtonClick()
    {
        SavePanel.SetActive(true);
        EditAvatarPanel.SetActive(false);
    }

    public void OnCancelButtonClick()
    {
        SavePanel.SetActive(false);
        EditAvatarPanel.SetActive(true);
    }

    public void OnSaveConfigButtonClick()
    {
        SaveLoadingPanel.SetActive(true);
        SaveTextPanel.SetActive(false);
        StartLoading();
        APIHandler.Instance.SaveConfig();
    }

    #endregion

    #region Loading Spinner

    public void StartLoading()
    {
        if (saveSpinner == null)
            return;

        saveSpinner.fillAmount = 0f;
        fillRoutine = StartCoroutine(FillLoop());
    }

    public void StopLoading()
    {
        if (fillRoutine != null)
            StopCoroutine(fillRoutine);

        fillRoutine = null;

        if (saveSpinner != null)
            saveSpinner.fillAmount = 0f;
    }

    private IEnumerator FillLoop()
    {
        while (true)
        {
            saveSpinner.fillAmount += Time.deltaTime * fillSpeed;
            if (saveSpinner.fillAmount >= 1f)
                saveSpinner.fillAmount = 0f;
            yield return null;
        }
    }

    #endregion

    #region Download And Category Actions

    public void ShowDownloadPanel()
    {
        SaveLoadingPanel.SetActive(false);
        SaveTextPanel.SetActive(true);
        SavePanel.SetActive(false);
        DownloadPanel.SetActive(true);
    }

    public void ShowCongraulationsPanel(string path)
    {
        // After download completes, close editing/auth panels and return to game panel
        DownloadPanel.SetActive(false);
        savedPathTMP.text = path;

        // Hide all UI panels related to editing/auth
        CongrualationsPanel.SetActive(false);
        EditAvatarPanel.SetActive(false);
        GetAuthTokenPanel.SetActive(false);
        SavePanel.SetActive(false);
        SaveLoadingPanel.SetActive(false);
        SaveTextPanel.SetActive(false);

        HalfBodyPanel.SetActive(false);
        GlassesBodyPanel.SetActive(false);
        ClothesPanel.SetActive(false);
        GenderPanel.SetActive(false);
        Facepanel.SetActive(false);
        RightSidePanel.SetActive(false);
        ClearRightSideContent();

        // Enable main game panel
        GamePanel.SetActive(true);
    }

    public void ShowFacePanelOnly()
    {
        GetAuthTokenPanel.SetActive(false);
        EditAvatarPanel.SetActive(false);
        SavePanel.SetActive(false);
        SaveLoadingPanel.SetActive(false);
        SaveTextPanel.SetActive(false);
        DownloadPanel.SetActive(false);
        CongrualationsPanel.SetActive(false);

        HalfBodyPanel.SetActive(false);
        GlassesBodyPanel.SetActive(false);
        ClothesPanel.SetActive(false);
        GenderPanel.SetActive(false);
        RightSidePanel.SetActive(false);
        ClearRightSideContent();

        Facepanel.SetActive(true);
        currentCategoryType = FACE;
        currentAvatarType = FACE_SHAPE;
        requestedAvatarType = currentAvatarType;

        SelectCategoryIcon(CategoryTypes.Face);

        APIHandler.Instance.ClearCachedAssets();
        ClearAssetUI();
        APIHandler.Instance.FetchAssets();
    }

    public void OnOkaybuttonClick()
    {
        CongrualationsPanel.SetActive(false);
        // ShowEditAvatarPanel();
        GamePanel.SetActive(true);
    }

    public void OnDownloadButtonClick()
    {
        APIHandler.Instance.DownloadGLB();
        GamePanel.SetActive(true);
    }

    public void HalfBodyButtonClick()
    {
        halfBodyIcon.color = iconSelectedColor;
        fullBodyIcon.color = deSelectedColor;
        currentAvatarBodyType = HALF;
        APIHandler.Instance.AddDataToConfig(BODY_TYPE_KEY, HALF);

        if (currentCategoryType == CLOTHES)
        {
            ClothesPanel.SetActive(false);
            HalfBodyPanel.SetActive(true);
            currentAvatarType = SHIRT;

            APIHandler.Instance.ClearCachedAssets();
            ClearAssetUI();
            APIHandler.Instance.FetchAssets();
        }
        else
        {
            HalfBodyPanel.SetActive(false);
        }
    }

    public void FullBodyButtonClick()
    {
        fullBodyIcon.color = iconSelectedColor;
        halfBodyIcon.color = deSelectedColor;
        currentAvatarBodyType = FULL;
        APIHandler.Instance.AddDataToConfig(BODY_TYPE_KEY, FULL);
        HalfBodyPanel.SetActive(false);

        if (currentCategoryType == CLOTHES)
        {
            ClothesPanel.SetActive(true);
            currentAvatarType = TOP;

            APIHandler.Instance.ClearCachedAssets();
            ClearAssetUI();
            APIHandler.Instance.FetchAssets();
        }
    }

    public void OnGlassesButtonClick()
    {
        HandleWearableCategorySelection(CategoryTypes.Glasses, GLASSES);
    }

    public void OnFaceWearButtonClick()
    {
        HandleWearableCategorySelection(CategoryTypes.FaceWear, FACE_WEAR);
    }

    public void OnFaceMaskButtonClick()
    {
        HandleWearableCategorySelection(CategoryTypes.FaceMask, FACE_MASK);
    }

    public void OnHeadWearButtonClick()
    {
        HandleWearableCategorySelection(CategoryTypes.HeadWear, HEAD_WEAR);
    }

    public void OnHairStyleButtonClick()
    {
        HandleWearableCategorySelection(CategoryTypes.HairStyle, HAIR_STYLE);
        EnableHairColorFeatures();
    }

    private void HandleWearableCategorySelection(CategoryTypes categoryType, string avatarType)
    {
        GlassesBodyPanel.SetActive(true);
        currentAvatarType = avatarType;
        DeselectAllColors();

        int index = categoryButtonList.FindIndex(b => b.type == categoryType);
        if (index != -1)
            categoryButtonList[index].Icon.color = selectedColor;

        APIHandler.Instance.ClearCachedAssets();
        APIHandler.Instance.FetchAssets();
    }

    public void EnableFaceCategoryFeatures()
    {
        Facepanel.SetActive(true);
        currentAvatarType = FACE_SHAPE;
        SelectAccessoryIcon(AccessoryTypes.Faceshape);
        APIHandler.Instance.ClearCachedAssets();
        APIHandler.Instance.FetchAssets();
    }

    public void EnableEyeBrowColorFeatures()
    {
        PopulateRightSideColorOptions(skinColorList, EYEBROW_COLOR_KEY, highlightFirstItem: true);
    }

    public void EnableEyeColorFeatures()
    {
        ClearRightSideContent();
        RightSidePanel.SetActive(true);

        if (APIHandler.Instance.EyeCachedAssets != null)
            ShowEyeColorAssetsData(APIHandler.Instance.EyeCachedAssets);
        else
            APIHandler.Instance.FetchEyeColorAssets();
    }

    public void EnableBeardColorFeatures()
    {
        PopulateRightSideColorOptions(colorList, BEARD_COLOR_KEY);
    }

    public void EnableFaceColorFeatures()
    {
        PopulateRightSideColorOptions(skinColorList, SKIN_COLOR_KEY);
    }

    public void EnableHairColorFeatures()
    {
        PopulateRightSideColorOptions(colorList, HAIR_COLOR_KEY);
    }

    private void PopulateRightSideColorOptions(
        List<string> colors,
        string configKey,
        bool highlightFirstItem = false
    )
    {
        RightSidePanel.SetActive(true);
        ClearRightSideContent();

        for (int i = 0; i < colors.Count; i++)
        {
            ItemInfo itemInfo = Instantiate(itemSmallCardInfo, rightSideContentTransform);
            itemInfo.SetColorInfo(colors[i], configKey, i.ToString());

            if (highlightFirstItem && i == 0)
                itemInfo.EnableHightlight(true);
        }
    }

    private void ClearRightSideContent()
    {
        ClearChildren(rightSideContentTransform);
    }

    public void EnableClothesCategoryFeatures()
    {
        bool isHalfBody = IsHalfBody();
        ClothesPanel.SetActive(!isHalfBody);
        HalfBodyPanel.SetActive(isHalfBody);

        currentAvatarType = isHalfBody ? SHIRT : TOP;
        DeselectAllColors();
        if (accessoryButtonList.Count > 0)
            accessoryButtonList[0].Icon.color = selectedColor;

        APIHandler.Instance.ClearCachedAssets();
        APIHandler.Instance.FetchAssets();
    }

    public void EnableGenderFeatures()
    {
        GenderPanel.SetActive(true);
        DeselectAllGenderIcons();
        DeSelectAllBodyPartIcons();

        if (string.IsNullOrEmpty(currentGenderType))
            currentGenderType = GenderType.Male.ToString().ToLower();
        if (string.IsNullOrEmpty(currentBodyPartType))
            currentBodyPartType = BodyTypes.Athletic.ToString().ToLower();

        int genderIndex = genderButtonList.FindIndex(
            b => b.type.ToString().Equals(currentGenderType, StringComparison.OrdinalIgnoreCase)
        );
        if (genderIndex < 0 && genderButtonList.Count > 0)
            genderIndex = 0;
        if (genderIndex >= 0)
            genderButtonList[genderIndex].Icon.color = selectedColor;

        int bodyIndex = bodyPartButtonList.FindIndex(
            b => b.type.ToString().Equals(currentBodyPartType, StringComparison.OrdinalIgnoreCase)
        );
        if (bodyIndex < 0 && bodyPartButtonList.Count > 0)
            bodyIndex = 0;
        if (bodyIndex >= 0)
            bodyPartButtonList[bodyIndex].Icon.color = selectedColor;

        APIHandler.Instance.ClearCachedAssets();
    }

    public void OnGenderItemButtonClick(GenderButtonList item)
    {
        DeselectAllGenderIcons();
        DeSelectAllBodyPartIcons();
        item.Icon.color = selectedColor;
        currentGenderType = item.type.ToString().ToLower();

        int bodyIndex = bodyPartButtonList.FindIndex(
            b => b.type.ToString().Equals(currentBodyPartType, StringComparison.OrdinalIgnoreCase)
        );
        if (bodyIndex < 0 && bodyPartButtonList.Count > 0)
            bodyIndex = 0;
        if (bodyIndex >= 0)
        {
            bodyPartButtonList[bodyIndex].Icon.color = selectedColor;
            currentBodyPartType = bodyPartButtonList[bodyIndex].type.ToString().ToLower();
        }

        currentAvatarType = string.Empty;
        APIHandler.Instance.ClearCachedAssets();
        APIHandler.Instance.SetConfig(currentGenderType);

        if (!string.IsNullOrEmpty(currentAvatarBodyType))
            APIHandler.Instance.AddDataToConfig(BODY_TYPE_KEY, currentAvatarBodyType);

        if (Enum.TryParse(currentBodyPartType, true, out BodyTypes parsedBodyType))
            APIHandler.Instance.AddDataToConfig(BODY_SHAPE_KEY, parsedBodyType.ToString());
        else
            APIHandler.Instance.LoadAvatar();

        if (currentCategoryType == CLOTHES)
            EnableClothesCategoryFeatures();
    }

    public void OnBodyPartItemButtonClick(BodyPartButtonList item)
    {
        DeSelectAllBodyPartIcons();
        item.Icon.color = selectedColor;
        currentBodyPartType = item.type.ToString().ToLower();
        APIHandler.Instance.AddDataToConfig(BODY_SHAPE_KEY, item.type.ToString());
    }

    private void DisableAllPanels()
    {
        HalfBodyPanel.SetActive(false);
        GlassesBodyPanel.SetActive(false);
        ClothesPanel.SetActive(false);
        GenderPanel.SetActive(false);
        Facepanel.SetActive(false);
    }

    private void EnsureDefaultFaceCategoryLoaded()
    {
        if (!APIHandler.Instance.HasValidToken())
            return;

        currentCategoryType = FACE;
        requestedAvatarType = FACE_SHAPE;
        SelectCategoryIcon(CategoryTypes.Face);
        EnableFaceCategoryFeatures();
    }

    #endregion
}
