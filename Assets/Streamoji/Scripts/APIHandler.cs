using System;
using System.Collections;
using System.IO;
using System.Reflection;
using System.Text;
using System.Threading.Tasks;
using UnityEngine;
using UnityEngine.Networking;
using static Components;

public class APIHandler : MonoBehaviour
{
    public static APIHandler Instance;

    [Header("References")]
    public AvatarLoader loader;

    #region URLs

    private const string AUTH_URL =
        "https://us-central1-streamoji-265f4.cloudfunctions.net/getAuthToken";

    private const string PROCESS_URL = "https://glb.streamoji.com/api/process";

    private const string SAVE_AVATAR_URL =
        "https://us-central1-streamoji-265f4.cloudfunctions.net/saveAvatarConfig";

    private string ASSET_BASE_URL = string.Empty;
    private string GET_ASSETS_URL =
        "https://glb.streamoji.com/api/assets?limit=100&page=1&filter=viewable-by-user-and-app&gender=neutral";

    #endregion

    #region Token

    public const string TOKEN_KEY = "STREAMOJI_AUTH_TOKEN";
    private const string TOKEN_TIME_KEY = "STREAMOJI_AUTH_TIME";
    private const int TOKEN_VALID_MINUTES = 30;

    #endregion

    #region Runtime Cache

    private AssetsRootData cachedAssets;

    public AssetsRootData CachedAssets
    {
        get => cachedAssets;
        set => cachedAssets = value;
    }

    private AssetsRootData eyeCachedAssets;

    public AssetsRootData EyeCachedAssets
    {
        get => eyeCachedAssets;
        set => eyeCachedAssets = value;
    }


    #endregion
    [Header("Avatar Confign Debugging")]
    [SerializeField] private Config config;
    private Config defaultConfig = new Config();
    private string avatarId;

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

    #endregion

    #region Auth Token

    public void OnGetAuthToken(string clientId, string clientSecret)
    {
        StartCoroutine(RequestAuthToken(clientId, clientSecret));
    }

    public bool HasValidToken()
    {
        if (!PlayerPrefs.HasKey(TOKEN_KEY) || !PlayerPrefs.HasKey(TOKEN_TIME_KEY))
            return false;

        long ticks = Convert.ToInt64(PlayerPrefs.GetString(TOKEN_TIME_KEY));
        DateTime savedTime = new DateTime(ticks, DateTimeKind.Utc);

        return DateTime.UtcNow < savedTime.AddMinutes(TOKEN_VALID_MINUTES);
    }

    private IEnumerator RequestAuthToken(string clientId, string clientSecret)
    {
        var body = new AuthRequestBody { userId = "user_789", userName = "John Doe" };

        byte[] bodyRaw = Encoding.UTF8.GetBytes(JsonUtility.ToJson(body));

        using (UnityWebRequest request = new UnityWebRequest(AUTH_URL, "POST"))
        {
            request.uploadHandler = new UploadHandlerRaw(bodyRaw);
            request.downloadHandler = new DownloadHandlerBuffer();

            request.SetRequestHeader("Content-Type", "application/json");
            request.SetRequestHeader("Client-Id", clientId);
            request.SetRequestHeader("Client-Secret", clientSecret);

            yield return request.SendWebRequest();

            if (request.result != UnityWebRequest.Result.Success)
            {
                Debug.LogError("Auth error: " + request.error);
                yield break;
            }

            AuthResponse response = JsonUtility.FromJson<AuthResponse>(
                request.downloadHandler.text
            );

            if (!response.success)
            {
                Debug.LogError("Token generation failed");
                yield break;
            }

            SaveToken(response.authToken);
            UIHandler.Instance.OnAuthTokenSuccess();
        }
    }

    private void SaveToken(string token)
    {
        PlayerPrefs.SetString(TOKEN_KEY, token);
        PlayerPrefs.SetString(TOKEN_TIME_KEY, DateTime.UtcNow.Ticks.ToString());
        PlayerPrefs.Save();
    }

