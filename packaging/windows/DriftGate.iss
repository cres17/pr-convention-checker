; Inno Setup script for the Windows installer (built in CI by desktop-build.yml).
; Compile: ISCC /DAppVersion=1.2.3 /DSourceDir=<dist\DriftGate> /O<output dir> DriftGate.iss
#ifndef AppVersion
  #define AppVersion "0.0.0-dev"
#endif
#ifndef SourceDir
  #define SourceDir "..\..\dist\DriftGate"
#endif

[Setup]
; Keep this GUID: it identifies the app so a new installer upgrades the old install.
AppId={{E22B1472-8C0E-4924-9E32-7BBDBB5A4DE9}
AppName=Cross Agent (Drift Gate)
AppVersion={#AppVersion}
AppPublisher=cres17
DefaultDirName={autopf}\DriftGate
DefaultGroupName=Cross Agent
DisableProgramGroupPage=yes
; Per-user install by default (no admin prompt); the wizard offers "for all users".
PrivilegesRequired=lowest
PrivilegesRequiredOverridesAllowed=dialog
OutputBaseFilename=DriftGate-Windows-Setup
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
UninstallDisplayIcon={app}\DriftGate.exe

[Tasks]
Name: "desktopicon"; Description: "Create a desktop shortcut"; Flags: unchecked

[Files]
Source: "{#SourceDir}\*"; DestDir: "{app}"; Flags: recursesubdirs createallsubdirs ignoreversion

[Icons]
Name: "{group}\Cross Agent"; Filename: "{app}\DriftGate.exe"
Name: "{autodesktop}\Cross Agent"; Filename: "{app}\DriftGate.exe"; Tasks: desktopicon

[Run]
Filename: "{app}\DriftGate.exe"; Description: "Launch Cross Agent"; Flags: nowait postinstall skipifsilent
