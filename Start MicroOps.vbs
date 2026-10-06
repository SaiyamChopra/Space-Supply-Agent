Option Explicit

Dim shell, files, projectDir, command, exitCode
Set shell = CreateObject("WScript.Shell")
Set files = CreateObject("Scripting.FileSystemObject")
projectDir = files.GetParentFolderName(WScript.ScriptFullName)
command = "cmd.exe /d /c call """ & projectDir & "\Start MicroOps.bat"" --hidden"
exitCode = shell.Run(command, 0, True)

If exitCode <> 0 Then
    MsgBox "MicroOps could not start. Confirm Python 3.11 x64 is installed and the offline_packages folder is beside the launcher.", vbExclamation, "MicroOps startup"
End If
