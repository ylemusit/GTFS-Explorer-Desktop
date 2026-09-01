; Instalador por usuario de GTFS Explorer Desktop.
; Este script se guarda como UTF-8 con BOM (UTF8SIG) y se compila con NSIS 3
; Unicode. El payload se prepara fuera de Git por tools/build_installer.py.

Unicode true
RequestExecutionLevel user
SetCompressor /SOLID lzma
SetDateSave on

!include "MUI2.nsh"

!ifndef PRODUCT_VERSION
  !error "PRODUCT_VERSION debe definirse al compilar."
!endif
!ifndef PRODUCT_FILE_VERSION
  !error "PRODUCT_FILE_VERSION debe definirse al compilar."
!endif
!ifndef PRODUCT_NAME
  !error "PRODUCT_NAME debe definirse al compilar."
!endif
!ifndef PRODUCT_PUBLISHER
  !error "PRODUCT_PUBLISHER debe definirse al compilar."
!endif
!ifndef PRODUCT_DESCRIPTION
  !error "PRODUCT_DESCRIPTION debe definirse al compilar."
!endif
!ifndef PRODUCT_EDITION
  !error "PRODUCT_EDITION debe definirse al compilar."
!endif
!ifndef PRODUCT_COPYRIGHT_YEAR
  !error "PRODUCT_COPYRIGHT_YEAR debe definirse al compilar."
!endif
!ifndef PRODUCT_RIGHTS_NOTICE
  !error "PRODUCT_RIGHTS_NOTICE debe definirse al compilar."
!endif
!ifndef PRODUCT_EXECUTABLE
  !error "PRODUCT_EXECUTABLE debe definirse al compilar."
!endif
!ifndef PRODUCT_INSTALL_DIRECTORY
  !error "PRODUCT_INSTALL_DIRECTORY debe definirse al compilar."
!endif
!ifndef PRODUCT_START_MENU_DIRECTORY
  !error "PRODUCT_START_MENU_DIRECTORY debe definirse al compilar."
!endif
!ifndef PRODUCT_SHORTCUT_NAME
  !error "PRODUCT_SHORTCUT_NAME debe definirse al compilar."
!endif
!ifndef PAYLOAD_DIR
  !error "PAYLOAD_DIR debe definirse al compilar."
!endif
!ifndef INSTALLER_OUTPUT
  !error "INSTALLER_OUTPUT debe definirse al compilar."
!endif

!define PRODUCT_ICON "${PAYLOAD_DIR}\gtfs_explorer\resources\gtfs_explorer.ico"
!define MUI_ICON "${PRODUCT_ICON}"
!define MUI_UNICON "${PRODUCT_ICON}"

!define PRODUCT_REGISTRY_KEY "Software\Microsoft\Windows\CurrentVersion\Uninstall\${PRODUCT_NAME}"

VIProductVersion "${PRODUCT_FILE_VERSION}"
VIAddVersionKey /LANG=3082 "ProductName" "${PRODUCT_NAME}"
VIAddVersionKey /LANG=3082 "ProductVersion" "${PRODUCT_VERSION}"
VIAddVersionKey /LANG=3082 "FileVersion" "${PRODUCT_FILE_VERSION}"
VIAddVersionKey /LANG=3082 "CompanyName" "${PRODUCT_PUBLISHER}"
VIAddVersionKey /LANG=3082 "FileDescription" "${PRODUCT_DESCRIPTION}"
VIAddVersionKey /LANG=3082 "LegalCopyright" "© ${PRODUCT_COPYRIGHT_YEAR} ${PRODUCT_PUBLISHER} · ${PRODUCT_RIGHTS_NOTICE}"

Name "${PRODUCT_NAME} ${PRODUCT_VERSION}"
OutFile "${INSTALLER_OUTPUT}"
InstallDir "$LOCALAPPDATA\Programs\${PRODUCT_INSTALL_DIRECTORY}"
InstallDirRegKey HKCU "${PRODUCT_REGISTRY_KEY}" "InstallLocation"
ShowInstDetails show
ShowUninstDetails show

