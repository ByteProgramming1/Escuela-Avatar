using UnityEngine;
using GLTFast.Logging;

public class UnityGltfLogger : ICodeLogger
{
    public void Error(LogCode code, params string[] messages)
    {
        Debug.LogError(Format(code, messages));
    }

    public void Error(string message)
    {
        Debug.LogError(message);
    }

    public void Warning(LogCode code, params string[] messages)
    {
        Debug.LogWarning(Format(code, messages));
    }

    public void Warning(string message)
    {
        Debug.LogWarning(message);
    }

    public void Info(LogCode code, params string[] messages)
    {
        Debug.Log(Format(code, messages));
    }

    public void Info(string message)
    {
        Debug.Log(message);
    }

    public void Log(LogType logType, LogCode code, params string[] messages)
    {
        string msg = Format(code, messages);

        switch (logType)
        {
            case LogType.Error:
            case LogType.Exception:
                Debug.LogError(msg);
                break;
            case LogType.Warning:
                Debug.LogWarning(msg);
                break;
            default:
                Debug.Log(msg);
                break;
        }
    }

    private string Format(LogCode code, params string[] messages)
    {
        return $"[glTFast:{code}] {string.Join(" ", messages)}";
    }
}
