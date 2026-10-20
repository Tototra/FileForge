; FileForge - installateur Windows en un seul fichier (compilé par tools/build.py avec makensis)
;   makensis /DSTAGE=<dossier préparé> /DVERSION=1.0.0 /DOUTFILE=FileForge-Setup.exe FileForge.nsi
; Installation pour l'utilisateur courant uniquement : aucun droit administrateur.
; Mode silencieux : FileForge-Setup.exe /S
; Conversions Office : Microsoft Office s'il est installé (Word, PowerPoint, Excel), sinon LibreOffice est installé.

Unicode true
SetCompressor /SOLID lzma
RequestExecutionLevel user
ManifestDPIAware true

!include "MUI2.nsh"
!include "LogicLib.nsh"
!include "FileFunc.nsh"
!include "Sections.nsh"

Name "FileForge"
Caption "Installation de FileForge"
OutFile "${OUTFILE}"
InstallDir "$LOCALAPPDATA\FileForge"
BrandingText "FileForge ${VERSION}"
ShowInstDetails show
ShowUninstDetails show

VIProductVersion "${VERSION}.0"
VIAddVersionKey /LANG=1036 "ProductName" "FileForge"
VIAddVersionKey /LANG=1036 "FileDescription" "Installation de FileForge"
VIAddVersionKey /LANG=1036 "FileVersion" "${VERSION}"
VIAddVersionKey /LANG=1036 "ProductVersion" "${VERSION}"
VIAddVersionKey /LANG=1036 "LegalCopyright" "FileForge, logiciel libre"

!define MUI_ICON "${STAGE}\app\icon.ico"
!define MUI_UNICON "${STAGE}\app\icon.ico"
!define MUI_WELCOMEFINISHPAGE_BITMAP "${STAGE}\wizard.bmp"
!define MUI_UNWELCOMEFINISHPAGE_BITMAP "${STAGE}\wizard.bmp"
!define MUI_ABORTWARNING
!define MUI_ABORTWARNING_TEXT "Arrêter l'installation de FileForge ?"

!define MUI_WELCOMEPAGE_TITLE "Installer FileForge"
!define MUI_WELCOMEPAGE_TEXT "FileForge convertit, compresse, rogne et signe tes fichiers depuis une roue qui s'ouvre d'un clic droit.$\r$\n$\r$\nL'installation prend quelques minutes et télécharge ce qu'il faut (environ 300 Mo, et 350 Mo de plus pour LibreOffice si Microsoft Office n'est pas installé). FileForge ne demande aucun mot de passe administrateur et ne touche à rien en dehors de ton compte.$\r$\n$\r$\nTout se passe ensuite sur ton ordinateur : aucun fichier n'est envoyé sur Internet."
!insertmacro MUI_PAGE_WELCOME


!define MUI_PAGE_HEADER_TEXT "Installation en cours"
!define MUI_PAGE_HEADER_SUBTEXT "Laisse la fenêtre ouverte, ça peut prendre quelques minutes."
!insertmacro MUI_PAGE_INSTFILES

!define MUI_FINISHPAGE_TITLE "FileForge est installé"
!define MUI_FINISHPAGE_TEXT "Pour l'utiliser :$\r$\n$\r$\n•  clic droit sur un fichier, puis FileForge…$\r$\n    (Windows 11 : « Afficher d'autres options »)$\r$\n•  ou Ctrl + Alt + F dans l'Explorateur$\r$\n•  Ctrl + Alt + G partout : chercher un fichier par son nom$\r$\n•  ou glisse des fichiers sur l'icône FileForge du Bureau"
!define MUI_FINISHPAGE_RUN
!define MUI_FINISHPAGE_RUN_TEXT "Ouvrir FileForge maintenant"
!define MUI_FINISHPAGE_RUN_FUNCTION LaunchWheel
!insertmacro MUI_PAGE_FINISH

!insertmacro MUI_UNPAGE_CONFIRM
!insertmacro MUI_UNPAGE_INSTFILES

!insertmacro MUI_LANGUAGE "French"

Var Failed

!macro RunStep STEP LABEL
  ${If} $Failed == ""
    DetailPrint "${LABEL}"
    nsExec::ExecToLog '"$SYSDIR\WindowsPowerShell\v1.0\powershell.exe" -NoProfile -ExecutionPolicy Bypass -File "$INSTDIR\install.ps1" -Step ${STEP} -Quiet'
    Pop $0
    ${If} $0 != "0"
      StrCpy $Failed "${LABEL}"
    ${EndIf}
  ${EndIf}
!macroend

