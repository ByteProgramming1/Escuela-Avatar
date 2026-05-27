using System;
using System.Collections.Generic;
using UnityEngine;

public class Components
{
    [System.Serializable]
    public class AssetData
    {
        public string _id;
        public string id;
        public string badgeLogoUrl;
        public string badgeText;
        public string baseColorUrl;
        public string beardStyle;
        public string bodyType;
        public DateTime createdAt;
        public bool editable;
        public string eyeStyle;
        public string eyebrowStyle;
        public List<object> faceBlendShapes;
        public string gender;
        public string glassesStyle;
        public string hairStyle;
        public bool hasApps;
        public bool iconGlow;
        public string iconText;
        public string iconUrl;
        public bool isTemplate;
        public bool locked;
        public List<object> lockedCategories;
        public string maskUrl;
        public string name;
        public string occlusionUrl;
        public string organizationId;
        public string psdTemplateUrl;
        public bool removeSkin;
        public string type;
        public DateTime updatedAt;
        public List<object> campaignIds;
    }

    [System.Serializable]
    public class Pagination
    {
        public int total;
        public int limit;
        public int page;
        public int pages;
    }

    [System.Serializable]
    public class AssetsRootData
    {
        public List<AssetData> data;
        public Pagination pagination;
    }

    [System.Serializable]
    public enum AccessoryTypes
    {
        None,
        Top,
        Bottom,
        Footwear,
        Outfit,
        Glasses,
        Faceshape,
        EyeBrowStyle,
        EyeShape,
        LipShape,
        NoseShape,
        BeardStyle
    }

    [System.Serializable]
    public enum CategoryTypes
    {
        Gender,
        Face,
        HairStyle,
        Clothes,
        Glasses,
        FaceMask,
        FaceWear,
        HeadWear
    }

    [System.Serializable]
    public enum GenderType
    {
        Male,
        Female
    }

    [System.Serializable]
    public enum BodyTypes
    {
        Average,
        Athletic,

        HeavySet,

        PlusSize

    }
    [Serializable]
    public class AccessoryButtonList
    {
        public AccessoryTypes type;
        public UnityEngine.UI.Button button;
        public UnityEngine.UI.Image Icon;
    }


    [Serializable]
    public class CategoryButtonList
    {
        public CategoryTypes type;
        public UnityEngine.UI.Button button;
        public UnityEngine.UI.Image Icon;
    }

    [Serializable]
    public class BodyPartButtonList
    {
        public BodyTypes type;
        public UnityEngine.UI.Button button;
        public UnityEngine.UI.Image Icon;
    }

    [Serializable]
    public class GenderButtonList
    {
        public GenderType type;
        public UnityEngine.UI.Button button;
        public UnityEngine.UI.Image Icon;
    }

    [Serializable]
    public enum BodyType
    {
        Full,
        Half
    }

    [System.Serializable]
    public class Config
    {
        public string gender;
        public string faceShape;
        public string eyeShape;
        public string noseShape;
        public string lipShape;
        public string hairStyle;
        public string hairColor;
        public string skinColor;
        public string bodyType;
        public string bodyShape;
        public string eyebrowColor;
        public string outfit;
        public string top;
        public string bottom;
        public string footwear;
        public string shirt;
        public string eyebrowStyle;
        public string eyeColor;
        public string beardStyle;
        public string glasses;
        public string headwear;
        public string beardColor;
        public string faceWear;
        public string faceMask;
    }

    [Serializable]
    public class OptionsWrapper
    {
        public DataWrapper data;
    }

    [Serializable]
    public class DataWrapper
    {
        public Config assets;
    }

    #region Models

    [Serializable]
    public class AuthRequestBody
    {
        public string userId;
        public string userName;
    }

    [Serializable]
    public class AuthResponse
    {
        public bool success;
        public string authToken;
    }

    [Serializable]
    public class SaveAvatarRequest
    {
        public AvatarData data;
    }

    [Serializable]
    public class AvatarData
    {
        public Config avatarConfig;
    }

    [System.Serializable]
    public class SaveAvatarResponse
    {
        public ResponseData data;
    }

    [Serializable]
    public class ResponseData
    {
        public string avatarId;
    }

    #endregion
}
