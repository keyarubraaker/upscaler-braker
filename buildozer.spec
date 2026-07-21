[app]
title = Anime Upscaler
package.name = animeupscaler
package.domain = com.animeupscaler

source.dir = .
source.include_exts = py,png,jpg,kv,atlas,json

version = 1.0

requirements = python3,kivy==2.2.1,requests,certifi

orientation = portrait
fullscreen = 0

android.minapi = 28
android.ndk = 25b
android.ndk_api = 21
android.archs = arm64-v8a

p4a.branch = v2024.01.21

android.permissions = INTERNET,READ_EXTERNAL_STORAGE,WRITE_EXTERNAL_STORAGE

android.allow_backup = True

[buildozer]
log_level = 2
warn_on_root = 1