Section "FileForge (convertir, compresser, éditer…)" SecMain
  SectionIn RO
  SetOutPath "$INSTDIR"
  SetDetailsPrint textonly
  DetailPrint "Copie des fichiers..."
  SetDetailsPrint both
  File /r "${STAGE}\app\*"
  File "${STAGE}\install.ps1"
  File "${STAGE}\uninstall.ps1"
  WriteUninstaller "$INSTDIR\Uninstall.exe"

  !insertmacro RunStep files "Préparation des fichiers"
  !insertmacro RunStep python "Téléchargement de Python (privé à FileForge)"
  !insertmacro RunStep libs "Bibliothèques PDF, images, vidéo et interface (quelques minutes)"
  !insertmacro RunStep ocr "Langues pour l'OCR (français, anglais)"
  !insertmacro RunStep webview "Moteur d'affichage de la roue"
  !insertmacro RunStep shell "Intégration à l'Explorateur Windows"
  ; Word / PowerPoint / Excel : Microsoft Office s'il est là, sinon LibreOffice (facultatif : un échec n'annule rien)
  ${If} $Failed == ""
    !insertmacro RunStep libreoffice "Conversions Word / PowerPoint / Excel : Microsoft Office, sinon LibreOffice (~350 Mo)"
    StrCpy $Failed ""
  ${EndIf}

  ${If} $Failed != ""
    DetailPrint "Échec : $Failed"
    IfSilent +2
    MessageBox MB_ICONSTOP|MB_OK "L'installation n'a pas pu se terminer ($Failed).$\r$\n$\r$\nVérifie ta connexion Internet puis relance FileForge-Setup.exe : ce qui est déjà téléchargé sera réutilisé.$\r$\n$\r$\nDétails : $INSTDIR\FileForge.log"
    SetErrorLevel 2
    Abort "L'installation a échoué."
  ${EndIf}

  ; Paramètres > Applications
  !define UNINST "Software\Microsoft\Windows\CurrentVersion\Uninstall\FileForge"
  WriteRegStr HKCU "${UNINST}" "DisplayName" "FileForge"
  WriteRegStr HKCU "${UNINST}" "DisplayVersion" "${VERSION}"
  WriteRegStr HKCU "${UNINST}" "Publisher" "FileForge"
  WriteRegStr HKCU "${UNINST}" "DisplayIcon" "$INSTDIR\icon.ico"
  WriteRegStr HKCU "${UNINST}" "InstallLocation" "$INSTDIR"
  WriteRegStr HKCU "${UNINST}" "UninstallString" '"$INSTDIR\Uninstall.exe"'
  WriteRegStr HKCU "${UNINST}" "QuietUninstallString" '"$INSTDIR\Uninstall.exe" /S'
  WriteRegStr HKCU "${UNINST}" "URLInfoAbout" "https://github.com/Tototra/FileForge"
  WriteRegDWORD HKCU "${UNINST}" "NoModify" 1
  WriteRegDWORD HKCU "${UNINST}" "NoRepair" 1
  ${GetSize} "$INSTDIR" "/S=0K" $0 $1 $2
  WriteRegDWORD HKCU "${UNINST}" "EstimatedSize" $0
  DetailPrint "FileForge est installé."
SectionEnd


Function .onInit
  ; Une seule installation à la fois
  System::Call 'kernel32::CreateMutex(p 0, i 0, t "FileForgeSetup") p .r1 ?e'
  Pop $R0
  ${If} $R0 == 183
    MessageBox MB_OK|MB_ICONINFORMATION "L'installation de FileForge est déjà en cours."
    Abort
  ${EndIf}
FunctionEnd

Function LaunchWheel
  Exec '"$INSTDIR\venv\Scripts\pythonw.exe" "$INSTDIR\wheel.py"'
FunctionEnd

Section "Uninstall"
  nsExec::ExecToLog '"$SYSDIR\WindowsPowerShell\v1.0\powershell.exe" -NoProfile -ExecutionPolicy Bypass -File "$INSTDIR\uninstall.ps1" -Quiet'
  Pop $0
  DeleteRegKey HKCU "Software\Microsoft\Windows\CurrentVersion\Uninstall\FileForge"
  SetOutPath "$TEMP"
  DetailPrint "Suppression des fichiers..."
  ; rmdir est bien plus rapide que RMDir /r sur les milliers de fichiers de Python
  nsExec::Exec '"$SYSDIR\cmd.exe" /c rmdir /s /q "$INSTDIR"'
  Pop $0
  RMDir /r "$INSTDIR"
SectionEnd
