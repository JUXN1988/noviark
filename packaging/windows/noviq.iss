; Instalador de Noviark para Windows (Inno Setup 6)
#define MyAppName "Noviark"
#define MyAppVersion "4.2.0"
#define MyAppPublisher "Noviark Labs"
#define MyAppURL "https://github.com/JUXN1988/noviark"
#define MyAppExeName "Noviark.exe"

[Setup]
AppId={{8F1C2A4E-6B3D-4E8A-9C71-5D2F0B9A7E13}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppPublisher={#MyAppPublisher}
AppPublisherURL={#MyAppURL}
AppSupportURL={#MyAppURL}
DefaultDirName={autopf}\Noviark
DefaultGroupName=Noviark
DisableProgramGroupPage=yes
LicenseFile=..\..\LICENSE.md
OutputDir=..\..\dist
OutputBaseFilename=Noviark-Setup-Windows
SetupIconFile=..\..\static\noviq.ico
UninstallDisplayIcon={app}\{#MyAppExeName}
Compression=lzma2/ultra
SolidCompression=yes
WizardStyle=modern
PrivilegesRequired=lowest
PrivilegesRequiredOverridesAllowed=dialog
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible

[Languages]
Name: "spanish"; MessagesFile: "compiler:Languages\Spanish.isl"
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"
Name: "startup"; Description: "Iniciar Noviark con Windows (para las tareas programadas)"; GroupDescription: "Opciones:"; Flags: unchecked

[Files]
Source: "..\..\dist\Noviark\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{group}\Noviark"; Filename: "{app}\{#MyAppExeName}"
Name: "{group}\Desinstalar Noviark"; Filename: "{uninstallexe}"
Name: "{autodesktop}\Noviark"; Filename: "{app}\{#MyAppExeName}"; Tasks: desktopicon
Name: "{userstartup}\Noviark"; Filename: "{app}\{#MyAppExeName}"; Parameters: "--no-browser"; Tasks: startup

[Run]
Filename: "{app}\{#MyAppExeName}"; Description: "Abrir Noviark ahora"; Flags: nowait postinstall skipifsilent

[UninstallRun]
Filename: "{app}\{#MyAppExeName}"; Parameters: "--stop"; Flags: runhidden; RunOnceId: "StopNoviark"