!define MUI_ABORTWARNING
!define MUI_FINISHPAGE_RUN "$INSTDIR\${PRODUCT_EXECUTABLE}"
!define MUI_FINISHPAGE_RUN_TEXT "Abrir GTFS Explorer"
!define MUI_FINISHPAGE_SHOWREADME "$INSTDIR\docs\USER_GUIDE.md"
!define MUI_FINISHPAGE_SHOWREADME_TEXT "Ver guía / README"
!define MUI_WELCOMEPAGE_TITLE "Bienvenido a ${PRODUCT_NAME}"
!define MUI_WELCOMEPAGE_TEXT "${PRODUCT_NAME} es una herramienta profesional para importar, explorar, validar, visualizar y exportar GTFS Schedule de forma local y offline-first.$\r$\n$\r$\nEdición ${PRODUCT_EDITION}$\r$\nCreado y desarrollado por ${PRODUCT_PUBLISHER}.$\r$\n© ${PRODUCT_COPYRIGHT_YEAR} ${PRODUCT_PUBLISHER} · ${PRODUCT_RIGHTS_NOTICE}$\r$\n$\r$\nEl instalador configurará la aplicación para el usuario actual, sin requerir permisos de administrador."

!insertmacro MUI_PAGE_WELCOME
!insertmacro MUI_PAGE_DIRECTORY
!insertmacro MUI_PAGE_INSTFILES
!insertmacro MUI_PAGE_FINISH
!insertmacro MUI_UNPAGE_CONFIRM
!insertmacro MUI_UNPAGE_INSTFILES
!insertmacro MUI_LANGUAGE "Spanish"

Function .onInit
  SetShellVarContext current
FunctionEnd

Section "${PRODUCT_NAME}" SEC_MAIN
  ; Una actualización se instala en la misma ubicación. Solo se reemplaza el
  ; directorio de la aplicación; el workspace de usuario queda fuera de él.
  IfFileExists "$INSTDIR\uninstall.exe" 0 +2
    RMDir /r "$INSTDIR"
  SetOutPath "$INSTDIR"
  File /r "${PAYLOAD_DIR}\*.*"
  WriteUninstaller "$INSTDIR\uninstall.exe"

  CreateDirectory "$SMPROGRAMS\${PRODUCT_START_MENU_DIRECTORY}"
  CreateShortcut "$SMPROGRAMS\${PRODUCT_START_MENU_DIRECTORY}\${PRODUCT_SHORTCUT_NAME}" "$INSTDIR\${PRODUCT_EXECUTABLE}"
  CreateShortcut "$DESKTOP\${PRODUCT_SHORTCUT_NAME}" "$INSTDIR\${PRODUCT_EXECUTABLE}"

  WriteRegStr HKCU "${PRODUCT_REGISTRY_KEY}" "DisplayName" "${PRODUCT_NAME}"
  WriteRegStr HKCU "${PRODUCT_REGISTRY_KEY}" "DisplayVersion" "${PRODUCT_VERSION}"
  WriteRegStr HKCU "${PRODUCT_REGISTRY_KEY}" "Publisher" "${PRODUCT_PUBLISHER}"
  WriteRegStr HKCU "${PRODUCT_REGISTRY_KEY}" "InstallLocation" "$INSTDIR"
  WriteRegStr HKCU "${PRODUCT_REGISTRY_KEY}" "DisplayIcon" "$INSTDIR\${PRODUCT_EXECUTABLE}"
  WriteRegStr HKCU "${PRODUCT_REGISTRY_KEY}" "UninstallString" "$\"$INSTDIR\uninstall.exe$\""
  WriteRegDWORD HKCU "${PRODUCT_REGISTRY_KEY}" "NoModify" 1
  WriteRegDWORD HKCU "${PRODUCT_REGISTRY_KEY}" "NoRepair" 1
SectionEnd

Section "Uninstall"
  SetShellVarContext current
  Delete "$SMPROGRAMS\${PRODUCT_START_MENU_DIRECTORY}\${PRODUCT_SHORTCUT_NAME}"
  RMDir "$SMPROGRAMS\${PRODUCT_START_MENU_DIRECTORY}"
  Delete "$DESKTOP\${PRODUCT_SHORTCUT_NAME}"
  DeleteRegKey HKCU "${PRODUCT_REGISTRY_KEY}"

  ; No borrar $LOCALAPPDATA\GTFS Explorer: contiene proyectos, caché, logs y ajustes.
  RMDir /r "$INSTDIR"
SectionEnd
