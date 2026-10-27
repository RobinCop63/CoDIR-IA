' CoDIR IA v16.5.76 - build v17.4.3.62.13.9.4.65-M6B-B1.3.62.13.9.4.65 - Launcher Windows
Dim installDir, venvPath, streamlit, cmd, shell

If WScript.Arguments.Count >= 1 Then
    installDir = WScript.Arguments(0)
Else
    Dim fso1
    Set fso1 = CreateObject("Scripting.FileSystemObject")
    installDir = fso1.GetParentFolderName(fso1.GetParentFolderName(WScript.ScriptFullName))
End If

If WScript.Arguments.Count >= 2 Then
    venvPath = WScript.Arguments(1)
Else
    Dim fso2
    Set fso2 = CreateObject("Scripting.FileSystemObject")
    Dim venvFile
    venvFile = installDir & "\outputs\venv_path.txt"
    If fso2.FileExists(venvFile) Then
        Dim ts
        Set ts = fso2.OpenTextFile(venvFile, 1)
        venvPath = Trim(ts.ReadLine())
        ts.Close
    Else
        venvPath = CreateObject("WScript.Shell").ExpandEnvironmentStrings("%LOCALAPPDATA%") & "\CoDIR-IA\.venv"
    End If
End If

streamlit = venvPath & "\Scripts\streamlit.exe"
cmd = Chr(34) & streamlit & Chr(34) & " run " & Chr(34) & installDir & "\app.py" & Chr(34) & " --server.headless false --browser.gatherUsageStats false --server.port 8501 --logger.level error"

Set shell = CreateObject("WScript.Shell")
' M6-A2.2.1 - force le moteur de parsing 'thread' (neutralise un eventuel
' CODIR_PARSE_ENGINE=process herite de l'environnement, source de warning).
shell.Environment("Process")("CODIR_PARSE_ENGINE") = "thread"
shell.Run "cmd /c cd /d " & Chr(34) & installDir & Chr(34) & " && " & cmd, 0, False
