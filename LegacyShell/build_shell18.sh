#!/usr/bin/env bash
# Build native game-free nx18 shell against the legacy Metal 3 host.
# No game content, Xcode account, or gameplay claims.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
if [ "$#" -lt 1 ]; then echo "usage: build_shell18.sh legacy-nxnative [output-dir]" >&2; exit 2; fi
LEGACY="$1"
OUT="$ROOT/build/shell18"
if [ "$#" -ge 2 ]; then OUT="$2"; fi
mkdir -p "$OUT"
LEGACY="$(cd "$LEGACY" && pwd)"
OUT="$(cd "$OUT" && pwd)"

export GAME=0000000000000000
export DM_IOS_RENDERER=legacy
export DM_IOS_DEPLOYMENT_TARGET=17.0
export DM_BUNDLE_ID=org.nx18.shell
export DM_DISPLAY_NAME=nx18
export DM_APP_VERSION=0.2
export DM_APP_CATEGORY=public.app-category.action-games
export DM_TEAM_ID=0000000000
export DM_SCHEME_NAME=nx18
export DM_SHOW_FPS=NO
export DM_LANG=en-US
export DM_COPY_GAME_RESOURCES=NO
export DM_COPY_ROMFS=NO
export LC_ALL=C

cd "$LEGACY/dm/ios"
rm -rf Gen
mkdir -p Gen/dm/font Gen/Assets.xcassets
python3 tools/gen_build.py ../host Gen > Gen/dm.xcconfig
echo '// nx18: signed guest code loaded from Guest.framework, not embedded' > Gen/embed.S
touch Gen/dm/placeholder.tsv
printf '{"info":{"author":"xcode","version":1}}\n' > Gen/Assets.xcassets/Contents.json
echo 'DM_APPICON =' >> Gen/dm.xcconfig
# Link every iOS-compatible framework discovered from the real host Makefile.
echo 'OTHER_LDFLAGS = $(inherited) $(DM_FRAMEWORKS)' >> Gen/dm.xcconfig

python3 - Gen/dm.xcconfig <<'PY'
import pathlib, sys
p = pathlib.Path(sys.argv[1])
s = p.read_text()
anchor = 'OTHER_CFLAGS = $(inherited) '
assert s.count(anchor) == 1, 'generated C flags are unexpected'
p.write_text(s.replace(anchor, anchor + '-DNX18_SHELL=1 -DDM_SHELL=1 ', 1))
PY

FONT=''
for candidate in \
    '/System/Library/Fonts/Supplemental/Arial Unicode.ttf' \
    '/System/Library/Fonts/Supplemental/Arial.ttf'; do
    if [ -f "$candidate" ]; then FONT="$candidate"; break; fi
done
if [ -z "$FONT" ]; then
    echo "macOS standard font not found" >&2
    exit 1
fi
cp "$FONT" Gen/dm/font/standard.ttf
python3 "$LEGACY/dm/tools/make_ext_font.py" Gen/dm/font/nintendo_ext.ttf

xcodegen generate
xcodebuild \
  -project DmIOS.xcodeproj -scheme "$DM_SCHEME_NAME" \
  -configuration Release -destination 'generic/platform=iOS' \
  -derivedDataPath "$OUT/derived" \
  CODE_SIGNING_ALLOWED=NO CODE_SIGNING_REQUIRED=NO \
  DM_COPY_GAME_RESOURCES=NO DM_COPY_ROMFS=NO \
  DM_XCODE_OUTPUT_ROOT="$OUT/derived" \
  build > "$OUT/xcodebuild.log" 2>&1 || {
    grep -E 'error:|warning:' "$OUT/xcodebuild.log" | tail -35 || true
    echo "nx18: native compilation failed; log: $OUT/xcodebuild.log" >&2
    exit 1
  }

APP="$OUT/derived/Build/Products/Release-iphoneos/DmIOS.app"
[ -d "$APP" ] || { echo "No native shell app at $APP" >&2; exit 1; }

xcrun vtool -show-build "$APP/DmIOS" | tee "$OUT/macho-target.txt"
grep -Eq 'minos[[:space:]]+17\.0' "$OUT/macho-target.txt" || {
    echo "nx18: target unexpectedly not iOS 17" >&2; exit 1;
}
if otool -L "$APP/DmIOS" | grep -q 'libswift_DarwinFoundation2'; then
    echo 'nx18: invalid iOS26 Swift dependency' >&2; exit 1
fi
if otool -l "$APP/DmIOS" | grep -Eq 'sectname __dmmainx[01]'; then
    echo 'nx18: game code accidentally embedded in game-free host' >&2; exit 1
fi
mkdir -p "$OUT/Payload"
cp -R "$APP" "$OUT/Payload/DmIOS.app"
(
    cd "$OUT"
    zip -qry nx18-metal3-gamefree-unsigned.ipa Payload
    unzip -t nx18-metal3-gamefree-unsigned.ipa | tail -1
)
echo "nx18: game-free native Metal3 shell built; no AC2 gameplay claimed."
echo "Artifact: $OUT/nx18-metal3-gamefree-unsigned.ipa"
