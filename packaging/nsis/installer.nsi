; Instalador por usuario de GTFS Explorer Desktop.
; El payload se prepara fuera de Git por tools/build_installer.py.

Unicode true
RequestExecutionLevel user
SetCompressor /SOLID lzma
SetDateSave on

!ifndef PRODUCT_VERSION
  !error "PRODUCT_VERSION debe definirse al compilar."
!endif
!ifndef PAYLOAD_DIR
  !error "PAYLOAD_DIR debe definirse al compilar."
!endif
!ifndef INSTALLER_OUTPUT
  !error "INSTALLER_OUTPUT debe definirse al compilar."
!endif

!define PRODUCT_NAME "GTFS Explorer Desktop"
!define PRODUCT_PUBLISHER "Yeison Arbey Carrillo Lemus"
!define PRODUCT_REGISTRY_KEY "Software\Microsoft\Windows\CurrentVersion\Uninstall\GTFS Explorer Desktop"

Name "${PRODUCT_NAME} ${PRODUCT_VERSION}"
OutFile "${INSTALLER_OUTPUT}"
InstallDir "$LOCALAPPDATA\Programs\GTFS Explorer"
InstallDirRegKey HKCU "${PRODUCT_REGISTRY_KEY}" "InstallLocation"
ShowInstDetails show
ShowUninstDetails show

Page directory
Page instfiles
UninstPage uninstConfirm
UninstPage instfiles

Function .onInit
  SetShellVarContext current
FunctionEnd

Section "GTFS Explorer Desktop" SEC_MAIN
  ; Una actualización se instala en la misma ubicación. Solo se reemplaza el
  ; directorio de la aplicación: el workspace vive en $LOCALAPPDATA\GTFS Explorer.
  IfFileExists "$INSTDIR\uninstall.exe" 0 +2
    RMDir /r "$INSTDIR"
  SetOutPath "$INSTDIR"
  File /r "${PAYLOAD_DIR}\*.*"
  WriteUninstaller "$INSTDIR\uninstall.exe"

  CreateDirectory "$SMPROGRAMS\GTFS Explorer"
  CreateShortcut "$SMPROGRAMS\GTFS Explorer\GTFS Explorer Desktop.lnk" "$INSTDIR\GTFS Explorer.exe"
  CreateShortcut "$DESKTOP\GTFS Explorer Desktop.lnk" "$INSTDIR\GTFS Explorer.exe"

  WriteRegStr HKCU "${PRODUCT_REGISTRY_KEY}" "DisplayName" "${PRODUCT_NAME}"
  WriteRegStr HKCU "${PRODUCT_REGISTRY_KEY}" "DisplayVersion" "${PRODUCT_VERSION}"
  WriteRegStr HKCU "${PRODUCT_REGISTRY_KEY}" "Publisher" "${PRODUCT_PUBLISHER}"
  WriteRegStr HKCU "${PRODUCT_REGISTRY_KEY}" "InstallLocation" "$INSTDIR"
  WriteRegStr HKCU "${PRODUCT_REGISTRY_KEY}" "DisplayIcon" "$INSTDIR\GTFS Explorer.exe"
  WriteRegStr HKCU "${PRODUCT_REGISTRY_KEY}" "UninstallString" "$\"$INSTDIR\uninstall.exe$\""
  WriteRegDWORD HKCU "${PRODUCT_REGISTRY_KEY}" "NoModify" 1
  WriteRegDWORD HKCU "${PRODUCT_REGISTRY_KEY}" "NoRepair" 1
SectionEnd

Section "Uninstall"
  SetShellVarContext current
  Delete "$SMPROGRAMS\GTFS Explorer\GTFS Explorer Desktop.lnk"
  RMDir "$SMPROGRAMS\GTFS Explorer"
  Delete "$DESKTOP\GTFS Explorer Desktop.lnk"
  DeleteRegKey HKCU "${PRODUCT_REGISTRY_KEY}"

  ; No borrar $LOCALAPPDATA\GTFS Explorer: contiene proyectos, caché, logs y ajustes.
  RMDir /r "$INSTDIR"
SectionEnd
