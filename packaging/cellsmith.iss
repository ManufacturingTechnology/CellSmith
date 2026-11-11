; CellSmith Windows installer (Inno Setup 6).
; Compiled by build.bat:  ISCC /DAppVersion=<ver> packaging\cellsmith.iss
;
; NON-ADMIN FIRST: PrivilegesRequired=lowest installs per-user into
; {localappdata}\Programs\CellSmith with an HKCU uninstall entry and NO UAC
; prompt; PrivilegesRequiredOverridesAllowed=dialog lets a user who CAN elevate
; choose an all-users install (Program Files) at install time instead.
; Packages the PyInstaller ONEDIR output verbatim. Uninstall removes only the
; install dir + shortcuts - user data (caches/configs) lives beside the user's
; STEP files, never under {app}.

#ifndef AppVersion
  #define AppVersion "0.0.0"
#endif
#ifndef DistDir
  #define DistDir "..\dist\CellSmith"
#endif
#ifndef OutDir
  #define OutDir "..\dist"
#endif

[Setup]
AppId={{422704C8-B9DA-4036-BA57-805ACB645920}
AppName=CellSmith
AppVersion={#AppVersion}
AppPublisher=AMT
; Surfaced as the publisher/support/update links on the Apps & features entry.
AppPublisherURL=https://github.com/ManufacturingTechnology/CellSmith
AppSupportURL=https://github.com/ManufacturingTechnology/CellSmith/issues
AppUpdatesURL=https://github.com/ManufacturingTechnology/CellSmith/releases
DefaultDirName={autopf}\CellSmith
DefaultGroupName=CellSmith
DisableProgramGroupPage=yes
PrivilegesRequired=lowest
PrivilegesRequiredOverridesAllowed=dialog
OutputDir={#OutDir}
OutputBaseFilename=CellSmith-v{#AppVersion}-setup
Compression=lzma2
SolidCompression=yes
SetupIconFile=cellsmith.ico
UninstallDisplayIcon={app}\CellSmith.exe
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
WizardStyle=modern

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"; Flags: unchecked

[Files]
Source: "{#DistDir}\*"; DestDir: "{app}"; Flags: recursesubdirs ignoreversion

[Icons]
Name: "{autoprograms}\CellSmith"; Filename: "{app}\CellSmith.exe"
Name: "{autodesktop}\CellSmith"; Filename: "{app}\CellSmith.exe"; Tasks: desktopicon
