#ifndef AppVersion
  #error AppVersion must be set by scripts/build_windows.ps1
#endif

[Setup]
AppId={{E537F8EE-03FE-428C-B1AB-45769C584EC8}
AppName=IR Setup Helper
AppVersion={#AppVersion}
AppPublisher=Xiaoyang Su
AppPublisherURL=https://github.com/XiaoyangSu-Sam/ir_setup_helper
DefaultDirName={localappdata}\Programs\IRSetupHelper
DefaultGroupName=IR Setup Helper
PrivilegesRequired=lowest
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
UninstallDisplayIcon={app}\IRSetupHelper.exe
DisableProgramGroupPage=yes
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
OutputDir=..\dist
OutputBaseFilename=IRSetupHelper-{#AppVersion}-windows-x64-setup

[Files]
Source: "..\build\windows\IRSetupHelper\*"; DestDir: "{app}"; Flags: recursesubdirs createallsubdirs ignoreversion
Source: "..\LICENSE"; DestDir: "{app}"; Flags: ignoreversion

[Icons]
Name: "{group}\IR Setup Helper"; Filename: "{app}\IRSetupHelper.exe"; WorkingDir: "{app}"
Name: "{group}\Stop IR Setup Helper"; Filename: "{app}\IRSetupHelper.exe"; Parameters: "--stop"; WorkingDir: "{app}"
Name: "{userdesktop}\IR Setup Helper"; Filename: "{app}\IRSetupHelper.exe"; WorkingDir: "{app}"; Tasks: desktopicon

[Tasks]
Name: "desktopicon"; Description: "Create a desktop shortcut"; Flags: unchecked

[Run]
Filename: "{app}\IRSetupHelper.exe"; Description: "Launch IR Setup Helper"; Flags: nowait postinstall skipifsilent

[UninstallRun]
Filename: "{app}\IRSetupHelper.exe"; Parameters: "--stop-and-wait"; Flags: waituntilterminated skipifdoesntexist; RunOnceId: "StopIRSetupHelper"

[Code]
function PrepareToInstall(var NeedsRestart: Boolean): String;
var
  Launcher: String;
  ExitCode: Integer;
begin
  Result := '';
  Launcher := ExpandConstant('{app}\IRSetupHelper.exe');
  if FileExists(Launcher) then
    if not Exec(Launcher, '--stop-and-wait', '', SW_HIDE, ewWaitUntilTerminated, ExitCode) or (ExitCode <> 0) then
      Result := 'Close IR Setup Helper from the Start menu before retrying the installation.';
end;
