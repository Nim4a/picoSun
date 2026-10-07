# -*- mode: python ; coding: utf-8 -*-


a = Analysis(
    ['picasa_viewer.py'],
    pathex=[],
    binaries=[],
    datas=[('picoSun.ico', '.')],
    hiddenimports=['OpenEXR', 'Imath', 'rawpy', 'rawpy._rawpy'],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    # Only QtWidgets/Gui/Core + Multimedia (video) are used; everything else
    # (Qml, Quick, Pdf, Network, Sql, Svg, OpenGL, DBus, VirtualKeyboard) rode
    # along as PySide6 bulk and cost cold-start time + Defender scan for no
    # feature. Drop the whole families.
    excludes=[
        'PySide6.QtQml', 'PySide6.QtQuick', 'PySide6.QtQuickWidgets',
        'PySide6.QtQmlModels', 'PySide6.QtQmlMeta',
        'PySide6.QtPdf', 'PySide6.QtPdfWidgets', 'PySide6.QtNetwork',
        'PySide6.QtSql', 'PySide6.QtSvg', 'PySide6.QtSvgWidgets',
        'PySide6.QtOpenGL', 'PySide6.QtOpenGLWidgets', 'PySide6.QtDBus',
        'PySide6.QtVirtualKeyboard', 'PySide6.QtWebEngineWidgets',
        'PySide6.QtWebEngineCore', 'PySide6.QtWebChannel',
        'PySide6.QtWebSockets', 'PySide6.QtTest', 'PySide6.QtConcurrent',
        'PySide6.Qt3DCore', 'PySide6.Qt3DRender', 'PySide6.QtCharts',
        'PySide6.QtDataVisualization', 'PySide6.QtGraphs',
        'PySide6.QtBluetooth', 'PySide6.QtNfc', 'PySide6.QtSensors',
        'PySide6.QtPositioning', 'PySide6.QtLocation', 'PySide6.QtHelp',
        'PySide6.QtDesigner', 'PySide6.QtUiTools', 'PySide6.QtTextToSpeech',
    ],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name='picoSun',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=['picoSun.ico'],
)
coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name='picoSun',
)
