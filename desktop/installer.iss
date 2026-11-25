; Inno Setup script for the LinkDrop Windows installer.
; Built by .github/workflows/desktop.yml:  iscc /DAppVersion=1.1.0 desktop\installer.iss
#ifndef AppVersion
  #define AppVersion "1.2.0"
#endif

[Setup]
AppId={{6C1C2E7B-7E0B-4F3C-9A1E-6B2E1C9D8A41}
AppName=LinkDrop
AppVersion={#AppVersion}
AppPublisher=Raslan Kiwan
AppPublisherURL=https://github.com/raslankiwan/linkdrop
DefaultDirName={autopf}\LinkDrop
DefaultGroupName=LinkDrop
DisableProgramGroupPage=yes
PrivilegesRequired=lowest
PrivilegesRequiredOverridesAllowed=dialog
OutputDir=..\dist
OutputBaseFilename=LinkDrop-{#AppVersion}-windows-setup
SetupIconFile=..\build\icon.ico
UninstallDisplayIcon={app}\LinkDrop.exe
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
ArchitecturesInstallIn64BitMode=x64compatible

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"

[Files]
Source: "..\dist\LinkDrop\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{autoprograms}\LinkDrop"; Filename: "{app}\LinkDrop.exe"
Name: "{autodesktop}\LinkDrop"; Filename: "{app}\LinkDrop.exe"; Tasks: desktopicon

[Run]
Filename: "{app}\LinkDrop.exe"; Description: "{cm:LaunchProgram,LinkDrop}"; Flags: nowait postinstall skipifsilent
