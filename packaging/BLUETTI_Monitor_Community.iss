#define MyAppName "BLUETTI Monitor"
#define MyAppVersion "0.2.61"
#define MyAppPublisher "BLUETTI Monitor Community Project"
#define MyAppExeName "BLUETTI Monitor.exe"

[Setup]
AppId={{8D247E37-05C1-4A5A-82A2-3F5DFD56E6C7}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppPublisher={#MyAppPublisher}
DefaultDirName={autopf}\BLUETTI Monitor
DefaultGroupName=BLUETTI Monitor
DisableProgramGroupPage=yes
OutputDir=..\installer_output
OutputBaseFilename=BLUETTI_Monitor_v{#MyAppVersion}_Setup
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
PrivilegesRequired=admin
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
UninstallDisplayName={#MyAppName} {#MyAppVersion}
SetupLogging=yes
CloseApplications=yes
RestartApplications=no

[Tasks]
Name: "desktopicon"; Description: "Create a &desktop shortcut"; GroupDescription: "Additional shortcuts:"; Flags: unchecked

[Files]
Source: "..\dist\BLUETTI Monitor\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{group}\BLUETTI Monitor"; Filename: "{app}\{#MyAppExeName}"; WorkingDir: "{app}"
Name: "{autodesktop}\BLUETTI Monitor"; Filename: "{app}\{#MyAppExeName}"; WorkingDir: "{app}"; Tasks: desktopicon

[Run]
Filename: "{app}\{#MyAppExeName}"; Description: "Launch BLUETTI Monitor"; Flags: nowait postinstall skipifsilent
