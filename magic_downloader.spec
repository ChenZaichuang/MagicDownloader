# -*- mode: python ; coding: utf-8 -*-

block_cipher = None


a = Analysis(['magic_downloader.py'],
             pathex=['/Users/zcchen/Documents/PersonalCodebase/MagicDownloader'],
             binaries=[],
             datas=[],
             hiddenimports=[],
             hookspath=[],
             runtime_hooks=[],
             excludes=[],
             win_no_prefer_redirects=False,
             win_private_assemblies=False,
             cipher=block_cipher,
             noarchive=False)
pyz = PYZ(a.pure, a.zipped_data,
             cipher=block_cipher)
exe = EXE(pyz,
          a.scripts,
          [],
          exclude_binaries=True,
          name='magic_downloader',
          debug=False,
          bootloader_ignore_signals=False,
          strip=False,
          upx=True,
          console=False )
coll = COLLECT(exe,
               a.binaries,
               a.zipfiles,
               a.datas,
               strip=False,
               upx=True,
               upx_exclude=[],
               name='magic_downloader')
app = BUNDLE(coll,
             name='magic_downloader.app',
             icon='icon/magic.icns',
             bundle_identifier=None,
             info_plist={
             	'NSHighResolutionCapable': True,
             })