    #endregion

    #region Assets
    public void FetchAssets()
    {
        Debug.Log("Fetching assets...");
        Debug.Log("Current Avatar Type: " + UIHandler.Instance.CurrentAvatarType);
        ASSET_BASE_URL = GET_ASSETS_URL + "&gender=" + UIHandler.Instance.CurrentGenderType.ToLower() + "&type=" + UIHandler.Instance.CurrentAvatarType.ToLower();
        Debug.Log("Fetching assets from URL: " + ASSET_BASE_URL);
        if (cachedAssets != null)
        {
            Debug.Log("Using cached assets");
            UIHandler.Instance.ShowAssetsData(cachedAssets);
            return;
        }

        if (!HasValidToken())
        {
            Debug.LogError("No valid token. Cannot fetch assets.");
            UIHandler.Instance.ShowGetAuthTokenPanel();
            return;
        }

        StartCoroutine(FetchAssetsCoroutine(PlayerPrefs.GetString(TOKEN_KEY)));
    }

    public void FetchEyeColorAssets(bool showUI = true)
    {
        Debug.Log("Fetching EyeCOLor assets...");
        ASSET_BASE_URL = GET_ASSETS_URL + "&gender=" + UIHandler.Instance.CurrentGenderType.ToLower() + "&type=" + "eyecolor";
        Debug.Log("Fetching assets from URL: " + ASSET_BASE_URL);
        Debug.Log("eyecached assetrs is null : " + (eyeCachedAssets == null));
        if (eyeCachedAssets != null)
        {
            Debug.Log("Using cached assets");
            if (showUI)
                UIHandler.Instance.ShowEyeColorAssetsData(eyeCachedAssets);
            return;
        }

        if (!HasValidToken())
        {
            Debug.LogError("No valid token. Cannot fetch assets.");
            UIHandler.Instance.ShowGetAuthTokenPanel();
            return;
        }

        StartCoroutine(FetchEyeColorAssetsCoroutine(PlayerPrefs.GetString(TOKEN_KEY), showUI));
    }

    public void ClearCachedAssets()
    {
        cachedAssets = null;
        Debug.Log("Cached assets cleared");
    }


    private IEnumerator FetchAssetsCoroutine(string authToken)
    {
        UnityWebRequest request = UnityWebRequest.Get(ASSET_BASE_URL);
        request.SetRequestHeader("Authorization", $"Bearer {authToken}");
        request.SetRequestHeader("Content-Type", "application/json");

        yield return request.SendWebRequest();

        if (request.result != UnityWebRequest.Result.Success)
        {
            Debug.LogError("Fetch Assets Error: " + request.error);
            yield break;
        }

        Debug.Log("Fetch Assets Response: " + request.downloadHandler.text);
        cachedAssets = JsonUtility.FromJson<AssetsRootData>(request.downloadHandler.text);

        Debug.Log("Assets cached in memory");
        UIHandler.Instance.ShowAssetsData(cachedAssets);
    }

    private IEnumerator FetchEyeColorAssetsCoroutine(string authToken, bool showUI)
    {
        UnityWebRequest request = UnityWebRequest.Get(ASSET_BASE_URL);
        request.SetRequestHeader("Authorization", $"Bearer {authToken}");
        request.SetRequestHeader("Content-Type", "application/json");

        yield return request.SendWebRequest();

        if (request.result != UnityWebRequest.Result.Success)
        {
            Debug.LogError("Fetch Assets Error: " + request.error);
            yield break;
        }

        Debug.Log("Fetch Assets Response: " + request.downloadHandler.text);
        eyeCachedAssets = JsonUtility.FromJson<AssetsRootData>(request.downloadHandler.text);

        Debug.Log("Assets cached in memory");
        if (showUI)
            UIHandler.Instance.ShowEyeColorAssetsData(eyeCachedAssets);
    }

