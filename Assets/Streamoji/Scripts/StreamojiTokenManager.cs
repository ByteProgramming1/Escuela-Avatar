using System;
using UnityEngine;

public static class StreamojiTokenManager
{
    private const string TOKEN_KEY = "STREAMOJI_AUTH_TOKEN";
    private const string EXPIRY_KEY = "STREAMOJI_AUTH_TOKEN_EXPIRY";

    // Token lifetime = 30 minutes
    private const int TOKEN_VALID_MINUTES = 30;

    public static bool HasValidToken()
    {
        if (!PlayerPrefs.HasKey(TOKEN_KEY) || !PlayerPrefs.HasKey(EXPIRY_KEY))
            return false;

        long expiryTicks = Convert.ToInt64(PlayerPrefs.GetString(EXPIRY_KEY));
        DateTime expiryTime = new DateTime(expiryTicks, DateTimeKind.Utc);

        return DateTime.UtcNow < expiryTime;
    }

    public static string GetToken()
    {
        return PlayerPrefs.GetString(TOKEN_KEY, "");
    }

    public static void SaveToken(string token)
    {
        DateTime expiryTime = DateTime.UtcNow.AddMinutes(TOKEN_VALID_MINUTES);

        PlayerPrefs.SetString(TOKEN_KEY, token);
        PlayerPrefs.SetString(EXPIRY_KEY, expiryTime.Ticks.ToString());
        PlayerPrefs.Save();

        Debug.Log(" Streamoji token saved. Expires at: " + expiryTime);
    }

    public static void ClearToken()
    {
        PlayerPrefs.DeleteKey(TOKEN_KEY);
        PlayerPrefs.DeleteKey(EXPIRY_KEY);
    }
}
