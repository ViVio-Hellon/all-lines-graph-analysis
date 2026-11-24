' ===================================================================
'  全ライン グラフ分析  起動(コンソールを出さない)
'  起動しないときは start.bat を使うと理由が表示されます。
'  --- keep this file in CP932 (Shift-JIS) with CRLF line endings ---
' ===================================================================
Option Explicit
Const APP_NAME = "全ライン グラフ分析"
Dim shell, fso, here, script
Set shell = CreateObject("WScript.Shell")
Set fso = CreateObject("Scripting.FileSystemObject")
here = fso.GetParentFolderName(WScript.ScriptFullName)
script = fso.BuildPath(here, "start_app.py")
If Not fso.FileExists(script) Then
    MsgBox "start_app.py が見つかりません。" & vbCrLf & script, vbCritical, APP_NAME
    WScript.Quit 1
End If
If shell.Run("cmd /c pythonw --version", 0, True) <> 0 Then
    MsgBox "pythonw が見つかりません。start.bat から起動してください。", vbCritical, APP_NAME
    WScript.Quit 1
End If
shell.CurrentDirectory = here
shell.Run "pythonw """ & script & """", 0, False
