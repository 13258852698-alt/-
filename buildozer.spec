[app]

title = CAV
package.name = cav
package.domain = org.cav
source.dir = .
source.include_exts = py,png,jpg,kv,atlas
version = 0.1
build_dir = ./build
bin_dir = ./bin

orientation = landscape

android.api = 21
android.ndk = 25b
android.sdk = 24
android.ndk_api = 21
android.permissions = INTERNET,ACCESS_NETWORK_STATE
android.add_activiy = false

requirements = python3,kivy

p4a.source_dir = 
p4a.local_recipes = 
p4a.libSDL2_ttf = 

buildozer.android.debug = false

[buildozer]
log_level = 2
warn_on_root = 1