    #endregion

    #region Avatar Config

    public void SetConfig(string genderType)
    {
        if (genderType == GenderType.Female.ToString().ToLower())
        {
            // FEMALE DEFAULT CONFIG
            defaultConfig = new Config
            {
                gender = "female",
                faceShape = "50094438",
                eyeShape = "49919161",
                noseShape = "49918764",
                lipShape = "50094598",
                hairStyle = "40524678",
                eyebrowStyle = "9247423",
                outfit = "75228028",
                bodyType = "Full",
                bodyShape = "average",
                skinColor = "0",
                eyeColor = "9781796",
                hairColor = "4",
                eyebrowColor = "0"
            };
        }
        else if (genderType == GenderType.Male.ToString().ToLower())
        {
            // MALE DEFAULT CONFIG (your existing one)
            defaultConfig = new Config
            {
                gender = "male",
                faceShape = "49918702",
                eyeShape = "49919164",
                noseShape = "49918836",
                lipShape = "50094598",
                hairStyle = "49597582",
                hairColor = "2",
                skinColor = "0",
                bodyType = "Full",
                bodyShape = "average",
                outfit = "77095355",
                eyebrowColor = "0"
            };
        }

        config = CloneConfig(defaultConfig);
    }

    private Config CloneConfig(Config source)
    {
        return new Config
        {
            gender = source.gender,
            faceShape = source.faceShape,
            eyeShape = source.eyeShape,
            noseShape = source.noseShape,
            lipShape = source.lipShape,
            hairStyle = source.hairStyle,
            eyebrowStyle = source.eyebrowStyle,
            outfit = source.outfit,
            bodyType = source.bodyType,
            bodyShape = source.bodyShape,
            skinColor = source.skinColor,
            eyeColor = source.eyeColor,
            hairColor = source.hairColor,
            eyebrowColor = source.eyebrowColor
        };
    }


    public void AddDataToConfig(string type, string value)
    {
        if (config == null)
            SetConfig(UIHandler.Instance.CurrentGenderType);

        string normalizedType = type.ToLower();

        bool isClothingPartUpdate =
            normalizedType == "top" ||
            normalizedType == "bottom" ||
            normalizedType == "footwear";

        // ================= BODY TYPE (SPECIAL CASE) =================
        if (normalizedType == "bodytype")
        {
            config.bodyType = value;

            if (value.Equals("Half", StringComparison.OrdinalIgnoreCase))
            {
                config.outfit = string.Empty;
                config.top = string.Empty;
                config.bottom = string.Empty;
                config.footwear = string.Empty;
            }
            else if (value.Equals("Full", StringComparison.OrdinalIgnoreCase))
            {
                if (string.IsNullOrEmpty(config.outfit))
                    config.outfit = defaultConfig.outfit;
            }

            LoadAvatar();
            return;
        }

        // ================= CLOTHING PARTS 
        if (isClothingPartUpdate)
        {
            // Selecting individual parts disables outfit
            config.outfit = string.Empty;
        }

        // ================= GENERIC FIELD REPLACEMENT =================
        FieldInfo field = typeof(Config).GetField(
            type,
            BindingFlags.Public | BindingFlags.Instance | BindingFlags.IgnoreCase
        );

        if (field == null)
        {
            Debug.LogWarning($"Config field not found: {type}");
            return;
        }

        // THIS LINE HANDLES bodyShape AND ALL OTHERS
        field.SetValue(config, value);
        Debug.Log($"Config updated: {type} = {value}");

        // ================= FULL BODY SAFETY =================
        if (!isClothingPartUpdate &&
            config.bodyType.Equals("Full", StringComparison.OrdinalIgnoreCase))
        {
            bool partsEmpty =
                string.IsNullOrEmpty(config.top) &&
                string.IsNullOrEmpty(config.bottom) &&
                string.IsNullOrEmpty(config.footwear);

            if (partsEmpty && string.IsNullOrEmpty(config.outfit))
            {
                config.outfit = defaultConfig.outfit;
            }
        }

        LoadAvatar();
    }

