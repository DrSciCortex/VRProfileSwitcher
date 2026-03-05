; VRProfileSwitcher — Inno Setup installer script
; ================================================
; Prerequisites:
;   1. Run build.py first to produce dist\VRProfileSwitcher\
;   2. Place this file in the project root (alongside build.py)
;   3. Install Inno Setup 6.x  (https://jrsoftware.org/isinfo.php)
;   4. Compile:  iscc VRProfileSwitcher.iss
;      or open in the Inno Setup IDE and press F9
;
; Output: installer_output\VRProfileSwitcher-1.0.0-Setup.exe

#define AppName      "VRProfile Switcher"
#define AppVersion   "1.0.0"
#define AppPublisher "VRProfile"
#define AppExeName   "VRProfileSwitcher.exe"
#define AppId        "{{A3F2C8E1-4D7B-4A9C-B2F1-8E3D5C6A7B9D}"

[Setup]
AppId={#AppId}
AppName={#AppName}
AppVersion={#AppVersion}
AppPublisher={#AppPublisher}
AppVerName={#AppName} {#AppVersion}

; Per-user install — no UAC elevation needed
PrivilegesRequired=lowest
DefaultDirName={localappdata}\VRProfileSwitcher
DefaultGroupName={#AppName}
DisableProgramGroupPage=yes

; Output
OutputDir=installer_output
OutputBaseFilename=VRProfileSwitcher-{#AppVersion}-Setup
SetupIconFile=assets\icon.ico
UninstallDisplayIcon={app}\{#AppExeName}

; Wizard icon shown on the welcome/finish pages
WizardSmallImageFile=assets\icon_64.ico

; Compression
Compression=lzma2/ultra64
SolidCompression=yes
LZMAUseSeparateProcess=yes

; Appearance
WizardStyle=modern
WizardSizePercent=120
DisableWelcomePage=no
DisableDirPage=no
DisableReadyPage=no

; Close running instances before installing
CloseApplications=yes
CloseApplicationsFilter=*.exe
RestartApplications=no

; Windows 10 minimum
MinVersion=10.0

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon";  Description: "Create a &desktop shortcut";            GroupDescription: "Additional shortcuts:"; Flags: unchecked
Name: "startupentry"; Description: "Launch VRProfile Switcher at &startup"; GroupDescription: "Windows startup:";      Flags: unchecked

[Files]
; Everything PyInstaller produced in dist\VRProfileSwitcher\
Source: "dist\VRProfileSwitcher\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Dirs]
; Pre-create data\ so the app can write its log on very first launch
Name: "{app}\data"

[Icons]
Name: "{autoprograms}\{#AppName}"; Filename: "{app}\{#AppExeName}"; IconFilename: "{app}\assets\icon.ico"
Name: "{autodesktop}\{#AppName}";  Filename: "{app}\{#AppExeName}"; IconFilename: "{app}\assets\icon.ico"; Tasks: desktopicon

[Registry]
; Optional startup entry
Root: HKCU; Subkey: "Software\Microsoft\Windows\CurrentVersion\Run"; \
  ValueType: string; ValueName: "{#AppName}"; \
  ValueData: """{app}\{#AppExeName}"""; \
  Flags: uninsdeletevalue; Tasks: startupentry

[Run]
Filename: "{app}\{#AppExeName}"; \
  Description: "Launch {#AppName}"; \
  Flags: nowait postinstall skipifsilent

[UninstallRun]
Filename: "taskkill.exe"; Parameters: "/F /IM {#AppExeName}"; \
  Flags: runhidden skipifdoesntexist; RunOnceId: "KillApp"

[UninstallDelete]
; Remove app files but leave data\ for the Pascal prompt below
Type: filesandordirs; Name: "{app}\*"; Excludes: "data\*"

[Code]
{ Ask whether to delete user data (profiles, config, logs) on uninstall }
procedure CurUninstallStepChanged(CurUninstallStep: TUninstallStep);
var
  DataDir: String;
  Answer: Integer;
begin
  if CurUninstallStep = usPostUninstall then
  begin
    DataDir := ExpandConstant('{app}\data');
    if DirExists(DataDir) then
    begin
      Answer := MsgBox(
        'Do you want to delete your VRProfile data?' + #13#10 + #13#10 +
        'This includes all profiles, configuration, and logs stored in:' + #13#10 +
        DataDir + #13#10 + #13#10 +
        'Click Yes to delete everything, No to keep your data.',
        mbConfirmation, MB_YESNO or MB_DEFBUTTON2
      );
      if Answer = IDYES then
        DelTree(DataDir, True, True, True);
    end;
    RemoveDir(ExpandConstant('{app}'));
  end;
end;

{ Prevent downgrade installs }
function InitializeSetup(): Boolean;
var
  InstalledVersion: String;
begin
  Result := True;
  if RegQueryStringValue(HKCU,
    'Software\Microsoft\Windows\CurrentVersion\Uninstall\{#AppId}_is1',
    'DisplayVersion', InstalledVersion) then
  begin
    if CompareStr(InstalledVersion, '{#AppVersion}') > 0 then
    begin
      MsgBox(
        'A newer version (' + InstalledVersion + ') of {#AppName} is already installed.' +
        #13#10 + 'Setup will now exit.',
        mbError, MB_OK
      );
      Result := False;
    end;
  end;
end;
