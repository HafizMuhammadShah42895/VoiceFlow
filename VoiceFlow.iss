[Setup]
AppName=VoiceFlow
; Keep in sync with voiceflow_core/version.py (CI fails if they differ).
AppVersion=3.1.0
AppPublisher=Waliq
DefaultDirName={autopf}\VoiceFlow
DefaultGroupName=VoiceFlow
OutputDir=dist
OutputBaseFilename=VoiceFlow_Setup
Compression=lzma2
SolidCompression=yes
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
SetupIconFile=app.ico

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"; Flags: unchecked

[Files]
; Notice the source is the onefile executable. We'll change the pyinstaller script to make a onefile build.
Source: "dist\VoiceFlow.exe"; DestDir: "{app}"; Flags: ignoreversion

[Icons]
Name: "{group}\VoiceFlow"; Filename: "{app}\VoiceFlow.exe"
Name: "{autodesktop}\VoiceFlow"; Filename: "{app}\VoiceFlow.exe"; Tasks: desktopicon

[Run]
Filename: "{app}\VoiceFlow.exe"; Description: "{cm:LaunchProgram,VoiceFlow}"; Flags: nowait postinstall skipifsilent