    #endregion

    #region Avatar Generation

    public void LoadAvatar()
    {
        if (!HasValidToken())
        {
            Debug.LogError("No valid token. Cannot load avatar.");
            UIHandler.Instance.ShowGetAuthTokenPanel();
            return;
        }

        loader.GenerateAvatar(PlayerPrefs.GetString(TOKEN_KEY), config);
    }

    public async void SaveConfig()
    {
        if (!HasValidToken())
        {
            UIHandler.Instance.ShowGetAuthTokenPanel();
            return;
        }

        avatarId = await SaveAvatar(PlayerPrefs.GetString(TOKEN_KEY), config);

        Debug.Log("AvatarId : " + avatarId);
        UIHandler.Instance.StopLoading();
        UIHandler.Instance.ShowDownloadPanel();
    }

    public async void DownloadGLB()
    {
        if (!HasValidToken())
        {
            UIHandler.Instance.ShowGetAuthTokenPanel();
            return;
        }

        if (string.IsNullOrEmpty(avatarId))
        {
            Debug.LogError("AvatarId is empty. Save the avatar before downloading.");
            return;
        }

        string bodyType = config?.bodyType ?? UIHandler.Instance.CurrentAvatarBodyType ?? "Full";

        loader.GenerateAvatarFromId(PlayerPrefs.GetString(TOKEN_KEY), avatarId, bodyType, false);
        UIHandler.Instance.ShowFacePanelOnly();
    }

    #endregion

    #region Network Calls

    public static async Task<string> SaveAvatar(string authToken, Config avatarConfig)
    {
        SaveAvatarRequest body = new SaveAvatarRequest
        {
            data = new AvatarData { avatarConfig = avatarConfig },
        };

        byte[] bodyRaw = Encoding.UTF8.GetBytes(JsonUtility.ToJson(body));

        using (UnityWebRequest request = new UnityWebRequest(SAVE_AVATAR_URL, "POST"))
        {
            request.uploadHandler = new UploadHandlerRaw(bodyRaw);
            request.downloadHandler = new DownloadHandlerBuffer();

            request.SetRequestHeader("Content-Type", "application/json");
            request.SetRequestHeader("Authorization", $"Bearer {authToken}");
            request.SetRequestHeader("origin", "https://avatars.streamoji.com");

            var op = request.SendWebRequest();
            while (!op.isDone)
                await Task.Yield();

            if (request.result != UnityWebRequest.Result.Success)
            {
                Debug.LogError("SaveAvatar failed: " + request.error);
                return null;
            }

            SaveAvatarResponse response = JsonUtility.FromJson<SaveAvatarResponse>(
                request.downloadHandler.text
            );

            return response.data.avatarId;
        }
    }

    public static async Task<string> DownloadAvatar(string avatarId, string authToken)
    {
        string url = $"{PROCESS_URL}?avatarId={avatarId}";
        string path = Path.Combine(Application.persistentDataPath, $"avatar-{avatarId}.glb");

        using (UnityWebRequest request = new UnityWebRequest(url, "POST"))
        {
            request.uploadHandler = new UploadHandlerRaw(Array.Empty<byte>());
            request.downloadHandler = new DownloadHandlerFile(path);

            request.SetRequestHeader("Accept", "application/octet-stream");
            request.SetRequestHeader("Authorization", $"Bearer {authToken}");
            request.SetRequestHeader("User-Agent", "UnityWebRequest");

            var op = request.SendWebRequest();
            while (!op.isDone)
                await Task.Yield();

            if (request.result != UnityWebRequest.Result.Success)
            {
                Debug.LogError("Avatar download failed: " + request.error);
                return null;
            }

            return path;
        }
    }

    #endregion
}
