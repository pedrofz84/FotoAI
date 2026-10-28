[Setup]
AppName=FotoAI
AppVersion=1.0.0
Publisher=Pedro Silva
DefaultDirName={autopf}\FotoAI
DefaultGroupName=FotoAI
OutputDir=.\Output
OutputBaseFilename=FotoAISetup_v1.0.0
Compression=lzma2/ultra64
SolidCompression=yes
ArchitecturesInstallIn64BitMode=x64
; PrivilegesRequired=lowest instala no %LOCALAPPDATA%\Programs se o user não for Admin, 
; sem pedir UAC, tornando a conversão perfeita para apps modernas.
PrivilegesRequired=lowest
PrivilegesRequiredOverridesAllowed=dialog

[Dirs]
; Garante que as pastas de sistema do utilizador não dão erro de acessos
Name: "{localappdata}\FotoAI"; Flags: uninsneveruninstall

[Files]
; 1. WPF Desktop App (Compilação C# AOT / Self-Contained)
; Assume uso de: dotnet publish -c Release -r win-x64 --self-contained
Source: "..\src\FotoAI.Desktop\bin\Release\net8.0-windows\win-x64\publish\*"; DestDir: "{app}\UI"; Flags: ignoreversion recursesubdirs createallsubdirs

; 2. Python Engine (Pacote PyInstaller)
; Assume uso de: pyinstaller --name engine --onedir main.py
Source: "..\src\FotoAI.Engine\dist\engine\*"; DestDir: "{app}\Engine"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{group}\FotoAI"; Filename: "{app}\UI\FotoAI.Desktop.exe"
Name: "{autodesktop}\FotoAI"; Filename: "{app}\UI\FotoAI.Desktop.exe"; Tasks: desktopicon

[Tasks]
Name: "desktopicon"; Description: "Criar ícone no Ambiente de Trabalho"; GroupDescription: "Atalhos Adicionais:"

[Run]
Filename: "{app}\UI\FotoAI.Desktop.exe"; Description: "Iniciar FotoAI agora"; Flags: nowait postinstall skipifsilent

[UninstallDelete]
; Apaga as pastas binárias da instalação C:\Program Files\FotoAI
Type: filesandordirs; Name: "{app}"
; (Nota de Segurança Crítica: Não apagamos sob qualquer pretexto a pasta %LOCALAPPDATA%\FotoAI no Uninstaller 
; de forma a não destruir 50h de indexação vetorial se o utilzador apenas quiser instalar um update patch).
